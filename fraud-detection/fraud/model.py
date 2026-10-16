"""Training, threshold selection and the model registry.

All models are free, open-source scikit-learn estimators. We train several,
keep the one with the best precision-recall AUC, and store it in Postgres.
"""
import io
import json
from dataclasses import dataclass, field
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .features import (ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES,
                       history_complete_from, load_features)

# Business costs used to pick the decision threshold: a missed fraud hurts
# far more than asking a legit customer to confirm a purchase.
COST_MISSED_FRAUD = 5.0
COST_FALSE_ALARM = 1.0

# Course correction: frauds the deployed model missed get extra weight in the
# next training run, and recent rows count more than old ones.
MISSED_FRAUD_WEIGHT = 3.0
RECENCY_HALF_LIFE_DAYS = 7.0


def candidate_models() -> dict:
    return {
        "logistic_regression": LogisticRegression(max_iter=2000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=200, min_samples_leaf=3, class_weight="balanced_subsample",
            n_jobs=-1, random_state=42),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, class_weight="balanced", random_state=42),
    }


def build_pipeline(estimator) -> Pipeline:
    preprocess = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ])
    return Pipeline([("prep", preprocess), ("clf", estimator)])


def sample_weights(df: pd.DataFrame) -> np.ndarray:
    age_days = (df["txn_time"].max() - df["txn_time"]).dt.total_seconds() / 86400
    weights = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
    missed = (df["is_fraud"] == 1) & (df["was_flagged"] == False)  # noqa: E712 (NaN = never scored)
    return np.where(missed, weights * MISSED_FRAUD_WEIGHT, weights)


def pick_threshold(y: np.ndarray, scores: np.ndarray) -> float:
    """Threshold that minimises expected business cost on validation data."""
    candidates = np.unique(np.concatenate([np.quantile(scores, np.linspace(0, 1, 401)), [0.5]]))
    costs = [COST_MISSED_FRAUD * np.sum((scores < t) & (y == 1))
             + COST_FALSE_ALARM * np.sum((scores >= t) & (y == 0)) for t in candidates]
    return float(candidates[int(np.argmin(costs))])


def evaluate(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    pred = scores >= threshold
    return {
        "pr_auc": float(average_precision_score(y, scores)) if y.any() else float("nan"),
        "roc_auc": float(roc_auc_score(y, scores)) if 0 < y.sum() < len(y) else float("nan"),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "cost": float(COST_MISSED_FRAUD * np.sum(~pred & (y == 1))
                      + COST_FALSE_ALARM * np.sum(pred & (y == 0))),
        "n": int(len(y)),
        "n_fraud": int(y.sum()),
    }


def feature_profile(X: pd.DataFrame, bins: int = 10) -> dict:
    """Quantile bins of each numeric feature: the 'expected' distribution for drift checks."""
    profile = {}
    for col in NUMERIC_FEATURES:
        values = X[col].to_numpy(dtype=float)
        edges = np.unique(np.quantile(values, np.linspace(0, 1, bins + 1)[1:-1]))
        counts = np.bincount(np.searchsorted(edges, values, side="left"), minlength=len(edges) + 1)
        profile[col] = {"edges": edges.tolist(), "props": (counts / counts.sum()).tolist()}
    return profile


@dataclass
class TrainedModel:
    algorithm: str
    pipeline: Pipeline
    threshold: float
    trained_from: datetime
    trained_to: datetime
    n_train: int
    metrics: dict
    profile: dict = field(repr=False)
    model_id: int | None = None

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict_proba(X[ALL_FEATURES])[:, 1]


def train(engine: Engine, start: datetime, end: datetime, valid_frac: float = 0.25) -> TrainedModel:
    """Train every candidate on labeled data in [start, end); keep the best one.

    The split is by *time* (train on the past, validate on the most recent
    slice) because that's how the model will be used: predicting the future.
    """
    start = max(start, history_complete_from(engine))
    df = load_features(engine, start, end, labeled_only=True)
    if df.empty or df["is_fraud"].sum() < 10:
        raise ValueError(f"Not enough labeled fraud between {start} and {end} to train")

    cut = df["txn_time"].quantile(1 - valid_frac)
    train_df, valid_df = df[df["txn_time"] < cut], df[df["txn_time"] >= cut]
    y_train, y_valid = train_df["is_fraud"].to_numpy(), valid_df["is_fraud"].to_numpy()

    results = {}
    for name, estimator in candidate_models().items():
        pipe = build_pipeline(estimator)
        pipe.fit(train_df[ALL_FEATURES], y_train, clf__sample_weight=sample_weights(train_df))
        scores = pipe.predict_proba(valid_df[ALL_FEATURES])[:, 1]
        threshold = pick_threshold(y_valid, scores)
        results[name] = {**evaluate(y_valid, scores, threshold), "threshold": threshold}

    best = max(results, key=lambda n: results[n]["pr_auc"])
    # Refit the winner on all the data (train + validation) so it sees the latest patterns.
    final = build_pipeline(candidate_models()[best])
    final.fit(df[ALL_FEATURES], df["is_fraud"].to_numpy(), clf__sample_weight=sample_weights(df))

    return TrainedModel(
        algorithm=best, pipeline=final, threshold=results[best]["threshold"],
        trained_from=df["txn_time"].min().to_pydatetime(),
        trained_to=df["txn_time"].max().to_pydatetime(),
        n_train=len(df), metrics={"selected": best, "candidates": results},
        profile=feature_profile(df),
    )


# ---------------------------------------------------------------- registry --

def register(engine: Engine, model: TrainedModel, status: str, reason: str) -> int:
    buf = io.BytesIO()
    joblib.dump(model.pipeline, buf)
    with engine.begin() as conn:
        if status == "champion":
            conn.execute(text(
                "UPDATE fraud.model_registry SET status = 'retired' WHERE status = 'champion'"))
        model.model_id = conn.execute(text("""
            INSERT INTO fraud.model_registry
                (algorithm, status, threshold, trained_from, trained_to, n_train,
                 metrics, feature_profile, reason, artifact)
            VALUES (:algorithm, :status, :threshold, :trained_from, :trained_to, :n_train,
                    CAST(:metrics AS jsonb), CAST(:profile AS jsonb), :reason, :artifact)
            RETURNING model_id
        """), {
            "algorithm": model.algorithm, "status": status, "threshold": model.threshold,
            "trained_from": model.trained_from, "trained_to": model.trained_to,
            "n_train": model.n_train, "metrics": json.dumps(model.metrics),
            "profile": json.dumps(model.profile), "reason": reason, "artifact": buf.getvalue(),
        }).scalar_one()
    return model.model_id


def load_champion(engine: Engine) -> TrainedModel | None:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM fraud.model_registry WHERE status = 'champion'")).mappings().first()
    if row is None:
        return None
    return TrainedModel(
        algorithm=row["algorithm"], pipeline=joblib.load(io.BytesIO(row["artifact"])),
        threshold=row["threshold"], trained_from=row["trained_from"],
        trained_to=row["trained_to"], n_train=row["n_train"], metrics=row["metrics"],
        profile=row["feature_profile"], model_id=row["model_id"],
    )
