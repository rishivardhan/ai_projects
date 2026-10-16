"""Command line entry point.

    python cli.py simulate                 # the whole story in one command
    python cli.py init-db [--reset]
    python cli.py generate --days 14 [--drift]
    python cli.py reveal-labels [--lag-days 2]
    python cli.py train
    python cli.py predict
    python cli.py monitor
    python cli.py status
"""
import argparse
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from fraud import datagen
from fraud.db import get_engine, init_schema
from fraud.model import register, train
from fraud.monitor import course_correct
from fraud.predict import score_window
from fraud.simulate import run


def _latest_txn_time(engine):
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT MAX(txn_time) FROM fraud.transactions")).scalar()
    if latest is None:
        raise SystemExit("No transactions yet - run `python cli.py generate` first")
    return latest


def main() -> None:
    parser = argparse.ArgumentParser(description="Fraud detection with scikit-learn + Postgres")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-db", help="create the fraud schema")
    p.add_argument("--reset", action="store_true", help="drop all existing data first")

    p = sub.add_parser("generate", help="append N days of synthetic transactions")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--drift", action="store_true", help="fraudsters switch to card testing")
    p.add_argument("--seed", type=int, default=None)

    p = sub.add_parser("reveal-labels", help="simulate chargebacks arriving")
    p.add_argument("--lag-days", type=int, default=0,
                   help="only label transactions older than this many days")

    sub.add_parser("train", help="train on all labeled data and promote to champion")
    sub.add_parser("predict", help="score all transactions the champion hasn't scored")
    sub.add_parser("monitor", help="check the champion; retrain/promote if it is failing")
    sub.add_parser("status", help="show registry and recent monitoring runs")

    p = sub.add_parser("simulate", help="full day-by-day simulation with drift")
    p.add_argument("--days", type=int, default=42)
    p.add_argument("--drift-day", type=int, default=28)
    p.add_argument("--label-lag-days", type=int, default=2)
    p.add_argument("--seed", type=int, default=7)

    args = parser.parse_args()
    engine = get_engine()
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    if args.cmd == "init-db":
        init_schema(engine, reset=args.reset)
        print("Schema ready.")

    elif args.cmd == "generate":
        rng = np.random.default_rng(args.seed)
        init_schema(engine)
        if not datagen.has_entities(engine):
            datagen.seed_entities(engine, rng)
        first = datagen.next_day_index(engine)
        for day in range(first, first + args.days):
            patterns = datagen.fraud_patterns_for_day(day, drift_day=first if args.drift else None)
            df = datagen.generate_day(engine, day, rng, patterns)
            print(f"day {day}: {len(df)} transactions, {int(df.is_fraud.sum())} fraudulent")

    elif args.cmd == "reveal-labels":
        through = _latest_txn_time(engine) + timedelta(seconds=1) - timedelta(days=args.lag_days)
        print(f"Labeled {datagen.reveal_labels(engine, through)} transactions before {through}")

    elif args.cmd == "train":
        model = train(engine, datagen.START, _latest_txn_time(engine) + timedelta(seconds=1))
        model_id = register(engine, model, "champion", "manual train")
        print(pd.DataFrame(model.metrics["candidates"]).T.round(3))
        print(f"\nPromoted model {model_id} ({model.algorithm}, threshold {model.threshold:.3f})")

    elif args.cmd == "predict":
        latest = _latest_txn_time(engine)
        df = score_window(engine, datagen.START, latest + timedelta(seconds=1))
        print(f"Scored {len(df)} transactions, flagged {int(df.get('predicted_fraud', pd.Series()).sum())}")
        if len(df):
            cols = ["transaction_id", "txn_time", "customer_id", "category", "amount", "score"]
            print(df[df.predicted_fraud].sort_values("score", ascending=False)[cols].head(15))

    elif args.cmd == "monitor":
        r = course_correct(engine, _latest_txn_time(engine) + timedelta(seconds=1))
        print(f"action: {r.action}  model: {r.model_id}  perf: {r.perf}")
        print(f"max PSI: {r.max_psi} ({r.drifted_feature})")
        for reason in r.reasons:
            print(f"  reason: {reason}")
        if "holdout_champion" in r.details:
            print(pd.DataFrame({"champion": r.details["holdout_champion"],
                                "challenger": r.details["holdout_challenger"]}).round(3))

    elif args.cmd == "status":
        with engine.connect() as conn:
            print(pd.read_sql(text("""
                SELECT model_id, algorithm, status, round(threshold::numeric, 3) AS threshold,
                       trained_from::date, trained_to::date, n_train, reason
                FROM fraud.model_registry ORDER BY model_id"""), conn).to_string(index=False))
            print()
            print(pd.read_sql(text("""
                SELECT as_of, model_id, n_fraud, round(precision::numeric, 2) AS precision,
                       round(recall::numeric, 2) AS recall, round(max_psi::numeric, 2) AS max_psi,
                       drifted_feature, action
                FROM fraud.monitoring_runs ORDER BY run_id DESC LIMIT 15"""), conn).to_string(index=False))

    elif args.cmd == "simulate":
        result = run(engine, days=args.days, drift_day=args.drift_day,
                     label_lag_days=args.label_lag_days, seed=args.seed)
        print("\nHindsight (ground truth per day, for the model that was live that day):")
        print(result.to_string())


if __name__ == "__main__":
    main()
