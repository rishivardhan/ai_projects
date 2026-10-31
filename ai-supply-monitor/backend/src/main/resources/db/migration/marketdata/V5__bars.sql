CREATE SCHEMA IF NOT EXISTS marketdata;

CREATE TABLE marketdata.bar (
    listing_id     TEXT           NOT NULL,   -- ISIN@MIC; owned by reference, deliberately no cross-schema FK
    bar_start      TIMESTAMPTZ    NOT NULL,
    open           NUMERIC(18, 6) NOT NULL,
    high           NUMERIC(18, 6) NOT NULL,
    low            NUMERIC(18, 6) NOT NULL,
    close          NUMERIC(18, 6) NOT NULL,
    volume         NUMERIC(20, 4) NOT NULL,
    trade_count    INTEGER        NOT NULL,
    first_trade_at TIMESTAMPTZ    NOT NULL,
    last_trade_at  TIMESTAMPTZ    NOT NULL,
    source         TEXT           NOT NULL,
    delay_class    TEXT           NOT NULL,
    received_at    TIMESTAMPTZ    NOT NULL,
    PRIMARY KEY (listing_id, bar_start)
);

SELECT create_hypertable('marketdata.bar', by_range('bar_start', INTERVAL '1 day'));

ALTER TABLE marketdata.bar SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'listing_id',
    timescaledb.compress_orderby = 'bar_start'
);
SELECT add_compression_policy('marketdata.bar', INTERVAL '7 days');

-- Batches (one per raw source object) already applied, so redelivered events are no-ops.
CREATE TABLE marketdata.applied_batch (
    batch_id   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
