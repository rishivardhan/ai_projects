from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from fraud.features import compute_features
from fraud.model import pick_threshold
from fraud.monitor import psi


def _raw(rows):
    return pd.DataFrame(rows, columns=["transaction_id", "customer_id", "merchant_id", "amount",
                                       "txn_time", "category", "is_online", "m_lat", "m_lon",
                                       "home_lat", "home_lon"])


def test_velocity_and_history_features():
    t0 = datetime(2026, 1, 1, 12)
    rows = [
        (1, 1, 10, 50.0, t0, "grocery", False, 40.7, -74.0, 40.7, -74.0),
        (2, 1, 10, 50.0, t0 + timedelta(hours=2), "grocery", False, 40.7, -74.0, 40.7, -74.0),
        # Burst of online purchases at new merchants, 1 minute apart
        (3, 1, 20, 2.0, t0 + timedelta(hours=3), "gift_cards", True, None, None, 40.7, -74.0),
        (4, 1, 21, 3.0, t0 + timedelta(hours=3, minutes=1), "gift_cards", True, None, None, 40.7, -74.0),
        # Another customer, far from home
        (5, 2, 30, 900.0, t0, "electronics", False, 25.76, -80.19, 47.6, -122.3),
    ]
    f = compute_features(_raw(rows)).set_index("transaction_id")

    assert f.loc[1, "txn_count_1h"] == 0
    assert f.loc[4, "txn_count_1h"] == 1          # one purchase earlier in the hour
    assert f.loc[4, "txn_count_24h"] == 3
    assert f.loc[2, "amount_ratio"] == 1.0        # same as previous average
    assert f.loc[2, "is_new_merchant"] == 0
    assert f.loc[3, "is_new_merchant"] == 1
    assert f.loc[3, "distance_km"] == 0           # online
    assert f.loc[5, "distance_km"] > 3000         # Seattle -> Miami
    assert f.loc[4, "mins_since_last"] == 1


def test_psi_detects_shift():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 5000)
    edges = np.quantile(base, np.linspace(0, 1, 11)[1:-1])
    props = np.bincount(np.searchsorted(edges, base), minlength=10) / len(base)
    assert psi(props, edges, rng.normal(0, 1, 5000)) < 0.05
    assert psi(props, edges, rng.normal(1.5, 1, 5000)) > 0.25


def test_threshold_prefers_catching_fraud():
    y = np.array([0] * 90 + [1] * 10)
    scores = np.concatenate([np.linspace(0, 0.4, 90), np.linspace(0.3, 0.9, 10)])
    t = pick_threshold(y, scores)
    assert ((scores >= t) & (y == 1)).sum() >= 8
