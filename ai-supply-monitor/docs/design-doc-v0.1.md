# AI Supply-Chain Market Monitor --- Design Doc v0.1

Oct 30, 2026 · \@Rishi

## Context and goals

We are building a near-real-time monitor that maps the AI supply chain
(frontier labs → hyperscalers → chip designers → foundry and memory →
equipment) as a weighted graph. It flags when a shock at one node has
not yet shown up in its linked names. Coverage is Germany, wider Europe
and the US. It runs on free data and a resource-constrained local
Ollama.

**Goals**

-   G1: Show live (≤ 15 min delayed) price state for \~40 linked
    listings across XETRA, Euronext/other EU venues and US exchanges,
    overlaid on the dependency graph.

-   G2: Turn events (earnings, guidance, ad-hoc disclosures, filings,
    news) into graph-tagged signals within 5 minutes of publication.

-   G3: Compute an exposure-weighted "expected vs actual" move for every
    linked node and alert on divergence.

-   G4: Keep every edge auditable: each relationship cites its source
    document and date.

**Non-goals (v1)**

-   No order execution or broker integration.

-   No tick-level or sub-second latency; 1-minute bars and
    15-minute-delayed EU data are acceptable.

-   No price prediction claims; the system surfaces context and
    divergence, not trade recommendations.

-   No multi-tenant SaaS; single user, self-hosted.

**Success criteria for v1**

-   A known historical event (e.g. a TSMC or NVIDIA earnings day)
    replayed through the system produces the correct downstream exposure
    list.

-   End-to-end event-to-alert latency p95 \< 5 min on live feeds.

-   Runs on one machine: backend, Postgres and Ollama, with headroom for
    the user\'s other workloads.

## Coverage universe

v1 tracks about 40 listings in five tiers plus a power/infrastructure
side branch, with tradable nodes restricted to German, other European
and US venues. Asian names that matter (Samsung, SK Hynix, Tokyo
Electron) are **context nodes**: end-of-day only, no live feed.

  -------------------------------------------------------------------------------
  Tier           Germany     Rest of Europe   US         Notes
                 (XETRA)                                 
  -------------- ----------- ---------------- ---------- ------------------------
  1\. Frontier   ---         ---              MSFT,      Labs are mostly private;
  labs                                        AMZN,      tracked through
                                              GOOGL,     investor/partner proxies
                                              META       (OpenAI → MSFT,
                                                         Anthropic → AMZN/GOOGL,
                                                         Mistral → ASML)

  2\.            SAP,        OVHcloud (Paris) MSFT,      European sovereign-cloud
  Hyperscalers   Deutsche                     AMZN,      angle is a
  and clouds     Telekom                      GOOGL,     differentiator for DE/EU
                 (DTE)                        ORCL,      focus
                                              CRWV, NBIS 

  3\. Chip and   Infineon    STMicro (Paris), NVDA, AMD, Infineon enters via AI
  network        (IFX)       ARM (US-listed,  AVGO,      data-centre power semis
  designers                  UK HQ)           MRVL, ANET 

  4\. Foundry    Siltronic   ---              TSM (ADR), Samsung, SK Hynix =
  and memory     (WAF)                        MU         context nodes

  5\. Equipment  Aixtron     ASML, ASM        AMAT,      ASML also trades on
  and materials  (AIXA),     International,   LRCX, KLAC NASDAQ: use the dual
                 SÜSS        BESI (Amsterdam)            listing to read EU-to-US
                 MicroTec                                handover
                 (SMHN),                                 
                 Merck KGaA                              
                 (MRK)                                   

  Side: power    Siemens     Schneider        VRT, ETN   Grid and cooling
  and infra      Energy      Electric (Paris)            constraints propagate
                 (ENR),                                  *up* the chain
                 Siemens                                 
                 (SIE)                                   
  -------------------------------------------------------------------------------

**Index layer:** DAX, TecDAX, EURO STOXX 50, PHLX Semiconductor (SOX),
Nasdaq-100, S&P 500. Where index values are not free, track them through
a liquid ETF as a proxy and label it as such.

The list is a seed. Edges and tickers live in the database, not in code,
so the universe grows without a release.

## Data sources (free tier only)

Germany is the best-served region for free data: Deutsche Börse is
required under MiFIR to publish delayed pre- and post-trade data at no
charge. The US is next via Finnhub and Alpaca. Wider-Europe venues are
the gap, and most of those names are reachable through their Xetra or
Tradegate lines.

  -------------------------------------------------------------------------------------------------------------------------------------------
  Source                                                                      Region       What             Freshness   Limits and licence
  --------------------------------------------------------------------------- ------------ ---------------- ----------- ---------------------
  [Deutsche Börse MiFIR delayed                                               DE (Xetra,   Pre- and         15 min      Free; files kept
  data](https://mds.deutsche-boerse.com/mds-en/real-time-data/Delayed-data)   Börse        post-trade       delay,      until midnight of the
                                                                              Frankfurt,   files, gzipped   published   next business day, so
                                                                              Tradegate,   JSON             once per    we must archive our
                                                                              Eurex)                        minute      own history

  Tradegate (via the same file service)                                       DE venue,    Trades in US/EU  15 min      Lets us see EU-hours
                                                                              but lists    names during     delay       reactions in NVDA,
                                                                              many EU and  European hours               TSM etc. before the
                                                                              US shares    and evening                  US open

  [Finnhub](https://qveris.ai/guides/free-stock-api-comparison/)              US + global  WebSocket        Near real   Free tier \~60
                                                                                           trades, quotes,  time        calls/min, \~50
                                                                                           company news                 WebSocket symbols,
                                                                                                                        non-commercial use
                                                                                                                        only

  Alpaca market data                                                          US           Real-time bars   Real time   Free account; IEX is
                                                                                           and trades (IEX              a subset of
                                                                                           feed on free                 consolidated volume
                                                                                           plan)                        

  SEC EDGAR APIs                                                              US           10-K/10-Q/8-K,   Minutes     Free; fair-access
                                                                                           XBRL company     after       rate limit and a
                                                                                           facts, full-text filing      descriptive
                                                                                           search                       User-Agent required

  ESEF filings (filings.xbrl.org)                                             EU           Annual reports   Days        Free; annual cadence,
                                                                                           in XBRL/iXBRL                used for edge
                                                                                                                        extraction, not
                                                                                                                        alerts

  EQS / ad-hoc news RSS                                                       DE/EU        Ad-hoc           Minutes     Free RSS; the single
                                                                                           disclosures (MAR             most important German
                                                                                           Art. 17),                    event source
                                                                                           directors\'                  
                                                                                           dealings                     

  GDELT 2.0                                                                   Global       News event       15 min      Free; noisy, so it
                                                                                           stream with      batches     feeds the LLM
                                                                                           entity tagging               classifier, never
                                                                                                                        alerts directly

  ECB Data Portal and FRED                                                    EU / US      FX reference     Daily       Free; EUR/USD needed
                                                                                           rates, macro                 to compare
                                                                                           series                       cross-venue moves
  -------------------------------------------------------------------------------------------------------------------------------------------

**Rules for the ingestion layer**

-   Every adapter records its source, licence tier and delay in the
    stored row; the UI shows the delay badge per price.

-   No scraping of sites whose terms forbid it (e.g. unofficial Yahoo
    endpoints). If a source needs scraping, it does not go in.

-   Upgrading a source later (e.g. paid Euronext data) must be a new
    adapter, not a change to downstream modules.

## Architecture: modular monolith

One Spring Boot application in Kotlin, built with **Spring Modulith**,
split into eight modules that own their data and talk only through
published APIs and in-process events. We get microservice-style
boundaries without network hops, distributed transactions or eight
deployments.

![Modular monolith · 8 modules, 1
deployable](media/image1.png)

Modular monolith · 8 modules, 1 deployable

Each box is a top-level Kotlin package; only its api subpackage is
visible to other modules, and signals is the one module that turns
everything else into value.

**Boundary rules (enforced in CI, not by convention)**

-   A module exposes a small Kotlin interface plus event types.
    Internals are internal or in non-exported packages.

-   Cross-module calls are synchronous only for queries (e.g. graph
    asking reference for a listing). State changes travel as events.

-   Events are persisted in Spring Modulith\'s publication registry, so
    a crash between publish and handle replays the event on restart.

-   No shared tables. Each module owns its Postgres schema.

**How it scales when it has to**

-   First lever: more CPU and memory on the same box; the hot path is
    light.

-   Second lever: run ingestion and llm as separate instances of the
    *same* jar with Spring profiles, switching the event transport to
    Kafka or Postgres-backed queues through Modulith\'s externalised
    events. No code in the other modules changes.

-   A module is extracted into its own service only when it needs a
    different release cadence or scaling profile, and the boundary is
    already clean when that day comes.

**Package layout**

ai-supply-monitor/\
backend/ (Gradle, Kotlin, Spring Boot 3)\
src/main/kotlin/dev/rishi/aimonitor/\
ingestion/ reference/ marketdata/ events/\
graph/ llm/ signals/ api/\
frontend/ (Vite, React, TypeScript)\
deploy/ (docker-compose, Grafana dashboards)

## Domain model

The core distinction is **Company vs Listing**: edges connect companies,
prices belong to listings. ASML is one company with listings on Euronext
Amsterdam, Xetra, Tradegate and NASDAQ. Every edge is bitemporal
(valid-from/valid-to plus recorded-at) so a replay sees the graph as it
was known on that day, with no look-ahead bias.

\@JvmInline value class CompanyId(val value: String) // LEI where
available, else internal slug\
\@JvmInline value class ListingId(val value: String) // ISIN + MIC, e.g.
NL0010273215@XETR\
\
data class Company(val id: CompanyId, val name: String, val tier: Tier,
val country: String, val tradable: Boolean)\
data class Listing(val id: ListingId, val company: CompanyId, val mic:
String, val currency: Currency, val source: SourceId)\
\
enum class EdgeType { SUPPLIES, CUSTOMER_OF, INVESTS_IN,
COMPUTE_CONTRACT, LICENSES_IP, COMPETES_WITH }\
\
data class Edge(\
val from: CompanyId, val to: CompanyId, val type: EdgeType,\
val weight: Double, // 0..1 share of revenue or spend; null-safe default
0.05 when unknown\
val confidence: Confidence, // DISCLOSED, REPORTED, INFERRED\
val evidence: List\<EvidenceRef\>, // filing URL + section, press
release, article\
val validFrom: LocalDate, val validTo: LocalDate?, val recordedAt:
Instant,\
)\
\
data class MarketEvent(\
val id: EventId, val occurredAt: Instant, val source: SourceId,\
val companies: Set\<CompanyId\>, val kind: EventKind, // EARNINGS,
GUIDANCE, AD_HOC, CAPEX, SUPPLY, REGULATORY, OTHER\
val direction: Direction?, val magnitude: Magnitude?, val summary:
String, val classifiedBy: String,\
)

**Edge weight rules**

-   DISCLOSED: taken from a filing (e.g. a 10-K customer above 10% of
    revenue). Weight = the disclosed share.

-   REPORTED: from a press release or credible reporting, no figure.
    Weight from a fixed scale (0.05 / 0.15 / 0.3).

-   INFERRED: suggested by the LLM. Never used in scoring until a human
    promotes it in the review queue.

## Ingestion and scheduling

Ingestion is a set of adapters behind one port, MarketDataSource, each
normalising into PriceBar (1-minute OHLCV, listing, venue timestamp,
received-at, delay class) or RawDocument. Adapters are scheduled by a
**market-session calendar per MIC**, so nothing polls a closed venue.

  -----------------------------------------------------------------------
  Window (Frankfurt     Active feeds            Why it matters
  time)                                         
  --------------------- ----------------------- -------------------------
  08:00--09:00          Tradegate (incl. US     Pre-open read on how Asia
                        names), EQS ad-hoc,     handed over
                        overnight Asia EOD      

  09:00--15:30          Xetra, Tradegate,       European session; US
                        Finnhub news, GDELT     names visible via
                                                Tradegate only

  15:30--17:30          All of the above +      Overlap: the main EU ↔ US
                        Finnhub/Alpaca live US  propagation window

  17:30--22:00          Tradegate,              US session; EU names
                        Finnhub/Alpaca, SEC     visible via Tradegate
                        EDGAR                   evening trading

  22:00--08:00          EDGAR (after-hours      Edge extraction, LLM
                        filings), batch jobs    backlog, backups
  -----------------------------------------------------------------------

The twice-yearly weeks when the EU and US switch daylight saving on
different dates shift the US open to 14:30. The calendar must derive
windows from venue time zones, never hard-code them.

**Pipeline guarantees**

-   Raw payloads are stored before parsing (raw_ingest table,
    compressed). Any parser bug is fixed by replay, not by re-fetching
    from a source that may have expired the data.

-   Idempotent upserts keyed on (listing, bar start). Late or duplicated
    files are harmless.

-   Each adapter has a circuit breaker and reports a heartbeat; a stale
    feed turns its nodes grey in the UI instead of silently showing old
    prices as current.

## Propagation and signal engine

The engine answers one question every minute: *given what moved, what
should have moved, and what hasn\'t?* It works on abnormal returns (a
stock\'s move minus what its home index explains), so a broad market
sell-off does not light up the whole graph.

For a source shock at company i, the expected abnormal move at linked
company j over the same window is:

\\hat{r}\_j = \\sum\_{i \\in N(j)} \\lambda\^{h\_{ij}} \\, w\_{ij} \\,
\\beta\_{ij} \\, \\tilde{r}\_i

Here w is the edge weight, β the historically fitted sensitivity of j to
i, λ a per-hop decay (start at 0.5, max 2 hops) and r̃ the abnormal
return of i. Divergence is then a z-score of actual minus expected,
scaled by j\'s own recent volatility.

**Signal types**

1.  **Lagging node**: \|z\| \> 2 on j while i\'s shock is itself \> 2σ.
    The core alert.

2.  **Event without price reaction**: a classified event (e.g. ad-hoc
    guidance cut) with no abnormal move in its own listing after 15 min.

3.  **Cross-venue gap**: the same company\'s Tradegate and US listings
    diverge beyond FX-adjusted noise.

4.  **Tier rotation**: a whole tier\'s aggregate abnormal return
    diverges from the tier above or below it (e.g. equipment selling off
    while hyperscalers rally).

**Calibration and honesty**

-   β is fitted nightly on rolling one-year, 30-minute returns. Edges
    without a stable fit fall back to weight-only scoring and are
    flagged as such.

-   Every alert stores its full inputs, so it can be re-scored after a
    model change.

-   A replay harness runs the engine over archived bars and events. Hit
    rate of signal type 1 is a tracked metric, not an assumption. If it
    is no better than chance, the feature is presented as context only.

## Local LLM usage (Ollama)

The LLM is never on the hot path for prices. It only classifies
documents that already passed a cheap deterministic filter, so expected
load is a few hundred short items a day plus a nightly batch.

  -------------------------------------------------------------------------------
  Job              Trigger             Expected      Priority    Fallback when
                                       volume                    backlogged
  ---------------- ------------------- ------------- ----------- ----------------
  Event            New ad-hoc, news    \~100--300    1 (ad-hoc), Rule-based
  classification   item or 8-K that    items/day     2 (news)    classifier:
  (kind,           matched the alias                             keyword + source
  direction,       dictionary                                    type
  companies)                                                     

  Edge extraction  Nightly, new        \~5--20       3           Defer to next
  from filings     10-K/10-Q/ESEF      docs/night,               night
                   reports for tracked chunked                   
                   companies                                     

  Morning summary  07:30 daily         1             3           Template text
  of overnight                                                   with no LLM
  signals                                                        
  -------------------------------------------------------------------------------

**Design rules**

-   **Pre-filter first.** An alias dictionary (company names in English
    and German, tickers, ISINs, key product names) drops irrelevant
    items before any model call. This is what keeps the local box
    viable.

-   **One worker, one model loaded.** A single-concurrency queue with
    priorities avoids model swapping, which costs more than inference on
    limited RAM/VRAM.

-   **Structured output only.** Every call uses a JSON schema (Ollama\'s
    format parameter) and is validated in Kotlin; invalid output is
    retried once, then routed to the fallback.

-   **German-capable model.** Ad-hoc disclosures are often German-first.
    Choose a 7--8B instruct model, Q4-quantised, by scoring candidates
    on a 50-item labelled set (mixed DE/EN) before committing.

-   **Port, not vendor.** LlmClient is an interface; Ollama is one
    adapter. A cloud adapter can be added later behind the same port,
    routed through the user\'s existing privacy gateway if company data
    is ever involved.

-   **Humans approve edges.** LLM-extracted edges enter as INFERRED and
    only affect scoring after review in the UI.

## Frontend (TypeScript)

A single-page app in React + Vite + TypeScript (strict mode), receiving
live updates over Server-Sent Events. SSE fits because the flow is
one-way (server to browser), it reconnects by itself, and it passes
through proxies without WebSocket upgrades.

  -------------------------------------------------------------------------
  View             Purpose                             Key library
  ---------------- ----------------------------------- --------------------
  Supply-chain     Tiers left to right, nodes coloured Cytoscape.js (or
  graph            by abnormal return, edges thickened Sigma.js if the
                   by live propagation score           graph outgrows \~500
                                                       nodes)

  Alert feed       Live signals with expected vs       TanStack Query + SSE
                   actual move, evidence links, delay  
                   badge                               

  Node detail      Intraday chart across all listings  TradingView
                   of a company (Xetra, Tradegate, US) lightweight-charts
                   in one currency                     

  Edge review      Approve, edit or reject INFERRED    Plain table + diff
  queue            edges, with the source passage      view
                   shown                               

  Replay           Pick a past date and step through   Same components,
                   the day as the engine saw it        driven by the replay
                                                       API
  -------------------------------------------------------------------------

**Contract discipline:** the backend publishes an OpenAPI spec;
TypeScript types are generated from it in CI (openapi-typescript).
Nobody hand-writes a DTO twice, and a breaking change fails the frontend
build.

## Storage, deployment, observability, testing

One PostgreSQL instance holds everything. The graph is small (hundreds
of nodes, low thousands of edges) and queries go at most two hops, which
recursive CTEs handle in milliseconds; adding Neo4j would buy nothing
but another process to run.

**Storage**

-   PostgreSQL 16 with the TimescaleDB extension for 1-minute bars
    (hypertables, compression after 7 days, continuous aggregates for
    30-min and daily).

-   One schema per module (marketdata, graph, events, signals); a module
    may only read its own schema. Cross-module reads go through the
    owning module\'s API.

-   Flyway migrations per module, versioned together.

**Deployment**

-   Docker Compose: app (Spring Boot fat jar, also serving the built
    frontend), postgres, and the existing host Ollama reached over its
    local port.

-   Container memory caps on app and postgres so Ollama keeps its share
    of the machine.

-   Secrets (Finnhub, Alpaca keys) via environment files excluded from
    Git.

**Observability**

-   Micrometer metrics: per-feed lag, bars/min, LLM queue depth and
    latency, alert counts. Prometheus + Grafana optional; the app\'s own
    /admin page shows the same health in v1.

-   Structured JSON logs with a correlation id from raw ingest through
    to alert.

**Testing pyramid**

-   Architecture tests: ApplicationModules.verify() fails the build on
    any illegal cross-module dependency or cycle.

-   Module tests with \@ApplicationModuleTest and Testcontainers
    Postgres, one module booted at a time.

-   Adapter contract tests on recorded real payloads (Deutsche Börse
    JSON, Finnhub messages, EDGAR JSON).

-   Golden replay tests: a fixed archived day must produce the same
    alerts after every change to the engine.

-   Build: Gradle Kotlin DSL with a version catalog, detekt and ktlint
    in CI.

## Milestones

Delivery runs as thin vertical slices: every phase ends with something
running end to end, never a finished layer waiting for the next one. M3
is where the product\'s value appears; everything before it is plumbing
that must be boring and reliable.

![Delivery plan · 5 phases with exit
gates](media/image2.png)

Delivery plan · 5 phases with exit gates

The first concrete step is M0: create the repo, wire Spring Modulith\'s
verify() into CI, and ingest one Deutsche Börse post-trade file into
Timescale.

## Risks, open questions, decisions

**Decision log**

  --------------------------------------------------------------------------
  \#      Decision             Alternative      Reason
                               rejected         
  ------- -------------------- ---------------- ----------------------------
  ADR-1   Modular monolith on  Microservices;   Boundaries enforced by
          Spring Boot + Spring Ktor +           tests, in-process events
          Modulith (Kotlin)    hand-rolled      with a durable publication
                               boundaries       log, one deployable

  ADR-2   PostgreSQL +         Neo4j + separate Graph is small and shallow;
          TimescaleDB for bars TSDB             one database to run and back
          and graph                             up

  ADR-3   SSE for live UI      WebSocket        One-way flow,
          updates                               auto-reconnect, simpler ops

  ADR-4   LLM only off the hot LLM classifying  Local hardware is limited;
          path, behind a       every news item  prices must never wait on a
          pre-filter                            model

  ADR-5   LLM-inferred edges   Auto-accept      One wrong high-weight edge
          need human approval  above a          corrupts every downstream
                               confidence score score
  --------------------------------------------------------------------------

**Risks**

  --------------------------------------------------------------------------
  Risk                      Impact           Mitigation
  ------------------------- ---------------- -------------------------------
  Free-tier terms change or Feed gap         Adapter per source, heartbeat
  a source disappears                        alerts, raw archive for replay

  Euronext names only       Weaker EU signal Accept for v1; label delay per
  visible with 15-min delay in the           node; evaluate a paid EU feed
  or via Xetra/Tradegate    15:30--17:30     only if replay shows value
  lines                     overlap          

  Finnhub free tier is      Blocks any       Keep v1 personal; licence
  non-commercial            future           review is a gate before sharing
                            productisation   

  Edge weights are guesses  Noisy expected   Confidence levels, weight-only
  for undisclosed           moves            fallback, replay hit-rate
  relationships                              tracked

  Local model weak on       Misclassified    50-item DE/EN eval set before
  German ad-hoc text        events           model choice; rule fallback
  --------------------------------------------------------------------------

**Open questions**

-   [ ] Does Euronext publish free MiFIR delayed data in a usable
    machine format, as Deutsche Börse does?

-   [ ] Which ASML, ARM and TSM lines trade on Xetra/Tradegate with
    enough volume to be useful?

-   [ ] Are EQS ad-hoc RSS feeds still offered openly, and with what
    reuse terms?

-   [ ] Exact current Finnhub and Alpaca free-tier limits, checked on
    their own pricing pages before the adapters are built.
