"""Decision model - the decision policy.

Turns the model's win probability into decisions the application acts on:

1. **Deal action** - Accelerate / Intervene / Re-qualify / Deprioritize, plus the
   playbook remedies for the factors hurting the deal most.
2. **Discount decision** - APPROVE / ESCALATE / REJECT. It combines two things:
   * the *economics*: does the discount raise expected revenue
     (win probability x net amount), given the model's estimate of how much a
     discount lifts the win probability for *this* deal?
   * the *authority* rules from the Pricing and Discount Approval Policy
     (<=10% rep, <=20% Regional Sales Director, <=30% VP Sales + Deal Desk, >30% not allowed).
   It also computes the counter-offer that maximizes expected revenue, and refuses to
   discount deals whose win probability is too low for price to be the problem.

All thresholds live here as constants, so the policy is easy to review and change.
"""
from __future__ import annotations

from .features import BY_NAME
from .model import WinModel

# Win-probability bands -> recommended action
ACTION_BANDS = [  # (minimum probability, action, meaning)
    (0.65, "Accelerate", "Likely to win - focus on closing steps and protect the timeline."),
    (0.40, "Intervene", "Winnable but at risk - act on the top risk factors now."),
    (0.20, "Re-qualify", "Unlikely as it stands - re-validate pain, budget and decision process."),
    (0.00, "Deprioritize", "Low odds - minimize effort or move to nurture."),
]

# Discount authority (from rag/knowledge/pricing_and_discount_policy.md)
AUTHORITY = [  # (max discount, approver)
    (0.10, "Account Executive"),
    (0.20, "Regional Sales Director"),
    (0.30, "VP of Sales + Deal Desk"),
]
MAX_DISCOUNT = 0.30
MIN_WIN_PROBABILITY_FOR_DISCOUNT = 0.20  # below this a discount won't rescue the deal - fix it first
DISCOUNT_GRID = [round(i * 0.025, 3) for i in range(int(MAX_DISCOUNT / 0.025) + 1)]  # 0%, 2.5% ... 30%


def deal_action(probability: float) -> dict:
    for floor, action, meaning in ACTION_BANDS:
        if probability >= floor:
            return {"action": action, "meaning": meaning}
    raise AssertionError("unreachable")


def assess_deal(model: WinModel, features: dict, amount: float) -> dict:
    p = model.predict(features)
    factors = model.explain(features)
    remedies = [BY_NAME[f["feature"]].remedy for f in factors
                if f["direction"] == "hurts" and f["impact"] <= -0.15 and BY_NAME[f["feature"]].remedy][:3]
    return {
        "win_probability": round(p, 3),
        **deal_action(p),
        "expected_value": round(p * amount),
        "value_at_risk": round((1 - p) * amount),
        "top_factors": factors[:5],
        "recommended_actions": remedies,
    }


def approver_for(discount: float) -> str | None:
    for limit, approver in AUTHORITY:
        if discount <= limit + 1e-9:
            return approver
    return None


def decide_discount(model: WinModel, features: dict, list_amount: float, discount: float) -> dict:
    """Decide on a requested discount (fraction, e.g. 0.25) for one deal."""
    def ev(d: float) -> tuple[float, float]:
        p = model.predict(dict(features, discount=d))
        return p, p * list_amount * (1 - d)

    p0, ev0 = ev(0.0)
    p1, ev1 = ev(discount)
    best_d, (best_p, best_ev) = max(((d, ev(d)) for d in DISCOUNT_GRID), key=lambda x: x[1][1])
    analysis = {
        "requested_discount": discount,
        "win_probability_without_discount": round(p0, 3),
        "win_probability_with_discount": round(p1, 3),
        "expected_revenue_without_discount": round(ev0),
        "expected_revenue_with_discount": round(ev1),
        "best_discount_for_expected_revenue": best_d,
        "expected_revenue_at_best_discount": round(best_ev),
    }

    if discount > MAX_DISCOUNT + 1e-9:
        decision, approver = "REJECT", None
        reason = (f"{discount:.0%} exceeds the {MAX_DISCOUNT:.0%} policy maximum (only a CRO-approved "
                  "strategic exception can go higher).")
    elif discount > 0 and p0 < MIN_WIN_PROBABILITY_FOR_DISCOUNT:
        decision, approver = "REJECT", None
        reason = (f"Win probability is only {p0:.0%} before any discount (threshold "
                  f"{MIN_WIN_PROBABILITY_FOR_DISCOUNT:.0%}). Price is not what is holding this deal back - "
                  "fix the top risk factors first, then revisit pricing.")
    elif discount > 0 and ev1 <= ev0:
        decision, approver = "REJECT", None
        reason = (f"The discount lifts win probability only from {p0:.0%} to {p1:.0%}, so expected revenue "
                  f"falls from ${ev0:,.0f} to ${ev1:,.0f}. Use non-price levers (multi-year terms, phased "
                  "scope, a pilot with success criteria) instead.")
    else:
        approver = approver_for(discount)
        decision = "APPROVE" if approver == "Account Executive" else "ESCALATE"
        reason = (f"Expected revenue rises from ${ev0:,.0f} to ${ev1:,.0f} (win probability {p0:.0%} -> {p1:.0%}). "
                  + ("Within account-executive authority." if decision == "APPROVE"
                     else f"Above rep authority - requires {approver} approval."))

    counter = None
    if p0 >= MIN_WIN_PROBABILITY_FOR_DISCOUNT and best_d != discount and best_ev > max(ev1, ev0) * 1.005:
        counter = {"discount": best_d, "approver": approver_for(best_d) if best_d else None,
                   "expected_revenue": round(best_ev), "win_probability": round(best_p, 3)}
    return {"decision": decision, "approver": approver, "reason": reason, "counter_offer": counter, **analysis}
