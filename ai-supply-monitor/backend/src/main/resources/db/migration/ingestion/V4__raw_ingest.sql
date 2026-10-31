CREATE SCHEMA IF NOT EXISTS ingestion;

-- Every payload exactly as received, stored before parsing. Deutsche Börse only keeps files until midnight of
-- the next business day, so this table is our history.
CREATE TABLE ingestion.raw_ingest (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT        NOT NULL,
    object_name TEXT        NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    sha256      CHAR(64)    NOT NULL,
    size_bytes  INTEGER     NOT NULL,
    payload     BYTEA       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'ARCHIVED',   -- ARCHIVED, PARSED, FAILED
    parsed_at   TIMESTAMPTZ,
    bar_count   INTEGER,
    error       TEXT,
    UNIQUE (source, object_name)
);

-- Payloads are usually gzip already; skip TOAST's own compression attempt.
ALTER TABLE ingestion.raw_ingest ALTER COLUMN payload SET STORAGE EXTERNAL;
CREATE INDEX raw_ingest_status_idx ON ingestion.raw_ingest (status) WHERE status <> 'PARSED';
