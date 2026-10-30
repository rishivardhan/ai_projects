# AI Supply-Chain Market Monitor

A near-real-time monitor that maps the AI supply chain (frontier labs → hyperscalers → chip designers → foundry and
memory → equipment) as a weighted graph. It flags when a shock at one node hasn't yet shown up in the names linked to
it. It runs on free data and a local Ollama. The full design is in [docs/design-doc-v0.1.md](docs/design-doc-v0.1.md).

**Status: M0, the walking skeleton.** Exit gate: 10 Xetra names stored and charted for a full day.

## Layout

```
ai-supply-monitor/
  backend/    Kotlin, Spring Boot 3.5, Spring Modulith; Gradle Kotlin DSL with a version catalog
  frontend/   React + Vite + TypeScript (strict)
  deploy/     docker-compose (app + Postgres/Timescale)
  docs/       design doc
```

Backend modules (`dev.rishi.aimonitor.*`). Other modules may only use a module's `api` subpackage, and
`ModularityTests` fails the build if any module breaks that rule:

| Module       | M0 state                                                                                     |
|--------------|----------------------------------------------------------------------------------------------|
| `reference`  | Companies and listings (`ISIN@MIC`), seeded with 10 Xetra names                               |
| `ingestion`  | Deutsche Börse post-trade adapter, raw archive, per-MIC session calendar, local-file importer |
| `marketdata` | 1-minute bars in a Timescale hypertable, idempotent batch upserts                             |
| `api`        | `GET /api/listings`, `GET /api/listings/{id}/bars?date=YYYY-MM-DD`, OpenAPI at `/v3/api-docs` |
| `events`, `graph`, `llm`, `signals` | Empty placeholders so the boundaries exist from day one                |

M0 data flow:

```
DETR-posttrade-*.json.gz ──► ingestion.raw_ingest (stored as received, before parsing)
        │ parse, drop cancels/untracked ISINs, fold to 1-min OHLCV
        ▼
PriceBarsIngested ──(Modulith publication registry)──► marketdata.bar ──► PriceBarsStored
                                                              │
                                                     REST ◄───┘──► chart
```

## Running it

```bash
cd deploy
cp .env.example .env            # set DB_PASSWORD; DEUTSCHE_BOERSE_ENABLED=true to poll live
mkdir -p import                 # optional: drop DETR-posttrade-*.json.gz files here to import on startup
docker compose up --build
open http://localhost:8080
```

For development, run Postgres from the compose file, then run `./gradlew bootRun` in `backend/` and `npm run dev` in
`frontend/`. Vite proxies `/api` to port 8080.

When `DEUTSCHE_BOERSE_ENABLED=true`, the poller lists the file service once a minute while Xetra is in session (plus
30 minutes after the close) and archives and parses every file it hasn't seen yet. Deutsche Börse keeps files only
until midnight of the next business day, so `ingestion.raw_ingest` is our history.

## Checks

```bash
cd backend && ./gradlew check   # Modulith verify, unit tests, Testcontainers IT (needs Docker), detekt, ktlint
cd frontend && npm run build    # tsc strict + vite build
```

CI runs both on every change under `ai-supply-monitor/` (`.github/workflows/ai-supply-monitor.yml`).

## Known gaps and next steps

- **Post-trade field mapping is unverified against a real file.** `PostTradeParser` follows the published layout
  (`isin`, `lastTrade`, `lastQty`, `tradingDateTime`, `tickActionIndicator`, `transIdCode`), but the only test fixture
  so far is synthetic. Next step: download one real `DETR-posttrade-*.json.gz`, add it under
  `backend/src/test/resources/fixtures/deutsche-boerse/` and point a contract test at it. The listing endpoint
  (`/api/DETR-posttrade`) and download path (`/api/download/{file}`) also need confirming against the live service.
- Cancellations are only matched within the same file. A cancel that arrives in a later file doesn't yet correct the
  bar it affects.
- The session calendar knows weekends but not exchange holidays.
- Frontend types are written by hand. Generating them with `openapi-typescript` from `/v3/api-docs` comes in M1.
- Module schema ownership is a convention for now (one schema per module, no cross-schema FKs). Per-module DB roles
  could enforce it later.
- Feed heartbeats, the grey-node staleness state and metrics are M4.
