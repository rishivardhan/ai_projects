# CRM Copilot: an agentic layer over a NoSQL CRM

An end-to-end system with three layers:

1. **A NoSQL CRM database** (MongoDB document model) with realistic dummy data: accounts, contacts, opportunities, leads, interactions and tasks.
2. **A tool-use framework**: 16 CRM tools (10 read, 6 write). Each tool has schema validation, an approval gate for writes and errors the model can recover from.
3. **An agent** built on Claude that decides on each turn whether to query records, retrieve documents or notes (RAG), or write to the CRM. You can use it from a terminal or a web UI.

```
 ┌──────────── Web UI (chat + live dashboard) ─────────┐   ┌─── Terminal CLI ───┐
 │  POST /api/chat → Server-Sent Events (tool trace)   │   │  python -m ...cli  │
 └───────────────────────────┬─────────────────────────┘   └─────────┬──────────┘
                             ▼                                       ▼
                ┌──────────────────────────── CRMAgent (agent.py) ───────────────────────────┐
                │ Claude Messages API · adaptive thinking · tool-use loop · refusal fallback │
                └───────────────┬──────────────────────────────────────┬─────────────────────┘
                                ▼                                      ▼
            ┌────────── ToolRegistry (tools/registry.py) ──────────┐   │ ToolResult → tool_result
            │ JSON-schema validation · write approval · errors      │◄──┘
            └──────┬────────────────────────────────┬──────────────┘
                   ▼                                ▼
     CRM tools (tools/crm_tools.py)       search_knowledge (RAG)
     search_accounts, get_account_360,    ┌──── Retriever (rag/index.py) ────┐
     list_opportunities, pipeline_summary,│ BM25 over knowledge-base markdown │
     search_leads, get_interactions, ...  │ + every interaction note          │
     log_interaction, update_opportunity, └───────────────┬──────────────────┘
     create_task, convert_lead, ...                       │
                   ▼                                      ▼
        ┌────────────────── NoSQL DB (db.py) ──────────────────┐
        │ MongoDB (MONGO_URI) or embedded mongomock + JSON file │
        │ accounts · contacts · opportunities · leads ·         │
        │ interactions · tasks                                  │
        └───────────────────────────────────────────────────────┘
```

## Quick start

```bash
cd crm-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env              # then put your ANTHROPIC_API_KEY in .env

python -m crm_agent.seed          # creates the dummy data (it also happens automatically on first run)
python -m crm_agent.server        # web UI → http://127.0.0.1:8000
# or
python -m crm_agent.cli           # terminal chat
```

No database server is needed. If `MONGO_URI` is unset, the CRM runs on an embedded MongoDB-compatible store (`mongomock`), saved to `data/crm_snapshot.json`. To use a real MongoDB instead:

```bash
docker compose up -d
export MONGO_URI=mongodb://localhost:27017
python -m crm_agent.seed --reset
```

## Things to ask

| Question | What the agent does |
|---|---|
| "Give me a pipeline summary by stage and flag anything risky" | Calls `pipeline_summary`, then `list_opportunities(past_due / stalled_days)` |
| "Prepare me for a meeting with Globex Financial" | Calls `get_account_360`, then `search_knowledge` scoped to the account for objections and concerns |
| "Globex wants 25% off a 2-year deal. Who needs to approve that?" | Looks up the deal, then retrieves the discount policy from the knowledge base (RAG) |
| "Who has raised data residency or security concerns?" | Searches interaction notes by meaning (RAG over notes) |
| "Which customers are at risk before renewal and why?" | Calls `search_accounts(renewal_within_days, max_health)`, then pulls interactions and the renewal policy |
| "Show my top qualified leads and convert the best one" | Calls `search_leads`, then `convert_lead` (a write, so you approve it first) |
| "Log a call with Acme: they want SSO via Okta, follow up next Friday" | Calls `log_interaction` and `create_task` (writes) |

## How it's built, step by step

Each step is one module and can be read on its own.

### Step 1: NoSQL data model (`crm_agent/db.py`)
The data is document-oriented. Each record is a JSON-like document, and documents reference each other by ID (`account_id`, `opportunity_id`, ...), the usual pattern for MongoDB.

| Collection | Key fields |
|---|---|
| `accounts` | `_id` (ACC-001), name, industry, tier (Strategic/Enterprise/Mid-Market/SMB), status (Customer/Prospect/Churned), owner, health_score, arr, renewal_date, tags[] |
| `contacts` | `_id` (CON-001), account_id, full_name, title, department, seniority, email, phone, is_primary |
| `opportunities` | `_id` (OPP-001), account_id, stage, amount, probability, close_date, products[], competitor, next_step, loss_reason |
| `leads` | `_id` (LEAD-001), company, full_name, source, status, score, interest, owner, converted_account_id |
| `interactions` | `_id` (INT-0001), type (Call/Email/Meeting/Demo/Support Ticket/Note), notes (free text), sentiment, timestamp, links to account/contact/opportunity/lead |
| `tasks` | `_id` (TASK-001), subject, due_date, status, priority, owner, account_id / opportunity_id / lead_id |

Secondary indexes are created on the fields the tools filter by. `connect()` returns a real `pymongo` database or a `mongomock` one. Both have the same API, so nothing above this layer cares which one it gets.

### Step 2: Dummy data (`crm_agent/seed.py`)
A deterministic generator (fixed seed) creates a consistent dataset for a fictional data-platform vendor, Northwind Cloud: 25 accounts, ~85 contacts, ~40 opportunities across every stage, 30 leads, ~170 interactions with free-text notes, and ~20 tasks. Dates are relative to the day you seed, so questions like "closing this month" always have answers. The data deliberately includes things worth finding: past-due deals, stalled deals, a champion leaving, competitor discounting, failing reports in support tickets, and low-health customers close to renewal.

### Step 3: Knowledge base (`crm_agent/rag/knowledge/*.md`)
These are company documents the agent can cite: product catalog and list prices, the pricing and discount approval policy, the sales playbook (stage exit criteria, deal hygiene, lead qualification), objection handling, and support SLAs and renewal policy. Add a markdown file here and it gets indexed. Each `## Section` becomes one chunk.

### Step 4: Retrieval (`crm_agent/rag/index.py`)
BM25 is implemented in pure Python, with no embedding API or vector database. The index covers the knowledge-base sections and every interaction note, and each note keeps account and opportunity metadata so a search can be scoped to one account. It rebuilds in milliseconds at startup and updates incrementally when the agent logs a new interaction. To switch to embeddings, swap out `Retriever.search`; the tools only depend on that interface.

### Step 5: The tool-use framework (`crm_agent/tools/registry.py`, `crm_agent/tools/crm_tools.py`)
`@registry.tool(description=..., properties=..., required=..., mutating=...)` turns a Python function into a Claude tool. The registry takes care of:
- **schema rendering** for the Messages API `tools` list, in a stable order so the prompt cache stays warm;
- **input validation**: required fields, types, enums and unknown keys. A bad call goes back to Claude as an `is_error` tool result, and Claude corrects itself;
- **an approval gate** for `mutating=True` tools. The CLI asks y/N, the web UI uses an "Allow write actions" toggle, and tests use a callback;
- **error isolation**: any exception becomes an error result, and the loop keeps running;
- **JSON serialization** of dates and other values.

Tools accept either an account ID or an account name, and an ambiguous name returns the list of candidates.

| Read tools | Write tools (need approval) |
|---|---|
| `search_accounts`, `get_account_360`, `search_contacts`, `list_opportunities`, `get_opportunity`, `pipeline_summary`, `search_leads`, `get_interactions`, `list_tasks`, `search_knowledge` (RAG) | `log_interaction`, `update_opportunity`, `create_task`, `complete_task`, `update_lead`, `convert_lead` |

### Step 6: The agent (`crm_agent/agent.py`)
The tool-use loop is written out by hand on the Claude Messages API:
1. Send the conversation, the system prompt and the tool schemas to Claude.
2. If Claude returns `tool_use` blocks, run every requested tool through the registry and send all the results back in **one** `tool_result` message. Claude may ask for several tools in parallel.
3. Repeat until Claude ends its turn, with a step limit as a safeguard.

RAG happens "as needed" because retrieval is just another tool, `search_knowledge`. Claude decides when a question needs documents or notes rather than structured records, and often combines the two (for example, it looks up the deal and then the discount policy that applies to it).

Each step is yielded as an `AgentEvent` (`thinking`, `tool_call`, `tool_result`, `text`, `notice`, `error`, `done`), so the interfaces can stream progress.

API settings:
- **Model:** `claude-opus-5-5`. Override it with `CRM_MODEL`.
- **Thinking:** adaptive, with summaries shown in the trace.
- **Effort:** `CRM_EFFORT`, default `medium`.
- **Caching:** the tools and system prompt form a stable, cached prefix.
- **History:** the full assistant content, including thinking and tool-use blocks, is appended back on every turn, so the history is append-only.
- **Refusals:** `stop_reason == "refusal"` is handled, and server-side refusal fallback (`fallbacks: "default"`) is on by default. Turn it off with `CRM_FALLBACKS=0`.
- **Errors:** errors and refusals roll back the partial turn, so the conversation history stays valid.

### Step 7: Interfaces (`crm_agent/cli.py`, `crm_agent/server.py`, `crm_agent/web/index.html`)
- **CLI:** interactive chat with a live tool trace. `/tool NAME {json}` calls a tool directly, without an API key, which is handy for exploring the data.
- **FastAPI server:** `/api/chat` streams agent events over Server-Sent Events. There are also `/api/dashboard`, `/api/tools`, `/api/tools/{name}` and `/api/records/{collection}` endpoints.
- **Web UI:** chat with collapsible "used N tool calls" traces, a pipeline dashboard in the sidebar, suggested prompts and the write-approval toggle. It needs no build step.

### Step 8: Tests (`tests/`)
```bash
pytest -q
```
The 25 tests cover data integrity, retrieval quality, every tool (filters, validation, approval, writes), the server, and the **full agent loop** driven by a scripted fake Claude client. The fake client checks parallel tool results, error recovery, declined writes, refusal rollback and the step limit, all without an API key.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API key (required for the agent; tools, RAG and the dashboard work without it) |
| `MONGO_URI` / `MONGO_DB` | unset / `crm` | Use a real MongoDB instead of the embedded store |
| `CRM_MODEL` | `claude-opus-5-5` | Model ID |
| `CRM_EFFORT` | `medium` | `low` / `medium` / `high` / `xhigh` / `max` |
| `CRM_FALLBACKS` | `1` | Server-side refusal fallback |
| `CRM_MAX_STEPS` | `15` | Max model calls per user turn |
| `CRM_SNAPSHOT` | `data/crm_snapshot.json` | Embedded-store persistence file |

## Extending it
- **New tool:** add a decorated function in `tools/crm_tools.py`. It shows up in the agent, the CLI's `/tools` and `/api/tools` automatically.
- **New knowledge:** drop a markdown file into `rag/knowledge/`.
- **Better retrieval:** replace BM25 in `Retriever.search` with embeddings and a vector index (for example MongoDB Atlas Vector Search) without touching the tools.
- **Real users:** replace the `user` field with authenticated identities and scope tool queries by owner or team.
