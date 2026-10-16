"""Monitoring and course correction.

Every run answers three questions:

1. Is the champion still good? Compare its live predictions with the labels
   that have come in since (precision / recall).
2. Has the data changed? Compare recent feature distributions with the ones
   the champion was trained on (Population Stability Index). This works even
   before labels arrive, so it is an early warning.
3. If either looks bad: train a challenger on recent data (with missed frauds
   up-weighted), compare both on the newest labeled data the challenger did
   not train on, and promote the challenger only if it is actually better.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .features import load_features
from .model import evaluate, load_champion, register, train

MIN_RECALL = 0.70
MIN_PRECISION = 0.25
PSI_THRESHOLD = 0.25          # > 0.25 is the common rule of thumb for "significant shift"
MIN_FRAUD_TO_JUDGE = 10       # don't judge recall on a handful of cases
MONITOR_WINDOW_DAYS = 3
TRAIN_WINDOW_DAYS = 14        # sliding window: old fraud patterns fade out
HOLDOUT_DAYS = 1


def psi(expected_props: list[float], edges: list[float], actual: np.ndarray) -> float:
    counts = np.bincount(np.searchsorted(edges, actual, side="left"), minlength=len(edges) + 1)
    e = np.clip(np.asarray(expected_props), 1e-4, None)
    a = np.clip(counts / max(counts.sum(), 1), 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def drift_report(profile: dict, recent: pd.DataFrame) -> dict[str, float]:
    return {col: psi(p["props"], p["edges"], recent[col].to_numpy(dtype=float))
            for col, p in profile.items() if col in recent}


def live_performance(engine: Engine, model_id: int, start: datetime, end: datetime) -> dict:
    """Precision/recall of the champion's real predictions, for rows that now have labels."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT p.predicted_fraud, l.is_fraud
            FROM fraud.predictions p
            JOIN fraud.fraud_labels l USING (transaction_id)
            JOIN fraud.transactions t USING (transaction_id)
            WHERE p.model_id = :m AND t.txn_time >= :start AND t.txn_time < :end
        """), conn, params={"m": model_id, "start": start, "end": end})
    pred, y = df["predicted_fraud"].to_numpy(bool), df["is_fraud"].to_numpy(bool)
    tp = int(np.sum(pred & y))
    return {
        "n_labeled": len(df), "n_fraud": int(y.sum()),
        "precision": float(tp / pred.sum()) if pred.sum() else None,
        "recall": float(tp / y.sum()) if y.sum() else None,
    }


@dataclass
class MonitorResult:
    action: str
    model_id: int | None
    perf: dict = field(default_factory=dict)
    max_psi: float | None = None
    drifted_feature: str | None = None
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _latest_label_time(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT MAX(t.txn_time) FROM fraud.fraud_labels l JOIN fraud.transactions t USING (transaction_id)
        """)).scalar()


def _log(engine: Engine, as_of: datetime, r: MonitorResult) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO fraud.monitoring_runs (as_of, model_id, n_labeled, n_fraud, precision,
                recall, max_psi, drifted_feature, action, details)
            VALUES (:as_of, :model_id, :n_labeled, :n_fraud, :precision, :recall, :max_psi,
                    :drifted_feature, :action, CAST(:details AS jsonb))
        """), {
            "as_of": as_of, "model_id": r.model_id, "n_labeled": r.perf.get("n_labeled"),
            "n_fraud": r.perf.get("n_fraud"), "precision": r.perf.get("precision"),
            "recall": r.perf.get("recall"), "max_psi": r.max_psi,
            "drifted_feature": r.drifted_feature, "action": r.action,
            "details": json.dumps({"reasons": r.reasons, **r.details}, default=str),
        })


def course_correct(engine: Engine, as_of: datetime) -> MonitorResult:
    """Run one monitoring cycle and retrain/promote if needed."""
    label_end = _latest_label_time(engine)
    champion = load_champion(engine)

    # -- No model yet: train the first one on everything labeled. --
    if champion is None:
        model = train(engine, datetime(1970, 1, 1), as_of)
        model_id = register(engine, model, "champion", "initial model")
        r = MonitorResult("initial", model_id, details={"validation": model.metrics})
        _log(engine, as_of, r)
        return r

    # -- 1. Live performance on the most recent labeled days --
    perf = live_performance(engine, champion.model_id,
                            label_end - timedelta(days=MONITOR_WINDOW_DAYS), as_of)
    r = MonitorResult("ok", champion.model_id, perf=perf)
    if perf["n_fraud"] >= MIN_FRAUD_TO_JUDGE:
        if perf["recall"] < MIN_RECALL:
            r.reasons.append(f"recall {perf['recall']:.2f} < {MIN_RECALL}")
        if perf["precision"] is not None and perf["precision"] < MIN_PRECISION:
            r.reasons.append(f"precision {perf['precision']:.2f} < {MIN_PRECISION}")

    # -- 2. Drift: recent feature distributions vs. the champion's training data --
    recent = load_features(engine, as_of - timedelta(days=1), as_of)
    if not recent.empty:
        report = drift_report(champion.profile, recent)
        r.drifted_feature = max(report, key=report.get)
        r.max_psi = report[r.drifted_feature]
        r.details["psi"] = report
        if r.max_psi > PSI_THRESHOLD:
            r.reasons.append(f"drift in {r.drifted_feature} (PSI {r.max_psi:.2f})")

    if not r.reasons:
        if perf["n_fraud"] < MIN_FRAUD_TO_JUDGE:
            r.action = "insufficient_data"
        _log(engine, as_of, r)
        return r

    # -- 3. Retrain a challenger and run a fair head-to-head --
    holdout_start = (label_end - timedelta(days=HOLDOUT_DAYS - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    train_start = holdout_start - timedelta(days=TRAIN_WINDOW_DAYS)
    challenger = train(engine, train_start, holdout_start)

    holdout = load_features(engine, holdout_start, label_end + timedelta(seconds=1), labeled_only=True)
    y = holdout["is_fraud"].to_numpy()
    champ_eval = evaluate(y, champion.score(holdout), champion.threshold)
    chall_eval = evaluate(y, challenger.score(holdout), challenger.threshold)
    r.details.update({"holdout_champion": champ_eval, "holdout_challenger": chall_eval})

    better = (chall_eval["pr_auc"] > champ_eval["pr_auc"]
              and chall_eval["cost"] <= champ_eval["cost"])
    reason = "; ".join(r.reasons)
    if better:
        # Refit on everything up to the newest label so the new champion also
        # learns from the holdout day.
        final = train(engine, train_start, label_end + timedelta(seconds=1))
        r.model_id = register(engine, final, "champion", f"promoted: {reason}")
        r.action = "promoted"
    else:
        register(engine, challenger, "rejected", f"not better than champion: {reason}")
        r.action = "rejected"
    _log(engine, as_of, r)
    return r
