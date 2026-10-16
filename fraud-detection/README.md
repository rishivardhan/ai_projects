# Fraud Detection with scikit-learn + PostgreSQL

A hands-on project for learning how a fraud model is **built, deployed, and kept
healthy**. Everything uses free, open-source tools: scikit-learn models,
PostgreSQL, and synthetic data that you can regenerate whenever you like.

The project goes past "train a model once". It simulates a bank where:

1. Transactions stream in every day and are scored by the live (**champion**) model.
2. The truth arrives **late** (chargebacks show up about 2 days after the purchase).
3. Fraudsters **change tactics** partway through, and the model starts failing.
4. A monitoring job notices, trains a **challenger**, compares the two fairly,
   and promotes the challenger only if it is actually better. In other words, it **course-corrects**.

## Quick start

```bash
cd fraud-detection
docker compose up -d                 # Postgres 16 on localhost:5432 (postgres/postgres)
pip install -r requirements.txt
python cli.py simulate               # the whole story in about 90 seconds
```

To use a different database, set `DATABASE_URL`, e.g.
`postgresql+psycopg://user:pass@host:5432/dbname`.

## What you'll see

```
day       date  txns fraud  model P(3d) R(3d) maxPSI  action
------------------------------------------------------------
 26 2026-01-27  1975    16      1  0.43  0.97   0.01  ok
 27 2026-01-28  2001    19      1  0.36  1.00   0.01  ok
 28 2026-01-29  2022    41      1  0.38  0.91   0.02  ok *drift starts*
 29 2026-01-30  2065    38      1  0.56  0.88   0.01  ok
 30 2026-01-31  2050    72      2  0.58  0.41   0.04  promoted  <- recall 0.41 < 0.7
 31 2026-02-01  1965    50      2   -     -     0.02  insufficient_data
 33 2026-02-03  2050    52      2  0.96  0.98   0.02  ok
 ...

Hindsight (ground truth per day, for the model that was live that day):
            model  fraud  flagged  precision  recall  card_testing_recall
2026-01-28      1     19       25       0.64    0.84                  NaN
2026-01-29      1     41        7       0.14    0.02                 0.00   <- new fraud pattern, model blind
2026-01-30      1     38       20       0.25    0.13                 0.00
2026-01-31      1     72        9       0.11    0.01                 0.00
2026-02-01      2     50       51       0.96    0.98                 1.00   <- retrained model catches it
2026-02-02      2     79       81       0.98    1.00                 1.00
```

The monitor sees the failure **two days late**, because that's how long labels
take to arrive. That delay is realistic, and it is why monitoring speed matters.

## Project layout

| Path | What it teaches |
|---|---|
| `sql/schema.sql` | How to model the data: transactions, delayed labels, a model registry, predictions, and a monitoring log |
| `fraud/datagen.py` | Synthetic customers, merchants, and two fraud patterns (`stolen_card`, `card_testing`) |
| `fraud/features.py` | **Feature engineering**, which matters most: velocity, amount vs. history, distance from home, new merchant |
| `fraud/model.py` | Pipelines, imbalanced data, time-based validation, model selection, cost-based thresholds, the model registry |
| `fraud/predict.py` | Scoring new transactions with the champion |
| `fraud/monitor.py` | **Course correction**: live precision/recall, drift (PSI), champion vs. challenger, promotion |
| `fraud/simulate.py` | Ties it all together day by day |
| `cli.py` | Run each step by hand |

## Step by step (to understand each piece)

```bash
python cli.py init-db --reset
python cli.py generate --days 21          # 3 weeks of normal traffic
python cli.py reveal-labels --lag-days 2  # chargebacks for all but the last 2 days
python cli.py train                       # compares 3 models, promotes the best
python cli.py generate --days 4 --drift   # fraudsters switch to card testing
python cli.py predict                     # champion scores the new transactions
python cli.py reveal-labels               # the truth comes in...
python cli.py monitor                     # ...recall collapsed -> retrain -> promote
python cli.py status                      # registry + monitoring history
```

Then look inside Postgres:

```sql
SELECT * FROM fraud.model_registry ORDER BY model_id;          -- every model, and why it exists
SELECT * FROM fraud.monitoring_runs ORDER BY run_id;           -- every health check
-- frauds the model missed (false negatives)
SELECT t.*, p.score FROM fraud.predictions p
JOIN fraud.fraud_labels l USING (transaction_id)
JOIN fraud.transactions t USING (transaction_id)
WHERE l.is_fraud AND NOT p.predicted_fraud;
```

## Key ideas, and where they are in the code

**1. Fraud is rare (about 1-3% of rows), so accuracy is useless.** A model that
says "never fraud" is 98% accurate. We use **precision** (of the transactions we
flagged, how many were fraud?), **recall** (of all fraud, how much did we
catch?), and **PR-AUC** to compare models. We also use `class_weight="balanced"`
so the models pay attention to the rare class. → `model.py`

**2. Validate on the future, not on a random sample.** `train()` splits by time:
it trains on older data and validates on the newest 25%. A random split would
leak future information and give scores that are too optimistic.

**3. The threshold is a business decision.** `predict_proba` returns a score,
and you still have to choose where to cut. `pick_threshold()` picks the cut
that minimizes `5 × missed_frauds + 1 × false_alarms`. Change `COST_MISSED_FRAUD`
to see the precision/recall trade-off move.

**4. Features beat algorithms.** The raw columns are just customer, merchant,
amount, and time. Context is what makes fraud visible: 6 purchases in 5 minutes,
an amount 10× the usual, a merchant 3000 km from home. Try removing
the velocity features (`txn_count_1h`, `mins_since_last`) from `NUMERIC_FEATURES`
and rerun the simulation. How well does it catch card testing now?

**5. Models decay. Watch them and correct them.** `monitor.course_correct()` does three things:
- **Live performance**: it joins past predictions with labels that have since arrived.
  Below `MIN_RECALL` or `MIN_PRECISION` means the model is failing.
- **Drift (PSI)**: it compares recent feature distributions with the training data. This
  needs no labels, so it can warn early. *Notice that in this simulation, PSI
  barely moves when fraud tactics change.* Fraud is a tiny share of traffic, so the
  overall distribution hardly shifts. Drift checks catch broad data changes. They
  do not catch a small adversary changing tactics. Only labels catch that.
- **Champion vs. challenger**: it trains on a sliding 14-day window, so old patterns
  fade out. It up-weights recent rows and **the frauds the champion missed**
  (`MISSED_FRAUD_WEIGHT`). Both models are scored on the newest labeled day, which the
  challenger has never seen. The challenger is promoted only if it wins on PR-AUC
  *and* on cost. Rejected challengers stay in the registry with the reason.

**6. Cold-start artifacts.** History features (such as "new merchant") are wrong for
the first few days of data, because every merchant looks new. Training skips the
first `HISTORY_DAYS`. An earlier version of this project didn't skip them. It raised
false drift alarms and promoted a worse model, which is a good lesson in itself.

## Experiments to try

- `python cli.py simulate --label-lag-days 5`: slower labels mean a longer blind spot.
- Set `MISSED_FRAUD_WEIGHT = 1` or `RECENCY_HALF_LIFE_DAYS = 1000` in `model.py`. Does recovery get slower?
- Add a candidate model (e.g. `ExtraTreesClassifier`, or `IsolationForest` for unsupervised anomaly scores) to `candidate_models()`.
- Add a new fraud pattern in `datagen.py` (e.g. account takeover: new device, then a large transfer).
- Plug in a real public dataset, such as the Kaggle "Credit Card Fraud Detection" (ULB) data, by loading it into `fraud.transactions`.

## Tests

```bash
python -m pytest -q tests
```
