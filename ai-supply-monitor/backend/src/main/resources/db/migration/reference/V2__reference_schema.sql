CREATE SCHEMA IF NOT EXISTS reference;

CREATE TABLE reference.company (
    id       TEXT PRIMARY KEY,           -- LEI where available, else an internal slug
    name     TEXT    NOT NULL,
    tier     TEXT    NOT NULL,
    country  CHAR(2) NOT NULL,
    tradable BOOLEAN NOT NULL            -- false for context nodes (end-of-day only, no live feed)
);

CREATE TABLE reference.listing (
    id         TEXT PRIMARY KEY,         -- ISIN@MIC
    company_id TEXT    NOT NULL REFERENCES reference.company (id),
    isin       CHAR(12) NOT NULL,
    mic        CHAR(4) NOT NULL,
    symbol     TEXT    NOT NULL,
    currency   CHAR(3) NOT NULL,
    source     TEXT    NOT NULL,
    UNIQUE (isin, mic),
    CHECK (id = isin || '@' || mic)
);
