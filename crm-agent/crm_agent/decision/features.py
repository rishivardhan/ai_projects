"""Decision model - features.

Turns a live opportunity (plus its account and interaction history in the NoSQL
DB) into the same numeric feature vector that past deals in ``deal_history`` are
stored with. Each feature carries a human-readable label, a formatter for its
value, and the playbook action to take when it is hurting the deal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

OPEN_STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation"]
SENIOR = {"C-Level", "VP"}
RISK_PHRASES = ("leaving the company", "on hold", "lost budget")


@dataclass(frozen=True)
class Feature:
    name: str
    label: str
    show: Callable[[float], str]
    remedy: str  # playbook action when this feature pulls the win probability down


FEATURES = [
    Feature("stage_progress", "Sales stage", lambda v: OPEN_STAGES[round(v * 3)],
            "Complete MEDDICC qualification and get the deal to Proposal."),
    Feature("health", "Account health", lambda v: f"{v * 100:.0f}/100",
            "Engage Customer Success on a success plan before pushing the expansion."),
    Feature("is_customer", "Existing customer", lambda v: "yes" if v else "no", ""),
    Feature("days_since_touch", "Last touchpoint", lambda v: f"{v * 30:.0f} days ago",
            "Re-engage this week: deals with no contact for 21+ days count as stalled."),
    Feature("negative_ratio", "Negative interactions (90d)", lambda v: f"{v:.0%}",
            "Resolve the open concerns and tickets behind the negative sentiment first."),
    Feature("competitor", "Competitor involved", lambda v: "yes" if v else "no",
            "Run the competitive play: lead with TCO, get the competing quote in writing."),
    Feature("past_due", "Close date passed", lambda v: "yes" if v else "no",
            "Fix deal hygiene: set a realistic close date within 2 business days."),
    Feature("discount", "Discount", lambda v: f"{v:.0%}", ""),
    Feature("log_size", "Deal size", lambda v: f"${50000 * math.exp(v):,.0f}",
            "Consider a phased scope to lower the size of the first commitment."),
    Feature("exec_engaged", "Executive engaged (90d)", lambda v: "yes" if v else "no",
            "Book an executive sponsor meeting with a VP or C-level buyer."),
    Feature("champion_risk", "Champion / project risk signal", lambda v: "yes" if v else "no",
            "Find a new VP-level sponsor and ask the champion for an introduction."),
]
FEATURE_NAMES = [f.name for f in FEATURES]
BY_NAME = {f.name: f for f in FEATURES}


def opportunity_features(db, opp: dict, discount: float | None = None, now: datetime | None = None) -> dict:
    """Feature vector for an open opportunity. ``discount`` overrides the one on record."""
    if opp["stage"] not in OPEN_STAGES:
        raise ValueError(f"{opp['_id']} is {opp['stage']}; only open deals can be scored")
    now = now or datetime.now()
    account = db.accounts.find_one({"_id": opp["account_id"]}) or {}
    since = now - timedelta(days=90)

    touches = list(db.interactions.find(
        {"$or": [{"opportunity_id": opp["_id"]}, {"account_id": opp["account_id"]}]}, {"timestamp": 1})
        .sort("timestamp", -1).limit(1))
    days_since = (now - touches[0]["timestamp"]).days if touches else 90

    recent = list(db.interactions.find({"account_id": opp["account_id"], "timestamp": {"$gte": since}}))
    negative = sum(1 for i in recent if i.get("sentiment") == "negative")
    contact_ids = {i.get("contact_id") for i in recent if i.get("contact_id")}
    senior = db.contacts.count_documents({"_id": {"$in": list(contact_ids)}, "seniority": {"$in": list(SENIOR)}})
    risk = any(p in (i.get("notes") or "").lower() for i in recent for p in RISK_PHRASES)

    health = account.get("health_score")
    return {
        "stage_progress": OPEN_STAGES.index(opp["stage"]) / 3,
        "health": health / 100 if health is not None else 0.5,
        "is_customer": 1 if account.get("status") == "Customer" else 0,
        "days_since_touch": min(3.0, days_since / 30),
        "negative_ratio": negative / len(recent) if recent else 0.0,
        "competitor": 1 if opp.get("competitor") else 0,
        "past_due": 1 if opp["close_date"] < now.replace(hour=0, minute=0, second=0, microsecond=0) else 0,
        "discount": opp.get("discount_pct", 0) / 100 if discount is None else discount,
        "log_size": math.log(max(opp.get("list_amount") or opp["amount"], 1000) / 50000),
        "exec_engaged": 1 if senior else 0,
        "champion_risk": 1 if risk else 0,
    }
