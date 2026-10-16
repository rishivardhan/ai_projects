"""End-to-end simulation of a fraud model living in production.

Day by day: new transactions arrive -> the champion scores them -> labels
from older days come in -> monitoring decides whether to retrain/promote.
Halfway through, fraudsters switch tactics so you can watch the model fail
and then course-correct.
"""
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import datagen
from .datagen import day_bounds
from .db import init_schema
from .monitor import course_correct
from .predict import score_window


def _fmt(x, spec=".2f"):
    return "  -  " if x is None or (isinstance(x, float) and np.isnan(x)) else format(x, spec)


def run(engine: Engine, days: int = 42, warmup_days: int = 21, drift_day: int | None = 28,
        label_lag_days: int = 2, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    init_schema(engine, reset=True)
    datagen.seed_entities(engine, rng)

    print(f"Warm-up: generating {warmup_days} days of history...")
    for day in range(warmup_days):
        datagen.generate_day(engine, day, rng, datagen.fraud_patterns_for_day(day, drift_day))
    datagen.reveal_labels(engine, day_bounds(warmup_days - 1)[1])
    first = course_correct(engine, day_bounds(warmup_days - 1)[1])
    print(f"Initial champion: model {first.model_id} "
          f"({first.details['validation']['selected']})\n")

    header = f"{'day':>3} {'date':>10} {'txns':>5} {'fraud':>5}  {'model':>5} " \
             f"{'P(3d)':>5} {'R(3d)':>5} {'maxPSI':>6}  action"
    print(header)
    print("-" * len(header))
    for day in range(warmup_days, days):
        start, end = day_bounds(day)
        df = datagen.generate_day(engine, day, rng, datagen.fraud_patterns_for_day(day, drift_day))
        score_window(engine, start, end)                                 # real-time scoring
        datagen.reveal_labels(engine, day_bounds(day - label_lag_days)[1])  # chargebacks arrive
        r = course_correct(engine, end)                                  # nightly monitoring job
        note = f"{r.action}" + (f"  <- {'; '.join(r.reasons)}" if r.reasons else "")
        marker = " *drift starts*" if day == drift_day else ""
        print(f"{day:>3} {start:%Y-%m-%d} {len(df):>5} {int(df.is_fraud.sum()):>5}  "
              f"{r.model_id:>5} {_fmt(r.perf.get('precision')):>5} {_fmt(r.perf.get('recall')):>5} "
              f"{_fmt(r.max_psi):>6}  {note}{marker}")

    return hindsight(engine)


def hindsight(engine: Engine) -> pd.DataFrame:
    """Per-day truth: how well did whatever model was live that day actually do?"""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT date_trunc('day', t.txn_time)::date AS day, p.model_id,
                   g.fraud_pattern, g.is_fraud, p.predicted_fraud
            FROM fraud.predictions p
            JOIN fraud.sim_ground_truth g USING (transaction_id)
            JOIN fraud.transactions t USING (transaction_id)
        """), conn)

    def summarize(g):
        tp = (g.is_fraud & g.predicted_fraud).sum()
        flagged, fraud = g.predicted_fraud.sum(), g.is_fraud.sum()
        ct = g[g.fraud_pattern == "card_testing"]
        return pd.Series({
            "model": g.model_id.iloc[0], "fraud": fraud, "flagged": flagged,
            "precision": tp / flagged if flagged else np.nan,
            "recall": tp / fraud if fraud else np.nan,
            "card_testing_recall": ct.predicted_fraud.mean() if len(ct) else np.nan,
        })

    return df.groupby("day").apply(summarize, include_groups=False).round(2)
