"""Score transactions with the current champion model."""
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .features import load_features
from .model import load_champion


def score_window(engine: Engine, start: datetime, end: datetime) -> pd.DataFrame:
    """Score transactions in [start, end) that the champion hasn't scored yet."""
    champion = load_champion(engine)
    if champion is None:
        raise RuntimeError("No champion model yet - run `python cli.py train` first")

    df = load_features(engine, start, end)
    if df.empty:
        return df
    with engine.connect() as conn:
        done = pd.read_sql(text("SELECT transaction_id FROM fraud.predictions WHERE model_id = :m"),
                           conn, params={"m": champion.model_id})
    df = df[~df["transaction_id"].isin(done["transaction_id"])]
    if df.empty:
        return df

    df = df.assign(score=champion.score(df))
    df["predicted_fraud"] = df["score"] >= champion.threshold
    out = df[["transaction_id", "score", "predicted_fraud"]].assign(model_id=champion.model_id)
    with engine.begin() as conn:
        out.to_sql("predictions", conn, schema="fraud", if_exists="append", index=False,
                   method="multi", chunksize=2000)
    return df
