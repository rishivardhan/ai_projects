"""Step 5d - Decision-model tools.

These expose the decision model (``crm_agent/decision``) to the agent. The model,
not the LLM, is the decisive factor:

* ``score_deal`` / ``prioritize_deals`` return the model's win probability, action
  and reasons - the agent is instructed to present these, not invent its own.
* ``request_discount`` is the *only* way to discount a deal, and the model's
  decision is enforced in code: APPROVE applies the discount, ESCALATE files an
  approval task and leaves the deal unchanged, REJECT changes nothing. Every
  decision is written to the ``decisions`` audit collection.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..decision.features import OPEN_STAGES, opportunity_features
from ..decision.model import MODEL_VERSION, get_model
from ..decision.policy import ACTION_BANDS, AUTHORITY, MAX_DISCOUNT, assess_deal, decide_discount
from .crm_tools import _next_id, _now, _with_account_names, registry, resolve_account
from .registry import ToolContext


def _open_opportunity(db, opportunity_id: str) -> dict:
    opp = db.opportunities.find_one({"_id": opportunity_id.upper()})
    if not opp:
        raise LookupError(f"opportunity {opportunity_id}")
    if opp["stage"] not in OPEN_STAGES:
        raise ValueError(f"{opp['_id']} is {opp['stage']}; the decision model only scores open deals")
    return opp


@registry.tool(
    description="""
DECISION MODEL. Score one open deal with the trained win-probability model. Returns the model's
win probability, the recommended action (Accelerate / Intervene / Re-qualify / Deprioritize),
expected value, the factors pushing the probability up or down (with their values), and playbook
actions for the biggest risks. Optionally pass proposed_discount_pct to see its effect.
Use this for any question about a deal's likelihood to close, risk, or what to do next.""",
    properties={
        "opportunity_id": {"type": "string"},
        "proposed_discount_pct": {"type": "number", "description": "e.g. 15 for 15%"},
    },
    required=["opportunity_id"],
)
def score_deal(ctx: ToolContext, opportunity_id, proposed_discount_pct=None):
    opp = _open_opportunity(ctx.db, opportunity_id)
    model = get_model(ctx.db)
    discount = proposed_discount_pct / 100 if proposed_discount_pct is not None else None
    features = opportunity_features(ctx.db, opp, discount=discount)
    result = assess_deal(model, features, opp["amount"])
    return {
        "opportunity_id": opp["_id"], "name": opp["name"], "stage": opp["stage"], "amount": opp["amount"],
        "crm_stage_probability": opp["probability"],
        "model": {"version": MODEL_VERSION, "holdout_auc": model.card["holdout_auc"]},
        **result,
        "note": "impact = contribution to the log-odds of winning versus an average past deal",
    }


@registry.tool(
    description="""
DECISION MODEL. Score every open deal (optionally for one owner or account) and rank them.
sort_by: expected_value (where the money most likely is), value_at_risk (big deals the model
thinks may slip) or win_probability. For "what should I focus on", filter action=Intervene and sort by
value_at_risk: those deals are winnable, so effort there pays most. Returns each deal's
win probability and recommended action plus a count per action. Use for "what should I focus
on", "which deals are at risk", forecast and pipeline-quality questions.""",
    properties={
        "owner": {"type": "string"},
        "account": {"type": "string", "description": "Account ID or name"},
        "action": {"type": "string", "enum": [a for _, a, _ in ACTION_BANDS]},
        "sort_by": {"type": "string", "enum": ["expected_value", "value_at_risk", "win_probability"]},
        "limit": {"type": "integer", "description": "Max deals returned (default 15)"},
    },
)
def prioritize_deals(ctx: ToolContext, owner=None, account=None, action=None, sort_by="value_at_risk",
                     limit=15):
    model = get_model(ctx.db)
    q: dict = {"stage": {"$in": OPEN_STAGES}}
    if owner:
        q["owner"] = {"$regex": owner, "$options": "i"}
    if account:
        q["account_id"] = resolve_account(ctx.db, account)["_id"]
    rows = []
    for opp in ctx.db.opportunities.find(q):
        a = assess_deal(model, opportunity_features(ctx.db, opp), opp["amount"])
        rows.append({"opportunity_id": opp["_id"], "account_id": opp["account_id"], "name": opp["name"],
                     "stage": opp["stage"], "owner": opp["owner"], "amount": opp["amount"],
                     "win_probability": a["win_probability"], "action": a["action"],
                     "expected_value": a["expected_value"], "value_at_risk": a["value_at_risk"],
                     "top_risk": next((f["factor"] + ": " + f["value"] for f in a["top_factors"]
                                       if f["direction"] == "hurts"), None)})
    summary: dict = {}
    for r in rows:
        s = summary.setdefault(r["action"], {"deals": 0, "amount": 0, "expected_value": 0})
        s["deals"] += 1
        s["amount"] += r["amount"]
        s["expected_value"] += r["expected_value"]
    if action:
        rows = [r for r in rows if r["action"] == action]
    rows.sort(key=lambda r: r[sort_by or "value_at_risk"], reverse=True)
    return {"model_forecast": {"open_deals": sum(s["deals"] for s in summary.values()),
                               "expected_value": sum(s["expected_value"] for s in summary.values())},
            "by_action": summary, "deals": _with_account_names(ctx.db, rows[: limit or 15])}


@registry.tool(
    description="""
DECISION MODEL. Show the decision model's model card: what it is, how it was trained, how
accurate it is on held-out deals, its learned weights, the action thresholds and the discount
authority rules. Use when the user asks how decisions are made or how much to trust them.""",
)
def decision_model_info(ctx: ToolContext):
    model = get_model(ctx.db)
    return {
        "model_card": model.card,
        "action_bands": [{"min_win_probability": f, "action": a, "meaning": m} for f, a, m in ACTION_BANDS],
        "discount_authority": [{"up_to": f"{lim:.0%}", "approver": who} for lim, who in AUTHORITY]
        + [{"above": f"{MAX_DISCOUNT:.0%}", "approver": "not permitted (CRO strategic exception only)"}],
        "recent_decisions": list(ctx.db.decisions.find({}, {"inputs": 0}).sort("timestamp", -1).limit(5)),
    }


@registry.tool(
    description="""
WRITE + DECISION MODEL. Request a discount on an open deal. The decision model makes the call and
the outcome is enforced - you cannot override it:
- APPROVE: within account-executive authority and it raises expected revenue -> discount applied.
- ESCALATE: worth doing but above rep authority -> an approval task is created for the right
  approver; the deal is NOT changed yet.
- REJECT: lowers expected revenue, the deal is too unlikely for price to matter, or it exceeds
  the 30% maximum -> nothing changes; a counter-offer may be suggested.
This is the only way to discount a deal.""",
    properties={
        "opportunity_id": {"type": "string"},
        "discount_pct": {"type": "number", "description": "Requested discount off list price, e.g. 25"},
        "justification": {"type": "string", "description": "Why the customer/rep wants it"},
    },
    required=["opportunity_id", "discount_pct"],
    mutating=True,
)
def request_discount(ctx: ToolContext, opportunity_id, discount_pct, justification=None):
    db = ctx.db
    if not 0 < discount_pct < 100:
        raise ValueError("discount_pct must be between 0 and 100")
    opp = _open_opportunity(db, opportunity_id)
    model = get_model(db)
    list_amount = opp.get("list_amount") or opp["amount"]
    d = discount_pct / 100
    features = opportunity_features(db, dict(opp, list_amount=list_amount), discount=0.0)
    decision = decide_discount(model, features, list_amount, d)

    now = _now()
    record = {
        "_id": _next_id(db.decisions, "DEC", 4), "type": "discount", "timestamp": now,
        "opportunity_id": opp["_id"], "account_id": opp["account_id"], "requested_by": ctx.user,
        "model_version": MODEL_VERSION, "justification": justification,
        "inputs": features, "decision": decision["decision"], "approver": decision["approver"],
        "reason": decision["reason"], "analysis": {k: v for k, v in decision.items()
                                                   if k not in ("decision", "approver", "reason")},
    }
    effect: dict
    if decision["decision"] == "APPROVE":
        net = round(list_amount * (1 - d))
        db.opportunities.update_one({"_id": opp["_id"]}, {"$set": {
            "list_amount": list_amount, "discount_pct": discount_pct, "amount": net, "updated_at": now,
            "discount_decision_id": record["_id"]}})
        effect = {"applied": True, "list_amount": list_amount, "new_amount": net}
    elif decision["decision"] == "ESCALATE":
        task = {
            "_id": _next_id(db.tasks, "TASK", 3),
            "subject": f"Approve {discount_pct:g}% discount on {opp['_id']} ({decision['approver']}) - {record['_id']}",
            "due_date": (now + timedelta(days=2)).replace(hour=0, minute=0, second=0),
            "status": "Open", "priority": "High", "owner": decision["approver"],
            "account_id": opp["account_id"], "opportunity_id": opp["_id"], "lead_id": None, "created_at": now,
        }
        db.tasks.insert_one(task)
        db.opportunities.update_one({"_id": opp["_id"]}, {"$set": {"pending_discount": {
            "discount_pct": discount_pct, "decision_id": record["_id"], "approver": decision["approver"]}}})
        effect = {"applied": False, "approval_task": task["_id"], "awaiting": decision["approver"]}
    else:
        effect = {"applied": False}
    record["effect"] = effect
    db.decisions.insert_one(record)
    return {"decision_id": record["_id"], "opportunity_id": opp["_id"], **decision, "effect": effect,
            "decided_at": datetime.isoformat(now)}
