import pytest
from crm_agent.decision.features import FEATURE_NAMES, opportunity_features
from crm_agent.decision.model import WinModel, get_model
from crm_agent.decision.policy import approver_for, deal_action, decide_discount
from crm_agent.seed import _TRUE_WEIGHTS, generate_deal_history
from crm_agent.tools.crm_tools import registry

OPEN = ["Prospecting", "Qualification", "Proposal", "Negotiation"]


def run(ctx, name, **args):
    return registry.execute(ctx, "t", name, args)


def test_model_learns_the_signal():
    model = WinModel()
    card = model.train(generate_deal_history())
    assert card["holdout_auc"] > 0.72
    assert card["holdout_accuracy"] > card["baseline_accuracy"]
    # every strong ground-truth driver is learned with the right sign
    for name, true_w in _TRUE_WEIGHTS.items():
        if abs(true_w) >= 0.8:
            assert (card["weights"][name] > 0) == (true_w > 0), name


def test_explanations_cover_every_feature(ctx, db):
    model = get_model(db)
    opp = db.opportunities.find_one({"stage": "Negotiation"})
    factors = model.explain(opportunity_features(db, opp))
    assert {f["feature"] for f in factors} == set(FEATURE_NAMES)
    assert abs(factors[0]["impact"]) >= abs(factors[-1]["impact"])


def test_policy_rules():
    assert deal_action(0.9)["action"] == "Accelerate"
    assert deal_action(0.5)["action"] == "Intervene"
    assert deal_action(0.3)["action"] == "Re-qualify"
    assert deal_action(0.05)["action"] == "Deprioritize"
    assert approver_for(0.10) == "Account Executive"
    assert approver_for(0.15) == "Regional Sales Director"
    assert approver_for(0.25) == "VP of Sales + Deal Desk"
    assert approver_for(0.35) is None


def test_discount_economics(db):
    model = get_model(db)
    base = {f: 0.0 for f in FEATURE_NAMES} | {"health": 0.5, "stage_progress": 1.0, "log_size": 0.0}
    strong = dict(base, exec_engaged=1)
    weak = dict(base, stage_progress=2 / 3, competitor=1, days_since_touch=1.0)
    assert model.predict(strong) > model.predict(weak)
    assert decide_discount(model, strong, 100000, 0.25)["decision"] == "REJECT"  # likely win: don't give money away
    assert decide_discount(model, weak, 100000, 0.40)["decision"] == "REJECT"  # above policy max
    hopeless = dict(base, stage_progress=0.0, champion_risk=1, negative_ratio=0.8, days_since_touch=3.0)
    out = decide_discount(model, hopeless, 100000, 0.05)
    assert out["decision"] == "REJECT" and out["counter_offer"] is None


def test_score_and_prioritize_tools(ctx, db):
    opp = db.opportunities.find_one({"stage": "Proposal"})
    out = run(ctx, "score_deal", opportunity_id=opp["_id"]).output
    assert 0 < out["win_probability"] < 1 and out["action"] and out["top_factors"]
    closed = db.opportunities.find_one({"stage": "Closed Won"})
    assert run(ctx, "score_deal", opportunity_id=closed["_id"]).is_error
    ranked = run(ctx, "prioritize_deals", sort_by="value_at_risk", limit=50).output
    risks = [d["value_at_risk"] for d in ranked["deals"]]
    assert risks == sorted(risks, reverse=True)
    assert ranked["model_forecast"]["open_deals"] == db.opportunities.count_documents({"stage": {"$in": OPEN}})
    assert run(ctx, "decision_model_info").output["model_card"]["training_deals"] == 600


def _find(ctx, db, wanted, pct):
    model = get_model(db)
    for opp in db.opportunities.find({"stage": {"$in": OPEN}}):
        d = decide_discount(model, opportunity_features(db, opp, discount=0.0), opp["amount"], pct / 100)
        if d["decision"] == wanted:
            return opp
    pytest.skip(f"no deal in the seed data yields {wanted} at {pct}%")


def test_request_discount_is_enforced(ctx, db):
    # APPROVE -> applied
    opp = _find(ctx, db, "APPROVE", 5)
    out = run(ctx, "request_discount", opportunity_id=opp["_id"], discount_pct=5).output
    assert out["decision"] == "APPROVE" and out["effect"]["applied"]
    after = db.opportunities.find_one({"_id": opp["_id"]})
    assert after["amount"] == round(opp["amount"] * 0.95) and after["list_amount"] == opp["amount"]

    # ESCALATE -> approval task, deal unchanged
    opp = _find(ctx, db, "ESCALATE", 15)
    out = run(ctx, "request_discount", opportunity_id=opp["_id"], discount_pct=15).output
    assert out["decision"] == "ESCALATE" and not out["effect"]["applied"]
    assert db.opportunities.find_one({"_id": opp["_id"]})["amount"] == opp["amount"]
    assert db.tasks.find_one({"_id": out["effect"]["approval_task"]})["owner"] == "Regional Sales Director"

    # REJECT -> nothing changes
    opp = _find(ctx, db, "REJECT", 25)
    out = run(ctx, "request_discount", opportunity_id=opp["_id"], discount_pct=25).output
    assert out["decision"] == "REJECT"
    assert db.opportunities.find_one({"_id": opp["_id"]})["amount"] == opp["amount"]

    # every decision is audited
    assert db.decisions.count_documents({}) == 3


def test_discount_cannot_bypass_the_model(ctx, db):
    opp = db.opportunities.find_one({"stage": "Negotiation"})
    r = run(ctx, "update_opportunity", opportunity_id=opp["_id"], amount=opp["amount"] * 0.7)
    assert r.is_error and "request_discount" in r.output
    assert not run(ctx, "update_opportunity", opportunity_id=opp["_id"], amount=opp["amount"] * 0.95).is_error
