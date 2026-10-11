"""Step 5b - The CRM tools the agent can call.

Read tools query the document database (and the RAG retriever); write tools are
flagged ``mutating=True`` so the framework asks for approval before running them.
Tool descriptions are written for the model: what the tool does, when to use it,
and what comes back.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..seed import PRODUCTS, STAGES
from .registry import ToolContext, ToolRegistry

registry = ToolRegistry()

STAGE_NAMES = [s for s, _ in STAGES]
OPEN_STAGES = STAGE_NAMES[:4]
STAGE_PROBABILITY = dict(STAGES)
INTERACTION_TYPES = ["Call", "Email", "Meeting", "Demo", "Support Ticket", "Note"]

ACCOUNT_FIELDS = ["_id", "name", "industry", "tier", "status", "region", "country", "city", "employees",
                  "owner", "health_score", "arr", "renewal_date", "tags"]
OPP_FIELDS = ["_id", "name", "account_id", "type", "stage", "amount", "probability", "close_date", "owner",
              "products", "competitor", "next_step", "loss_reason", "primary_contact_id", "updated_at"]
CONTACT_FIELDS = ["_id", "account_id", "full_name", "title", "department", "seniority", "email", "phone",
                  "is_primary"]
LEAD_FIELDS = ["_id", "full_name", "company", "title", "email", "industry", "source", "status", "score",
               "interest", "estimated_employees", "owner", "created_at", "converted_account_id"]
INTERACTION_FIELDS = ["_id", "type", "timestamp", "subject", "notes", "sentiment", "owner", "account_id",
                      "contact_id", "opportunity_id", "lead_id"]
TASK_FIELDS = ["_id", "subject", "due_date", "status", "priority", "owner", "account_id", "opportunity_id",
               "lead_id"]


# ---------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _today() -> datetime:
    return _now().replace(hour=0, minute=0, second=0)


def _pick(doc: dict | None, fields: list[str]) -> dict | None:
    if doc is None:
        return None
    return {f: doc.get(f) for f in fields if doc.get(f) is not None}


def _ci(text: str) -> dict:
    """Case-insensitive 'contains' match."""
    return {"$regex": re.escape(text), "$options": "i"}


def _parse_date(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"{field} must be a date in YYYY-MM-DD format, got {value!r}") from e


def _next_id(coll, prefix: str, width: int) -> str:
    best = 0
    for doc in coll.find({"_id": {"$regex": f"^{prefix}-"}}, {"_id": 1}):
        try:
            best = max(best, int(doc["_id"].split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{best + 1:0{width}d}"


def resolve_account(db, account: str) -> dict:
    """Accept an account ID (ACC-001) or a (partial) account name."""
    doc = db.accounts.find_one({"_id": account.upper()}) if account.upper().startswith("ACC-") else None
    if doc:
        return doc
    matches = list(db.accounts.find({"name": _ci(account)}).limit(5))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"no account matches '{account}'")
    exact = [m for m in matches if m["name"].lower() == account.lower()]
    if exact:
        return exact[0]
    raise LookupError(f"'{account}' is ambiguous: " + ", ".join(f"{m['_id']} {m['name']}" for m in matches))


def _account_names(db, ids) -> dict[str, str]:
    ids = [i for i in set(ids) if i]
    return {a["_id"]: a["name"] for a in db.accounts.find({"_id": {"$in": ids}}, {"name": 1})}


def _with_account_names(db, docs: list[dict]) -> list[dict]:
    names = _account_names(db, [d.get("account_id") for d in docs])
    for d in docs:
        if d.get("account_id") in names:
            d["account_name"] = names[d["account_id"]]
    return docs


# ---------------------------------------------------------------------------------------
# read tools
# ---------------------------------------------------------------------------------------
@registry.tool(
    description="""
Search and filter customer/prospect accounts. All filters are optional and combined with AND.
Use this to find accounts by name, industry, tier, lifecycle status, region, owner (sales rep),
health score range or upcoming renewal. Returns a list of account summaries with their IDs
(ACC-xxx) - use get_account_360 for full detail on one account.""",
    properties={
        "query": {"type": "string", "description": "Case-insensitive substring of the account name"},
        "industry": {"type": "string", "description": "e.g. Technology, Financial Services, Retail"},
        "tier": {"type": "string", "enum": ["Strategic", "Enterprise", "Mid-Market", "SMB"]},
        "status": {"type": "string", "enum": ["Customer", "Prospect", "Churned"]},
        "region": {"type": "string", "enum": ["NA", "EMEA", "APAC"]},
        "owner": {"type": "string", "description": "Account owner (sales rep) name"},
        "min_health": {"type": "integer", "description": "Minimum health score (0-100, customers only)"},
        "max_health": {"type": "integer", "description": "Maximum health score (0-100, customers only)"},
        "renewal_within_days": {"type": "integer", "description": "Only customers renewing within N days"},
        "limit": {"type": "integer", "description": "Max results (default 25)"},
    },
)
def search_accounts(ctx: ToolContext, query=None, industry=None, tier=None, status=None, region=None,
                    owner=None, min_health=None, max_health=None, renewal_within_days=None, limit=25):
    q: dict = {}
    if query:
        q["name"] = _ci(query)
    if industry:
        q["industry"] = _ci(industry)
    if tier:
        q["tier"] = tier
    if status:
        q["status"] = status
    if region:
        q["region"] = region
    if owner:
        q["owner"] = _ci(owner)
    if min_health is not None or max_health is not None:
        q["health_score"] = {k: v for k, v in (("$gte", min_health), ("$lte", max_health)) if v is not None}
    if renewal_within_days is not None:
        q["renewal_date"] = {"$gte": _today(), "$lte": _today() + timedelta(days=renewal_within_days)}
    docs = list(ctx.db.accounts.find(q).sort("name", 1).limit(limit or 25))
    return {"count": len(docs), "accounts": [_pick(d, ACCOUNT_FIELDS) for d in docs]}


@registry.tool(
    description="""
Get a complete 360-degree view of one account: firmographics, health and renewal, all contacts,
all opportunities (open and closed), open tasks, and the most recent interactions.
Accepts an account ID (ACC-xxx) or an account name. Use this before summarizing an account,
preparing for a meeting, or assessing deal risk.""",
    properties={
        "account": {"type": "string", "description": "Account ID (ACC-001) or account name"},
        "recent_interactions": {"type": "integer", "description": "How many recent interactions (default 8)"},
    },
    required=["account"],
)
def get_account_360(ctx: ToolContext, account, recent_interactions=8):
    acc = resolve_account(ctx.db, account)
    aid = acc["_id"]
    opps = list(ctx.db.opportunities.find({"account_id": aid}).sort("close_date", 1))
    interactions = list(ctx.db.interactions.find({"account_id": aid}).sort("timestamp", -1)
                        .limit(recent_interactions or 8))
    open_opps = [o for o in opps if o["stage"] in OPEN_STAGES]
    return {
        "account": _pick(acc, ACCOUNT_FIELDS + ["website", "annual_revenue", "created_at"]),
        "contacts": [_pick(c, CONTACT_FIELDS) for c in ctx.db.contacts.find({"account_id": aid})],
        "opportunities": [_pick(o, OPP_FIELDS) for o in opps],
        "open_pipeline": {"count": len(open_opps), "total_amount": sum(o["amount"] for o in open_opps),
                          "weighted_amount": round(sum(o["amount"] * o["probability"] / 100 for o in open_opps))},
        "open_tasks": [_pick(t, TASK_FIELDS) for t in ctx.db.tasks.find({"account_id": aid, "status": "Open"})],
        "recent_interactions": [_pick(i, INTERACTION_FIELDS) for i in interactions],
        "interaction_sentiment_last_90d": _sentiment_counts(ctx.db, {"account_id": aid}, 90),
    }


def _sentiment_counts(db, q: dict, days: int) -> dict:
    q = dict(q, timestamp={"$gte": _now() - timedelta(days=days)})
    out = {"positive": 0, "neutral": 0, "negative": 0}
    for row in db.interactions.aggregate([{"$match": q}, {"$group": {"_id": "$sentiment", "n": {"$sum": 1}}}]):
        out[row["_id"]] = row["n"]
    return out


@registry.tool(
    description="""
Search contacts (people at accounts). Filter by name/email/title text, account, seniority or department.
Returns contact details including email and phone and the account they belong to.""",
    properties={
        "query": {"type": "string", "description": "Substring matched against name, email and title"},
        "account": {"type": "string", "description": "Account ID or name to restrict to"},
        "seniority": {"type": "string", "enum": ["C-Level", "VP", "Director", "Manager", "Individual Contributor"]},
        "department": {"type": "string"},
        "limit": {"type": "integer", "description": "Max results (default 25)"},
    },
)
def search_contacts(ctx: ToolContext, query=None, account=None, seniority=None, department=None, limit=25):
    q: dict = {}
    if query:
        q["$or"] = [{"full_name": _ci(query)}, {"email": _ci(query)}, {"title": _ci(query)}]
    if account:
        q["account_id"] = resolve_account(ctx.db, account)["_id"]
    if seniority:
        q["seniority"] = seniority
    if department:
        q["department"] = _ci(department)
    docs = [_pick(d, CONTACT_FIELDS) for d in ctx.db.contacts.find(q).limit(limit or 25)]
    return {"count": len(docs), "contacts": _with_account_names(ctx.db, docs)}


@registry.tool(
    description="""
List and filter opportunities (deals). Useful for pipeline questions such as "deals closing this month",
"past-due deals", "stalled deals", "biggest deals in negotiation", or "Priya's open pipeline".
- open_only: only stages Prospecting/Qualification/Proposal/Negotiation.
- closing_within_days: open deals with close_date between today and today+N.
- past_due: open deals whose close_date is already in the past (hygiene problem).
- stalled_days: open deals with no logged interaction in the last N days.
Results include account names, amount, stage, probability, close date and next step.""",
    properties={
        "account": {"type": "string", "description": "Account ID or name"},
        "stage": {"type": "string", "enum": STAGE_NAMES},
        "owner": {"type": "string", "description": "Opportunity owner (sales rep) name"},
        "open_only": {"type": "boolean"},
        "min_amount": {"type": "number"},
        "closing_within_days": {"type": "integer"},
        "past_due": {"type": "boolean"},
        "stalled_days": {"type": "integer"},
        "product": {"type": "string", "enum": list(PRODUCTS)},
        "sort_by": {"type": "string", "enum": ["amount", "close_date", "probability", "updated_at"],
                    "description": "Default close_date ascending; amount/probability sort descending"},
        "limit": {"type": "integer", "description": "Max results (default 25)"},
    },
)
def list_opportunities(ctx: ToolContext, account=None, stage=None, owner=None, open_only=False, min_amount=None,
                       closing_within_days=None, past_due=False, stalled_days=None, product=None,
                       sort_by="close_date", limit=25):
    q: dict = {}
    if account:
        q["account_id"] = resolve_account(ctx.db, account)["_id"]
    if stage:
        q["stage"] = stage
    elif open_only or past_due or closing_within_days is not None or stalled_days is not None:
        q["stage"] = {"$in": OPEN_STAGES}
    if owner:
        q["owner"] = _ci(owner)
    if min_amount is not None:
        q["amount"] = {"$gte": min_amount}
    if product:
        q["products"] = product
    if closing_within_days is not None:
        q["close_date"] = {"$gte": _today(), "$lte": _today() + timedelta(days=closing_within_days)}
    if past_due:
        q["close_date"] = {"$lt": _today()}
    direction = 1 if sort_by in (None, "close_date") else -1
    docs = list(ctx.db.opportunities.find(q).sort(sort_by or "close_date", direction))

    if stalled_days is not None:
        cutoff = _now() - timedelta(days=stalled_days)
        active = {i["opportunity_id"] for i in ctx.db.interactions.find(
            {"opportunity_id": {"$in": [d["_id"] for d in docs]}, "timestamp": {"$gte": cutoff}},
            {"opportunity_id": 1})}
        docs = [d for d in docs if d["_id"] not in active]

    total = sum(d["amount"] for d in docs)
    docs = docs[: limit or 25]
    out = _with_account_names(ctx.db, [_pick(d, OPP_FIELDS) for d in docs])
    return {"count": len(out), "total_amount_all_matches": total, "opportunities": out}


@registry.tool(
    description="""
Get one opportunity with its account, primary contact, related open tasks and full interaction history.
Use before giving deal advice, writing a follow-up email, or assessing risk on a specific deal.""",
    properties={"opportunity_id": {"type": "string", "description": "Opportunity ID, e.g. OPP-007"}},
    required=["opportunity_id"],
)
def get_opportunity(ctx: ToolContext, opportunity_id):
    opp = ctx.db.opportunities.find_one({"_id": opportunity_id.upper()})
    if not opp:
        raise LookupError(f"opportunity {opportunity_id}")
    return {
        "opportunity": _pick(opp, OPP_FIELDS + ["created_at"]),
        "account": _pick(ctx.db.accounts.find_one({"_id": opp["account_id"]}), ACCOUNT_FIELDS),
        "primary_contact": _pick(ctx.db.contacts.find_one({"_id": opp.get("primary_contact_id")}), CONTACT_FIELDS),
        "open_tasks": [_pick(t, TASK_FIELDS) for t in ctx.db.tasks.find({"opportunity_id": opp["_id"],
                                                                         "status": "Open"})],
        "interactions": [_pick(i, INTERACTION_FIELDS) for i in
                         ctx.db.interactions.find({"opportunity_id": opp["_id"]}).sort("timestamp", -1)],
    }


@registry.tool(
    description="""
Aggregate the sales pipeline. Returns count, total amount and probability-weighted amount per group.
group_by: stage | owner | tier (account tier) | close_month | product. By default only open deals
are included; set include_closed=true to include Closed Won / Closed Lost (e.g. for win-rate questions).""",
    properties={
        "group_by": {"type": "string", "enum": ["stage", "owner", "tier", "close_month", "product"]},
        "owner": {"type": "string", "description": "Restrict to one owner"},
        "include_closed": {"type": "boolean"},
    },
    required=["group_by"],
)
def pipeline_summary(ctx: ToolContext, group_by, owner=None, include_closed=False):
    match: dict = {} if include_closed else {"stage": {"$in": OPEN_STAGES}}
    if owner:
        match["owner"] = _ci(owner)
    opps = list(ctx.db.opportunities.find(match))
    tiers = {a["_id"]: a["tier"] for a in ctx.db.accounts.find({}, {"tier": 1})}

    groups: dict[str, dict] = {}

    def add(key, opp, amount):
        g = groups.setdefault(key, {"group": key, "count": 0, "total_amount": 0, "weighted_amount": 0.0})
        g["count"] += 1
        g["total_amount"] += amount
        g["weighted_amount"] += amount * opp["probability"] / 100

    for o in opps:
        if group_by == "product":  # split the amount evenly across products for attribution
            for p in o["products"]:
                add(p, o, o["amount"] / len(o["products"]))
            continue
        key = {"stage": o["stage"], "owner": o["owner"], "tier": tiers.get(o["account_id"], "Unknown"),
               "close_month": o["close_date"].strftime("%Y-%m")}[group_by]
        add(key, o, o["amount"])

    rows = sorted(groups.values(), key=lambda g: (STAGE_NAMES.index(g["group"]) if group_by == "stage"
                                                  else g["group"] if group_by == "close_month"
                                                  else -g["total_amount"]))
    for g in rows:
        g["total_amount"] = round(g["total_amount"])
        g["weighted_amount"] = round(g["weighted_amount"])
    result = {"group_by": group_by, "groups": rows,
              "totals": {"count": len(opps), "total_amount": round(sum(o["amount"] for o in opps)),
                         "weighted_amount": round(sum(o["amount"] * o["probability"] / 100 for o in opps))}}
    if include_closed:
        won = sum(1 for o in opps if o["stage"] == "Closed Won")
        lost = sum(1 for o in opps if o["stage"] == "Closed Lost")
        result["win_rate"] = round(won / (won + lost), 3) if won + lost else None
    return result


@registry.tool(
    description="""
Search and filter leads (unconverted prospects). Filter by text (name/company/interest), status,
source, minimum score, owner or industry. Sorted by score descending.""",
    properties={
        "query": {"type": "string"},
        "status": {"type": "string", "enum": ["New", "Working", "Qualified", "Unqualified", "Converted"]},
        "source": {"type": "string", "enum": ["Web Form", "Referral", "Trade Show", "Outbound", "Partner", "Webinar"]},
        "min_score": {"type": "integer"},
        "owner": {"type": "string"},
        "industry": {"type": "string"},
        "limit": {"type": "integer", "description": "Max results (default 25)"},
    },
)
def search_leads(ctx: ToolContext, query=None, status=None, source=None, min_score=None, owner=None,
                 industry=None, limit=25):
    q: dict = {}
    if query:
        q["$or"] = [{"full_name": _ci(query)}, {"company": _ci(query)}, {"interest": _ci(query)}]
    if status:
        q["status"] = status
    if source:
        q["source"] = source
    if min_score is not None:
        q["score"] = {"$gte": min_score}
    if owner:
        q["owner"] = _ci(owner)
    if industry:
        q["industry"] = _ci(industry)
    docs = list(ctx.db.leads.find(q).sort("score", -1).limit(limit or 25))
    return {"count": len(docs), "leads": [_pick(d, LEAD_FIELDS) for d in docs]}


@registry.tool(
    description="""
List logged interactions (calls, emails, meetings, demos, support tickets, notes) filtered by account,
contact, opportunity or lead, type, sentiment and recency. Newest first. Use search_knowledge instead
when looking for interactions by topic/meaning (e.g. "who mentioned data residency?").""",
    properties={
        "account": {"type": "string", "description": "Account ID or name"},
        "contact_id": {"type": "string"},
        "opportunity_id": {"type": "string"},
        "lead_id": {"type": "string"},
        "type": {"type": "string", "enum": INTERACTION_TYPES},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "since_days": {"type": "integer", "description": "Only interactions in the last N days"},
        "limit": {"type": "integer", "description": "Max results (default 20)"},
    },
)
def get_interactions(ctx: ToolContext, account=None, contact_id=None, opportunity_id=None, lead_id=None,
                     type=None, sentiment=None, since_days=None, limit=20):  # noqa: A002 - matches schema
    q: dict = {}
    if account:
        q["account_id"] = resolve_account(ctx.db, account)["_id"]
    for key, val in (("contact_id", contact_id), ("opportunity_id", opportunity_id), ("lead_id", lead_id)):
        if val:
            q[key] = val.upper()
    if type:
        q["type"] = type
    if sentiment:
        q["sentiment"] = sentiment
    if since_days is not None:
        q["timestamp"] = {"$gte": _now() - timedelta(days=since_days)}
    docs = [_pick(d, INTERACTION_FIELDS) for d in
            ctx.db.interactions.find(q).sort("timestamp", -1).limit(limit or 20)]
    return {"count": len(docs), "interactions": _with_account_names(ctx.db, docs)}


@registry.tool(
    description="""
List follow-up tasks. Filter by owner, status, account, or show only overdue tasks / tasks due soon.""",
    properties={
        "owner": {"type": "string"},
        "status": {"type": "string", "enum": ["Open", "Completed"]},
        "account": {"type": "string", "description": "Account ID or name"},
        "overdue_only": {"type": "boolean"},
        "due_within_days": {"type": "integer"},
        "limit": {"type": "integer", "description": "Max results (default 25)"},
    },
)
def list_tasks(ctx: ToolContext, owner=None, status="Open", account=None, overdue_only=False,
               due_within_days=None, limit=25):
    q: dict = {}
    if status:
        q["status"] = status
    if owner:
        q["owner"] = _ci(owner)
    if account:
        q["account_id"] = resolve_account(ctx.db, account)["_id"]
    if overdue_only:
        q["due_date"] = {"$lt": _today()}
        q["status"] = "Open"
    elif due_within_days is not None:
        q["due_date"] = {"$lte": _today() + timedelta(days=due_within_days)}
    docs = [_pick(d, TASK_FIELDS) for d in ctx.db.tasks.find(q).sort("due_date", 1).limit(limit or 25)]
    return {"count": len(docs), "tasks": _with_account_names(ctx.db, docs)}


@registry.tool(
    description="""
Semantic/keyword search (RAG) over unstructured text:
- knowledge_base: company documents - product catalog and list prices, pricing & discount approval
  policy, sales playbook (stage definitions, deal hygiene, lead qualification), objection handling,
  support SLAs and renewal policy.
- interactions: the free-text notes of every call, email, meeting, demo and support ticket.
Use it for policy/product/how-to questions and for finding interactions by topic (e.g. "data residency",
"pricing pushback", "champion leaving"). Optionally scope interaction hits to one account or opportunity.
Returns ranked passages with their source IDs - cite them in your answer.""",
    properties={
        "query": {"type": "string", "description": "Natural-language search query"},
        "source": {"type": "string", "enum": ["all", "knowledge_base", "interactions"]},
        "account": {"type": "string", "description": "Account ID or name to scope interaction results"},
        "opportunity_id": {"type": "string"},
        "top_k": {"type": "integer", "description": "Number of passages (default 5, max 15)"},
    },
    required=["query"],
)
def search_knowledge(ctx: ToolContext, query, source="all", account=None, opportunity_id=None, top_k=5):
    account_id = resolve_account(ctx.db, account)["_id"] if account else None
    hits = ctx.retriever.search(query, source=source or "all", account_id=account_id,
                                opportunity_id=opportunity_id.upper() if opportunity_id else None,
                                top_k=min(top_k or 5, 15))
    names = _account_names(ctx.db, [h["metadata"].get("account_id") for h in hits])
    for h in hits:
        aid = h["metadata"].get("account_id")
        if aid in names:
            h["metadata"]["account_name"] = names[aid]
        h["metadata"] = {k: v for k, v in h["metadata"].items() if v is not None}
    return {"query": query, "results": hits}


# ---------------------------------------------------------------------------------------
# write tools (require approval)
# ---------------------------------------------------------------------------------------
@registry.tool(
    description="""
WRITE. Log a new interaction (call, email, meeting, demo, support ticket or note) in the CRM.
Link it to an account and optionally a contact, opportunity or lead. The note becomes searchable
immediately via search_knowledge.""",
    properties={
        "type": {"type": "string", "enum": INTERACTION_TYPES},
        "notes": {"type": "string", "description": "What happened - full free-text notes"},
        "subject": {"type": "string"},
        "account": {"type": "string", "description": "Account ID or name"},
        "contact_id": {"type": "string"},
        "opportunity_id": {"type": "string"},
        "lead_id": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
    },
    required=["type", "notes"],
    mutating=True,
)
def log_interaction(ctx: ToolContext, type, notes, subject=None, account=None, contact_id=None,  # noqa: A002
                    opportunity_id=None, lead_id=None, sentiment="neutral"):
    account_id = resolve_account(ctx.db, account)["_id"] if account else None
    opp = ctx.db.opportunities.find_one({"_id": opportunity_id.upper()}) if opportunity_id else None
    if opportunity_id and not opp:
        raise LookupError(f"opportunity {opportunity_id}")
    if opp and not account_id:
        account_id = opp["account_id"]
    if contact_id and not ctx.db.contacts.find_one({"_id": contact_id.upper()}):
        raise LookupError(f"contact {contact_id}")
    if lead_id and not ctx.db.leads.find_one({"_id": lead_id.upper()}):
        raise LookupError(f"lead {lead_id}")
    if not (account_id or lead_id):
        raise ValueError("an interaction must be linked to an account, opportunity or lead")
    doc = {
        "_id": _next_id(ctx.db.interactions, "INT", 4),
        "type": type,
        "subject": subject or notes.split(".")[0][:90],
        "notes": notes,
        "sentiment": sentiment or "neutral",
        "timestamp": _now(),
        "owner": ctx.user,
        "account_id": account_id,
        "contact_id": contact_id.upper() if contact_id else None,
        "opportunity_id": opp["_id"] if opp else None,
        "lead_id": lead_id.upper() if lead_id else None,
    }
    ctx.db.interactions.insert_one(doc)
    if opp:
        ctx.db.opportunities.update_one({"_id": opp["_id"]}, {"$set": {"updated_at": doc["timestamp"]}})
    ctx.retriever.add_interaction(doc)
    return {"created": _pick(doc, INTERACTION_FIELDS)}


@registry.tool(
    description="""
WRITE. Update fields on an opportunity: stage, amount, close_date (YYYY-MM-DD), next_step, probability,
loss_reason (required when moving to Closed Lost). Changing stage without a probability applies the
playbook default probability for that stage. Returns the before/after values.""",
    properties={
        "opportunity_id": {"type": "string"},
        "stage": {"type": "string", "enum": STAGE_NAMES},
        "amount": {"type": "number"},
        "close_date": {"type": "string", "description": "YYYY-MM-DD"},
        "next_step": {"type": "string"},
        "probability": {"type": "integer"},
        "loss_reason": {"type": "string"},
    },
    required=["opportunity_id"],
    mutating=True,
)
def update_opportunity(ctx: ToolContext, opportunity_id, stage=None, amount=None, close_date=None,
                       next_step=None, probability=None, loss_reason=None):
    opp = ctx.db.opportunities.find_one({"_id": opportunity_id.upper()})
    if not opp:
        raise LookupError(f"opportunity {opportunity_id}")
    changes: dict = {}
    if stage:
        changes["stage"] = stage
        changes["probability"] = STAGE_PROBABILITY[stage]
        if stage.startswith("Closed"):
            changes["next_step"] = None
        if stage == "Closed Lost" and not (loss_reason or opp.get("loss_reason")):
            raise ValueError("loss_reason is required when moving an opportunity to Closed Lost")
    if probability is not None:
        if not 0 <= probability <= 100:
            raise ValueError("probability must be between 0 and 100")
        changes["probability"] = probability
    if amount is not None:
        if amount < 0:
            raise ValueError("amount must be positive")
        if amount < opp["amount"] * 0.9:
            # Price cuts are decisions for the decision model - they can't be made by editing the amount.
            raise ValueError("cutting the amount by more than 10% is a discount; use request_discount so the "
                             "decision model can approve, escalate or reject it")
        changes["amount"] = amount
    if close_date:
        changes["close_date"] = _parse_date(close_date, "close_date")
    if next_step is not None:
        changes["next_step"] = next_step
    if loss_reason:
        changes["loss_reason"] = loss_reason
    if not changes:
        raise ValueError("no fields to update were provided")
    changes["updated_at"] = _now()
    ctx.db.opportunities.update_one({"_id": opp["_id"]}, {"$set": changes})
    before = {k: opp.get(k) for k in changes if k != "updated_at"}
    after = {k: v for k, v in changes.items() if k != "updated_at"}
    return {"opportunity_id": opp["_id"], "name": opp["name"], "before": before, "after": after}


@registry.tool(
    description="""
WRITE. Create a follow-up task (to-do) with a due date (YYYY-MM-DD), optionally linked to an account,
opportunity or lead. Owner defaults to the current user.""",
    properties={
        "subject": {"type": "string"},
        "due_date": {"type": "string", "description": "YYYY-MM-DD"},
        "priority": {"type": "string", "enum": ["High", "Normal", "Low"]},
        "owner": {"type": "string"},
        "account": {"type": "string", "description": "Account ID or name"},
        "opportunity_id": {"type": "string"},
        "lead_id": {"type": "string"},
    },
    required=["subject", "due_date"],
    mutating=True,
)
def create_task(ctx: ToolContext, subject, due_date, priority="Normal", owner=None, account=None,
                opportunity_id=None, lead_id=None):
    account_id = resolve_account(ctx.db, account)["_id"] if account else None
    if opportunity_id:
        opp = ctx.db.opportunities.find_one({"_id": opportunity_id.upper()})
        if not opp:
            raise LookupError(f"opportunity {opportunity_id}")
        account_id = account_id or opp["account_id"]
    doc = {
        "_id": _next_id(ctx.db.tasks, "TASK", 3),
        "subject": subject,
        "due_date": _parse_date(due_date, "due_date"),
        "status": "Open",
        "priority": priority or "Normal",
        "owner": owner or ctx.user,
        "account_id": account_id,
        "opportunity_id": opportunity_id.upper() if opportunity_id else None,
        "lead_id": lead_id.upper() if lead_id else None,
        "created_at": _now(),
    }
    ctx.db.tasks.insert_one(doc)
    return {"created": _pick(doc, TASK_FIELDS)}


@registry.tool(
    description="WRITE. Mark a task as completed.",
    properties={"task_id": {"type": "string"}},
    required=["task_id"],
    mutating=True,
)
def complete_task(ctx: ToolContext, task_id):
    res = ctx.db.tasks.update_one({"_id": task_id.upper()},
                                  {"$set": {"status": "Completed", "completed_at": _now()}})
    if not res.matched_count:
        raise LookupError(f"task {task_id}")
    return {"task_id": task_id.upper(), "status": "Completed"}


@registry.tool(
    description="""
WRITE. Update a lead's status, score or owner (e.g. mark Qualified/Unqualified after a call).
To turn a qualified lead into an account + contact + opportunity use convert_lead instead.""",
    properties={
        "lead_id": {"type": "string"},
        "status": {"type": "string", "enum": ["New", "Working", "Qualified", "Unqualified"]},
        "score": {"type": "integer"},
        "owner": {"type": "string"},
    },
    required=["lead_id"],
    mutating=True,
)
def update_lead(ctx: ToolContext, lead_id, status=None, score=None, owner=None):
    lead = ctx.db.leads.find_one({"_id": lead_id.upper()})
    if not lead:
        raise LookupError(f"lead {lead_id}")
    if lead["status"] == "Converted":
        raise ValueError("lead is already converted")
    changes = {k: v for k, v in (("status", status), ("score", score), ("owner", owner)) if v is not None}
    if not changes:
        raise ValueError("no fields to update were provided")
    ctx.db.leads.update_one({"_id": lead["_id"]}, {"$set": changes})
    return {"lead_id": lead["_id"], "before": {k: lead.get(k) for k in changes}, "after": changes}


@registry.tool(
    description="""
WRITE. Convert a lead into a new Prospect account, a primary contact and a Qualification-stage
opportunity, and mark the lead Converted. Optionally set the products and amount of the opportunity
(defaults to Core Platform at list price).""",
    properties={
        "lead_id": {"type": "string"},
        "products": {"type": "array", "items": {"type": "string", "enum": list(PRODUCTS)}},
        "amount": {"type": "number"},
        "close_date": {"type": "string", "description": "YYYY-MM-DD, default today + 90 days"},
    },
    required=["lead_id"],
    mutating=True,
)
def convert_lead(ctx: ToolContext, lead_id, products=None, amount=None, close_date=None):
    db = ctx.db
    lead = db.leads.find_one({"_id": lead_id.upper()})
    if not lead:
        raise LookupError(f"lead {lead_id}")
    if lead["status"] == "Converted":
        raise ValueError(f"lead already converted to {lead.get('converted_account_id')}")
    if db.accounts.find_one({"name": {"$regex": f"^{re.escape(lead['company'])}$", "$options": "i"}}):
        raise ValueError(f"an account named '{lead['company']}' already exists")
    products = products or ["Core Platform"]
    now = _now()
    emp = lead.get("estimated_employees") or 500
    tier = "Strategic" if emp >= 15000 else "Enterprise" if emp >= 5000 else "Mid-Market" if emp >= 1000 else "SMB"
    account = {
        "_id": _next_id(db.accounts, "ACC", 3), "name": lead["company"], "industry": lead.get("industry"),
        "employees": emp, "tier": tier, "status": "Prospect", "owner": lead["owner"], "region": "NA",
        "health_score": None, "arr": 0, "renewal_date": None, "tags": ["converted-lead"], "created_at": now,
    }
    contact = {
        "_id": _next_id(db.contacts, "CON", 3), "account_id": account["_id"],
        "first_name": lead["first_name"], "last_name": lead["last_name"], "full_name": lead["full_name"],
        "email": lead["email"], "title": lead["title"], "seniority": None, "department": None,
        "is_primary": True, "created_at": now,
    }
    opp = {
        "_id": _next_id(db.opportunities, "OPP", 3), "account_id": account["_id"],
        "name": f"{lead['company']} - New Business - {' + '.join(products)}", "type": "New Business",
        "stage": "Qualification", "probability": STAGE_PROBABILITY["Qualification"],
        "amount": amount if amount is not None else sum(PRODUCTS[p] for p in products),
        "close_date": _parse_date(close_date, "close_date") if close_date else _today() + timedelta(days=90),
        "owner": lead["owner"], "products": products, "primary_contact_id": contact["_id"],
        "competitor": None, "next_step": "Schedule discovery deep-dive", "loss_reason": None,
        "created_at": now, "updated_at": now,
    }
    db.accounts.insert_one(account)
    db.contacts.insert_one(contact)
    db.opportunities.insert_one(opp)
    db.leads.update_one({"_id": lead["_id"]}, {"$set": {"status": "Converted",
                                                        "converted_account_id": account["_id"]}})
    db.interactions.update_many({"lead_id": lead["_id"]}, {"$set": {"account_id": account["_id"]}})
    ctx.retriever.rebuild()  # re-index the lead's interactions under the new account
    return {"account": _pick(account, ACCOUNT_FIELDS), "contact": _pick(contact, CONTACT_FIELDS),
            "opportunity": _pick(opp, OPP_FIELDS)}


# Decision-model tools register themselves on the same registry.
from . import decision_tools  # noqa: E402,F401
