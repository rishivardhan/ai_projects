-- Fraud detection schema. Everything the project needs lives in the `fraud` schema.
CREATE SCHEMA IF NOT EXISTS fraud;

-- ---------- Core business data ----------
CREATE TABLE IF NOT EXISTS fraud.customers (
    customer_id    INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    home_city      TEXT NOT NULL,
    home_lat       DOUBLE PRECISION NOT NULL,
    home_lon       DOUBLE PRECISION NOT NULL,
    typical_spend  NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS fraud.merchants (
    merchant_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    city         TEXT,                -- NULL for online merchants
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION,
    is_online    BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS fraud.transactions (
    transaction_id  BIGINT PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES fraud.customers,
    merchant_id     INTEGER NOT NULL REFERENCES fraud.merchants,
    amount          NUMERIC(12, 2) NOT NULL,
    txn_time        TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_time_idx ON fraud.transactions (txn_time);
CREATE INDEX IF NOT EXISTS transactions_customer_time_idx ON fraud.transactions (customer_id, txn_time);

-- Labels arrive LATE in real life (chargebacks, analyst reviews). The model
-- only ever learns from rows that have a label here.
CREATE TABLE IF NOT EXISTS fraud.fraud_labels (
    transaction_id  BIGINT PRIMARY KEY REFERENCES fraud.transactions,
    is_fraud        BOOLEAN NOT NULL,
    source          TEXT NOT NULL,     -- 'chargeback' | 'no_dispute'
    labeled_at      TIMESTAMP NOT NULL DEFAULT now()
);

-- Simulation only: what the data generator knows to be true. The
-- "reveal labels" step copies rows from here into fraud_labels after a delay.
CREATE TABLE IF NOT EXISTS fraud.sim_ground_truth (
    transaction_id  BIGINT PRIMARY KEY REFERENCES fraud.transactions,
    is_fraud        BOOLEAN NOT NULL,
    fraud_pattern   TEXT NOT NULL      -- 'none' | 'stolen_card' | 'card_testing'
);

-- ---------- ML operations ----------
CREATE TABLE IF NOT EXISTS fraud.model_registry (
    model_id         SERIAL PRIMARY KEY,
    algorithm        TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('champion', 'challenger', 'retired', 'rejected')),
    threshold        DOUBLE PRECISION NOT NULL,
    trained_from     TIMESTAMP,
    trained_to       TIMESTAMP,
    n_train          INTEGER,
    metrics          JSONB,            -- validation metrics of every candidate
    feature_profile  JSONB,            -- training distribution, used for drift (PSI)
    reason           TEXT,             -- why it was trained / promoted / rejected
    artifact         BYTEA NOT NULL,   -- joblib-serialised sklearn pipeline
    created_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fraud.predictions (
    transaction_id   BIGINT NOT NULL REFERENCES fraud.transactions,
    model_id         INTEGER NOT NULL REFERENCES fraud.model_registry,
    score            DOUBLE PRECISION NOT NULL,
    predicted_fraud  BOOLEAN NOT NULL,
    scored_at        TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, model_id)
);

CREATE TABLE IF NOT EXISTS fraud.monitoring_runs (
    run_id          SERIAL PRIMARY KEY,
    as_of           TIMESTAMP NOT NULL,
    model_id        INTEGER REFERENCES fraud.model_registry,
    n_labeled       INTEGER,
    n_fraud         INTEGER,
    precision       DOUBLE PRECISION,
    recall          DOUBLE PRECISION,
    max_psi         DOUBLE PRECISION,
    drifted_feature TEXT,
    action          TEXT NOT NULL,     -- 'ok' | 'promoted' | 'rejected' | 'initial' | 'insufficient_data'
    details         JSONB,
    run_at          TIMESTAMP NOT NULL DEFAULT now()
);
