"""Decision model - the win-probability model.

A logistic regression trained on ``deal_history`` (past deals and whether they
were won). It is small on purpose:

* **Explainable** - every prediction breaks down into per-feature contributions
  (in log-odds, relative to an average deal), so the app can say *why* a deal
  scores the way it does.
* **Deterministic** - same data, same weights, same decision. No LLM in the loop.
* **Fast** - trains in milliseconds with numpy at startup; retrain any time.

The model card (training size, holdout accuracy/AUC, learned weights) is exposed
so users can see how much to trust it.
"""
from __future__ import annotations

import threading
from datetime import datetime

import numpy as np

from .features import BY_NAME, FEATURE_NAMES

MODEL_VERSION = "deal-win-logreg-1"


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    """Probability a random won deal outscores a random lost one."""
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


class WinModel:
    def __init__(self, l2: float = 0.01, lr: float = 0.5, epochs: int = 3000):
        self.l2, self.lr, self.epochs = l2, lr, epochs
        self.mean = self.std = self.w = None
        self.b = 0.0
        self.card: dict = {}

    # -- training ------------------------------------------------------------------------
    def _fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.mean, self.std = X.mean(axis=0), X.std(axis=0) + 1e-9
        Z = (X - self.mean) / self.std
        self.w, self.b = np.zeros(Z.shape[1]), 0.0
        for _ in range(self.epochs):  # batch gradient descent on L2-regularised log-loss
            err = _sigmoid(Z @ self.w + self.b) - y
            self.w -= self.lr * (Z.T @ err / len(y) + self.l2 * self.w)
            self.b -= self.lr * err.mean()

    def train(self, history: list[dict], holdout: float = 0.25, seed: int = 7) -> dict:
        if len(history) < 50:
            raise ValueError(f"need at least 50 past deals to train, got {len(history)}")
        X = np.array([[h["features"][f] for f in FEATURE_NAMES] for h in history], dtype=float)
        y = np.array([1.0 if h["outcome"] == "Won" else 0.0 for h in history])
        idx = np.random.default_rng(seed).permutation(len(y))
        cut = int(len(y) * (1 - holdout))
        tr, te = idx[:cut], idx[cut:]

        self._fit(X[tr], y[tr])  # 1) fit on the training split and measure on the holdout
        p = self.predict_matrix(X[te])
        metrics = {"holdout_accuracy": round(float(((p >= 0.5) == y[te]).mean()), 3),
                   "holdout_auc": round(_auc(y[te], p), 3),
                   "baseline_accuracy": round(float(max(y[te].mean(), 1 - y[te].mean())), 3)}

        self._fit(X, y)  # 2) refit on everything for serving
        self.card = {
            "version": MODEL_VERSION,
            "type": "logistic regression (L2), standardized features",
            "trained_at": datetime.now().replace(microsecond=0).isoformat(),
            "training_deals": len(y),
            "historical_win_rate": round(float(y.mean()), 3),
            **metrics,
            "weights": {f: round(float(w), 3) for f, w in zip(FEATURE_NAMES, self.w, strict=True)},
        }
        return self.card

    # -- inference -----------------------------------------------------------------------
    def predict_matrix(self, X: np.ndarray) -> np.ndarray:
        return _sigmoid(((X - self.mean) / self.std) @ self.w + self.b)

    def predict(self, features: dict) -> float:
        x = np.array([[features[f] for f in FEATURE_NAMES]], dtype=float)
        return float(self.predict_matrix(x)[0])

    def explain(self, features: dict) -> list[dict]:
        """Per-feature contribution to the log-odds versus an average past deal, biggest first."""
        out = []
        for i, name in enumerate(FEATURE_NAMES):
            impact = float(self.w[i] * (features[name] - self.mean[i]) / self.std[i])
            out.append({"factor": BY_NAME[name].label, "feature": name, "value": BY_NAME[name].show(features[name]),
                        "impact": round(impact, 2), "direction": "helps" if impact > 0 else "hurts"})
        return sorted(out, key=lambda c: abs(c["impact"]), reverse=True)


_model: WinModel | None = None
_model_db = None
_lock = threading.Lock()


def get_model(db, retrain: bool = False) -> WinModel:
    """Train once per database handle (history is seeded on first use if missing)."""
    global _model, _model_db
    with _lock:
        if _model is None or _model_db is not db or retrain:
            if db.deal_history.count_documents({}) == 0:
                from ..seed import generate_deal_history

                db.deal_history.insert_many(generate_deal_history())
            model = WinModel()
            model.train(list(db.deal_history.find({}, {"features": 1, "outcome": 1})))
            _model, _model_db = model, db
        return _model
