"""Synthetic transaction generator.

Real fraud data is hard to get, so we simulate a bank: customers live in a
city, mostly shop locally, and occasionally get hit by fraudsters. Two fraud
patterns exist so we can simulate *concept drift*:

* stolen_card  - a few large purchases, often at night, far from home or at
                 online electronics / travel merchants.
* card_testing - a rapid burst of tiny online charges (is the card live?)
                 followed by a gift-card cash-out. Happens in the daytime and
                 uses small amounts, so a model that only knows "stolen_card"
                 tends to miss it.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

START = datetime(2026, 1, 1)

CITIES = {
    "New York": (40.71, -74.00),
    "Chicago": (41.88, -87.63),
    "Austin": (30.27, -97.74),
    "Seattle": (47.61, -122.33),
    "Miami": (25.76, -80.19),
}
# Spend multiplier relative to a customer's typical purchase.
CATEGORY_SPEND = {
    "grocery": 1.0, "restaurant": 0.8, "fuel": 0.9, "clothing": 1.5,
    "electronics": 3.0, "travel": 4.0, "online_retail": 1.2, "gift_cards": 1.0,
}
PHYSICAL_CATEGORIES = ["grocery", "restaurant", "fuel", "clothing", "electronics"]
PHYSICAL_WEIGHTS = [0.35, 0.3, 0.15, 0.12, 0.08]
ONLINE_CATEGORIES = ["online_retail", "electronics", "travel", "gift_cards"]
ONLINE_WEIGHTS = [0.5, 0.2, 0.15, 0.15]

# Legit shopping peaks in the day/evening; a little happens at night.
HOUR_WEIGHTS = np.array(
    [1, 0.5, 0.3, 0.2, 0.2, 0.5, 1.5, 3, 5, 6, 6, 7, 8, 7, 6, 6, 7, 8, 9, 8, 6, 4, 3, 2],
    dtype=float,
)
HOUR_WEIGHTS /= HOUR_WEIGHTS.sum()

# Fraud events per customer per day, by pattern.
BASE_FRAUD_RATE = 0.008


def day_bounds(day: int) -> tuple[datetime, datetime]:
    return START + timedelta(days=day), START + timedelta(days=day + 1)


def seed_entities(engine: Engine, rng: np.random.Generator,
                  n_customers: int = 1000, n_merchants: int = 300) -> None:
    city_names = list(CITIES)

    cities = rng.choice(city_names, size=n_customers)
    customers = pd.DataFrame({
        "customer_id": np.arange(1, n_customers + 1),
        "name": [f"Customer {i}" for i in range(1, n_customers + 1)],
        "home_city": cities,
        "home_lat": [CITIES[c][0] + rng.normal(0, 0.08) for c in cities],
        "home_lon": [CITIES[c][1] + rng.normal(0, 0.08) for c in cities],
        "typical_spend": np.round(rng.lognormal(np.log(45), 0.5, n_customers), 2),
    })

    n_online = int(n_merchants * 0.2)
    rows = []
    for i in range(1, n_merchants + 1):
        if i <= n_online:
            cat = rng.choice(ONLINE_CATEGORIES, p=ONLINE_WEIGHTS)
            rows.append((i, f"{cat} web shop {i}", cat, None, None, None, True))
        else:
            cat = rng.choice(PHYSICAL_CATEGORIES, p=PHYSICAL_WEIGHTS)
            city = rng.choice(city_names)
            lat, lon = CITIES[city]
            rows.append((i, f"{city} {cat} {i}", cat, city,
                         lat + rng.normal(0, 0.08), lon + rng.normal(0, 0.08), False))
    merchants = pd.DataFrame(rows, columns=["merchant_id", "name", "category", "city",
                                            "lat", "lon", "is_online"])

    with engine.begin() as conn:
        customers.to_sql("customers", conn, schema="fraud", if_exists="append", index=False)
        merchants.to_sql("merchants", conn, schema="fraud", if_exists="append", index=False)


def fraud_patterns_for_day(day: int, drift_day: int | None) -> dict[str, float]:
    """Relative intensity of each fraud pattern. After drift_day, fraudsters switch tactics."""
    if drift_day is None or day < drift_day:
        return {"stolen_card": 1.0}
    return {"stolen_card": 0.3, "card_testing": 1.0}


def generate_day(engine: Engine, day: int, rng: np.random.Generator,
                 patterns: dict[str, float]) -> pd.DataFrame:
    """Generate one day of transactions (legit + fraud) and store them."""
    with engine.connect() as conn:
        customers = pd.read_sql(text("SELECT * FROM fraud.customers"), conn)
        merchants = pd.read_sql(text("SELECT * FROM fraud.merchants"), conn)
        next_id = conn.execute(
            text("SELECT COALESCE(MAX(transaction_id), 0) + 1 FROM fraud.transactions")
        ).scalar_one()
    customers["typical_spend"] = customers["typical_spend"].astype(float)

    day_start, _ = day_bounds(day)
    local = {c: g["merchant_id"].to_numpy()
             for c, g in merchants[~merchants.is_online].groupby("city")}
    online = merchants[merchants.is_online]
    category = merchants.set_index("merchant_id")["category"]

    def online_ids(categories):
        return online[online.category.isin(categories)]["merchant_id"].to_numpy()

    rows = []  # (customer_id, merchant_id, amount, txn_time, is_fraud, pattern)

    # ---- Legit traffic ----
    for cust in customers.itertuples():
        for _ in range(rng.poisson(2.0)):
            r = rng.random()
            if r < 0.80:
                m = rng.choice(local[cust.home_city])
            elif r < 0.97:
                m = rng.choice(online["merchant_id"].to_numpy())
            else:  # legit travel: shopping in another city
                other = rng.choice([c for c in CITIES if c != cust.home_city])
                m = rng.choice(local[other])
            amount = cust.typical_spend * CATEGORY_SPEND[category[m]] * rng.lognormal(0, 0.6)
            t = day_start + timedelta(hours=int(rng.choice(24, p=HOUR_WEIGHTS)),
                                      seconds=int(rng.integers(0, 3600)))
            rows.append((cust.customer_id, m, amount, t, False, "none"))

    # ---- Fraud ----
    n_customers = len(customers)
    for pattern, intensity in patterns.items():
        for _ in range(rng.poisson(BASE_FRAUD_RATE * intensity * n_customers)):
            victim = customers.iloc[rng.integers(n_customers)]
            if pattern == "stolen_card":
                hour = int(rng.integers(0, 6)) if rng.random() < 0.7 else int(rng.choice(24, p=HOUR_WEIGHTS))
                t = day_start + timedelta(hours=hour, seconds=int(rng.integers(0, 3600)))
                for _ in range(rng.integers(1, 4)):
                    if rng.random() < 0.5:
                        far = rng.choice([c for c in CITIES if c != victim.home_city])
                        m = rng.choice(local[far])
                    else:
                        m = rng.choice(online_ids(["electronics", "travel"]))
                    amount = victim.typical_spend * rng.uniform(4, 12)
                    rows.append((victim.customer_id, m, amount, t, True, pattern))
                    t += timedelta(minutes=int(rng.integers(5, 90)))
            elif pattern == "card_testing":
                t = day_start + timedelta(hours=int(rng.choice(24, p=HOUR_WEIGHTS)),
                                          seconds=int(rng.integers(0, 3600)))
                for _ in range(rng.integers(4, 9)):
                    m = rng.choice(online_ids(["gift_cards", "online_retail"]))
                    rows.append((victim.customer_id, m, rng.uniform(0.5, 5), t, True, pattern))
                    t += timedelta(seconds=int(rng.integers(20, 120)))
                m = rng.choice(online_ids(["gift_cards"]))
                rows.append((victim.customer_id, m, rng.uniform(150, 500), t, True, pattern))

    df = pd.DataFrame(rows, columns=["customer_id", "merchant_id", "amount", "txn_time",
                                     "is_fraud", "fraud_pattern"])
    df = df.sort_values("txn_time", kind="stable").reset_index(drop=True)
    df["amount"] = df["amount"].clip(lower=0.5).round(2)
    df["transaction_id"] = np.arange(next_id, next_id + len(df))

    with engine.begin() as conn:
        df[["transaction_id", "customer_id", "merchant_id", "amount", "txn_time"]].to_sql(
            "transactions", conn, schema="fraud", if_exists="append", index=False,
            method="multi", chunksize=2000)
        df[["transaction_id", "is_fraud", "fraud_pattern"]].to_sql(
            "sim_ground_truth", conn, schema="fraud", if_exists="append", index=False,
            method="multi", chunksize=2000)
    return df


def reveal_labels(engine: Engine, through: datetime) -> int:
    """Simulate chargebacks: label every transaction that happened before `through`."""
    with engine.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO fraud.fraud_labels (transaction_id, is_fraud, source)
            SELECT g.transaction_id, g.is_fraud,
                   CASE WHEN g.is_fraud THEN 'chargeback' ELSE 'no_dispute' END
            FROM fraud.sim_ground_truth g
            JOIN fraud.transactions t USING (transaction_id)
            WHERE t.txn_time < :through
            ON CONFLICT (transaction_id) DO NOTHING
        """), {"through": through})
        return result.rowcount


def next_day_index(engine: Engine) -> int:
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT MAX(txn_time) FROM fraud.transactions")).scalar()
    return 0 if latest is None else (latest - START).days + 1


def has_entities(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM fraud.customers")).scalar_one() > 0
