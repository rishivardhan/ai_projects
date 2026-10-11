# CRM Copilot: an agentic layer over a NoSQL CRM

An end-to-end system with three layers:

1. **A NoSQL CRM database** (MongoDB document model) with realistic dummy data: accounts, contacts, opportunities, leads, interactions and tasks.
2. **A tool-use framework**: 20 tools (CRM records, RAG search and the decision model). Each tool has schema validation, an approval gate for writes and errors the model can recover from.
3. **A decision model**: a small machine-learning model trained on past deal outcomes. It scores every open deal, recommends an action, and approves, escalates or rejects discount requests. Its decisions are enforced in code, so the chatbot can explain them but cannot override them.
4. **An agent** built on Claude that decides on each turn whether to query records, retrieve documents or notes (RAG), consult the decision model, or write to the CRM. You can use it from a terminal or a web UI.

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
            └──────┬────────────────────┬────────────────────┬─────┘
                   ▼                    ▼                    ▼
     CRM tools                search_knowledge (RAG)    Decision model tools
     (tools/crm_tools.py)     ┌─ rag/index.py ──────┐   (tools/decision_tools.py)
     search_accounts,         │ BM25 over policy    │   score_deal, prioritize_deals,
     get_account_360,         │ docs + every        │   request_discount (enforced)
     list_opportunities, ...  │ interaction note    │   ┌─ decision/ ───────────────┐
     log_interaction,         └─────────┬───────────┘   │ features → logistic-      │
     update_opportunity, ...            │               │ regression win model →    │
                   │                    │               │ policy (action, discount) │
                   │                    │               └─────────────┬─────────────┘
                   ▼                    ▼                             ▼
        ┌───────────────────────── NoSQL DB (db.py) ──────────────────────────┐
        │ MongoDB (MONGO_URI) or embedded mongomock + JSON file                │
        │ accounts · contacts · opportunities · leads · interactions · tasks · │
        │ deal_history (model training data) · decisions (audit log)           │
        └──────────────────────────────────────────────────────────────────────┘
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
| "Which deals should I focus on this week?" | Calls `prioritize_deals(action="Intervene", sort_by="value_at_risk")` (decision model) |
| "Request a 15% discount on OPP-029, budget is tight" | Calls `request_discount`; the model decides APPROVE / ESCALATE / REJECT and the app enforces it |
| "How does the decision model work and how accurate is it?" | Calls `decision_model_info` (model card) |

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
| `deal_history` | `_id` (HIST-0001), features{...}, outcome (Won/Lost): 600 past deals the decision model is trained on |
| `decisions` | `_id` (DEC-0001), audit log of every discount decision: inputs, model version, decision, reason, effect |

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
| `search_accounts`, `get_account_360`, `search_contacts`, `list_opportunities`, `get_opportunity`, `pipeline_summary`, `search_leads`, `get_interactions`, `list_tasks`, `search_knowledge` (RAG), `score_deal`, `prioritize_deals`, `decision_model_info` (decision model) | `log_interaction`, `update_opportunity`, `create_task`, `complete_task`, `update_lead`, `convert_lead`, `request_discount` (decision model) |

### Step 5c: The decision model (`crm_agent/decision/`, `crm_agent/tools/decision_tools.py`)
This is a small, explainable model that acts as the **deciding factor** for deal judgments. It has three parts.

**1. Features** (`decision/features.py`). Each open deal becomes 11 numbers computed from the database: sales stage, account health, existing customer or not, days since the last touchpoint, share of negative interactions in the last 90 days, competitor involved, close date passed, discount, deal size, executive engaged, and champion or project risk (phrases like "leaving the company" in notes). Past deals in `deal_history` are stored as the same 11 numbers plus Won or Lost.

**2. Win-probability model** (`decision/model.py`). A logistic regression trained with numpy on 600 past deals in milliseconds at startup. On a 25% holdout it scores **AUC ≈ 0.77** and 70% accuracy, against 56% for always guessing the most common outcome. Every prediction breaks down into per-factor contributions such as "Last touchpoint: 45 days ago, hurts". These come with the playbook action for each top risk, so nothing is a black box. The model card is available through `decision_model_info` and `/api/model`.

**3. Decision policy** (`decision/policy.py`) turns the probability into decisions. All thresholds are constants in one file.

| Win probability | Action |
|---|---|
| ≥ 65% | **Accelerate**: focus on closing steps |
| 40–65% | **Intervene**: act on the top risk factors now |
| 20–40% | **Re-qualify**: re-validate pain, budget and decision process |
| < 20% | **Deprioritize**: minimize effort |

The policy decides discounts by combining the economics with the authority rules in the pricing policy:
- **Economics:** expected revenue = win probability × net amount. A discount is only worth giving if the lift in win probability outweighs the lost revenue.
- **REJECT** when the discount lowers expected revenue (typical for deals already likely to win), when the deal is below 20% win probability (price isn't the problem), or when the discount is above 30%. A counter-offer is suggested when a smaller discount would do better.
- **APPROVE** when the discount is worth it and is ≤10% (account-executive authority). The discount is applied to the deal.
- **ESCALATE** when it is worth it but is 10–30%. A high-priority approval task goes to the Regional Sales Director (≤20%) or to the VP of Sales + Deal Desk (≤30%). The deal stays unchanged.

**How it is enforced:** `request_discount` is the only way to discount a deal. `update_opportunity` refuses to cut an amount by more than 10%, and every decision is written to the `decisions` audit collection. The system prompt tells Claude to present the model's numbers and decisions and never to make up its own probabilities. Claude still adds the "why" from notes and policies.

The training history is synthetic: outcomes are drawn from a hidden formula in `seed.py` so the model has a real signal to learn. To use your own outcomes, fill `deal_history` with your past deals; the model retrains from whatever it finds there.

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
The 32 tests cover data integrity, retrieval quality, every tool (filters, validation, approval, writes), the decision model (learning, explanations, policy rules, enforcement and audit), the server, and the **full agent loop** driven by a scripted fake Claude client. The fake client checks parallel tool results, error recovery, declined writes, refusal rollback and the step limit, all without an API key.

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
- **Tune decisions:** edit the thresholds and authority table in `decision/policy.py`, or add a feature in `decision/features.py` (and to `deal_history`).
- **New tool:** add a decorated function in `tools/crm_tools.py`. It shows up in the agent, the CLI's `/tools` and `/api/tools` automatically.
- **New knowledge:** drop a markdown file into `rag/knowledge/`.
- **Better retrieval:** replace BM25 in `Retriever.search` with embeddings and a vector index (for example MongoDB Atlas Vector Search) without touching the tools.
- **Real users:** replace the `user` field with authenticated identities and scope tool queries by owner or team.
