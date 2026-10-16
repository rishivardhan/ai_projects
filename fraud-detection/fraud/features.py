"""Feature engineering: turn raw transactions into model inputs.

A single transaction says little on its own. Fraud shows up in *context*:
how this purchase compares to the customer's history, how far from home it
is, and how many purchases happened in the last hour.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

NUMERIC_FEATURES = [
    "log_amount",        # size of the purchase
    "amount_ratio",      # vs. this customer's recent average
    "hour",
    "is_night",
    "is_online",
    "distance_km",       # merchant distance from customer's home (0 if online)
    "txn_count_1h",      # velocity: how many purchases in the previous hour
    "txn_count_24h",
    "amount_sum_24h",
    "mins_since_last",
    "is_new_merchant",   # customer hasn't bought here in the last HISTORY_DAYS
]
CATEGORICAL_FEATURES = ["category"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# History-based features look back this far. Rows within HISTORY_DAYS of the
# very first transaction have incomplete history and must not be trained on.
HISTORY_DAYS = 7


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def compute_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Pure-pandas feature computation. `raw` must include enough history for velocity features."""
    df = raw.sort_values(["customer_id", "txn_time", "transaction_id"]).reset_index(drop=True)
    df["txn_time"] = pd.to_datetime(df["txn_time"])

    # Time-window aggregates per customer. Rolling windows include the current
    # row, so subtract it to get "what happened *before* this purchase".
    rolling = df.set_index("txn_time").groupby("customer_id", sort=True)["amount"]
    count_1h = rolling.rolling("1h").count().to_numpy()
    count_24h = rolling.rolling("24h").count().to_numpy()
    sum_24h = rolling.rolling("24h").sum().to_numpy()
    count_hist = rolling.rolling(f"{HISTORY_DAYS}D").count().to_numpy()
    sum_hist = rolling.rolling(f"{HISTORY_DAYS}D").sum().to_numpy()

    df["txn_count_1h"] = count_1h - 1
    df["txn_count_24h"] = count_24h - 1
    df["amount_sum_24h"] = sum_24h - df["amount"]
    prior_n = count_hist - 1
    prior_avg = np.where(prior_n > 0, (sum_hist - df["amount"]) / np.maximum(prior_n, 1), np.nan)
    prior_avg = pd.Series(prior_avg).fillna(df["amount"].median())
    df["amount_ratio"] = df["amount"] / prior_avg.clip(lower=1.0)

    gap = df.groupby("customer_id")["txn_time"].diff().dt.total_seconds() / 60
    df["mins_since_last"] = gap.fillna(7 * 24 * 60).clip(upper=7 * 24 * 60)
    pair = df.set_index("txn_time").groupby(["customer_id", "merchant_id"], sort=True)["amount"]
    seen = pair.rolling(f"{HISTORY_DAYS}D").count().rename("seen").reset_index()
    seen["transaction_id"] = df.sort_values(["customer_id", "merchant_id", "txn_time",
                                             "transaction_id"])["transaction_id"].to_numpy()
    df = df.merge(seen[["transaction_id", "seen"]], on="transaction_id")
    df["is_new_merchant"] = (df.pop("seen") <= 1).astype(int)

    df["log_amount"] = np.log1p(df["amount"])
    df["hour"] = df["txn_time"].dt.hour
    df["is_night"] = (df["hour"] < 6).astype(int)
    df["is_online"] = df["is_online"].astype(int)
    dist = haversine_km(df["home_lat"], df["home_lon"], df["m_lat"], df["m_lon"])
    df["distance_km"] = np.where(df["is_online"] == 1, 0.0, dist)
    return df


def history_complete_from(engine: Engine) -> datetime | None:
    """Earliest time at which history-based features are trustworthy."""
    with engine.connect() as conn:
        first = conn.execute(text("SELECT MIN(txn_time) FROM fraud.transactions")).scalar()
    return None if first is None else first + timedelta(days=HISTORY_DAYS)


def load_features(engine: Engine, start: datetime, end: datetime,
                  labeled_only: bool = False) -> pd.DataFrame:
    """Features for transactions in [start, end). Loads extra history for context.

    With labeled_only=True, only transactions with a label are returned, plus
    `is_fraud` and `was_flagged` (did a deployed model flag it at the time?).
    """
    sql = text("""
        SELECT t.transaction_id, t.customer_id, t.merchant_id, t.amount::float AS amount,
               t.txn_time, m.category, m.is_online, m.lat AS m_lat, m.lon AS m_lon,
               c.home_lat, c.home_lon
        FROM fraud.transactions t
        JOIN fraud.merchants m USING (merchant_id)
        JOIN fraud.customers c USING (customer_id)
        WHERE t.txn_time >= :hist_start AND t.txn_time < :end
    """)
    with engine.connect() as conn:
        raw = pd.read_sql(sql, conn, params={
            "hist_start": start - timedelta(days=HISTORY_DAYS), "end": end})
    if raw.empty:
        return raw
    df = compute_features(raw)
    df = df[df["txn_time"] >= start]

    if labeled_only:
        with engine.connect() as conn:
            labels = pd.read_sql(text("""
                SELECT l.transaction_id, l.is_fraud, p.flagged AS was_flagged
                FROM fraud.fraud_labels l
                JOIN fraud.transactions t USING (transaction_id)
                LEFT JOIN (SELECT transaction_id, bool_or(predicted_fraud) AS flagged
                           FROM fraud.predictions GROUP BY transaction_id) p USING (transaction_id)
                WHERE t.txn_time >= :start AND t.txn_time < :end
            """), conn, params={"start": start, "end": end})
        df = df.merge(labels, on="transaction_id", how="inner")
        df["is_fraud"] = df["is_fraud"].astype(int)
    return df.sort_values("txn_time").reset_index(drop=True)
