from crm_agent.tools.crm_tools import registry


def run(ctx, name, **args):
    result = registry.execute(ctx, "t1", name, args)
    return result


def test_schemas_are_valid_tool_definitions():
    for schema in registry.schemas():
        assert set(schema) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"
        for req in schema["input_schema"]["required"]:
            assert req in schema["input_schema"]["properties"]


def test_search_accounts_and_360(ctx):
    r = run(ctx, "search_accounts", industry="financial")
    assert not r.is_error and r.output["count"] >= 2
    r = run(ctx, "get_account_360", account="globex")
    assert not r.is_error
    out = r.output
    assert out["account"]["name"] == "Globex Financial"
    assert out["contacts"] and "open_pipeline" in out


def test_ambiguous_and_missing_account_are_errors(ctx):
    assert run(ctx, "get_account_360", account="zzz-nope").is_error
    r = run(ctx, "get_account_360", account="a")  # matches many
    assert r.is_error and "ambiguous" in r.output


def test_validation_errors(ctx):
    assert "missing required" in run(ctx, "get_opportunity").output
    assert "unknown field" in run(ctx, "search_accounts", colour="red").output
    assert "must be one of" in run(ctx, "search_accounts", tier="Huge").output
    assert run(ctx, "no_such_tool").is_error


def test_pipeline_summary_totals_match(ctx, db):
    out = run(ctx, "pipeline_summary", group_by="stage").output
    open_total = sum(o["amount"] for o in db.opportunities.find(
        {"stage": {"$in": ["Prospecting", "Qualification", "Proposal", "Negotiation"]}}))
    assert out["totals"]["total_amount"] == open_total
    assert sum(g["total_amount"] for g in out["groups"]) == open_total
    assert run(ctx, "pipeline_summary", group_by="owner", include_closed=True).output["win_rate"] is not None


def test_opportunity_filters(ctx):
    out = run(ctx, "list_opportunities", open_only=True, sort_by="amount").output
    amounts = [o["amount"] for o in out["opportunities"]]
    assert amounts == sorted(amounts, reverse=True)
    stalled = run(ctx, "list_opportunities", stalled_days=21).output
    assert all(o["stage"] not in ("Closed Won", "Closed Lost") for o in stalled["opportunities"])


def test_search_knowledge_tool(ctx):
    out = run(ctx, "search_knowledge", query="Premium Support response time severity 1").output
    assert out["results"]


def test_write_requires_approval(ctx, db):
    ctx.approve = lambda name, args: False
    r = run(ctx, "create_task", subject="Call back", due_date="2030-01-01")
    assert r.is_error and "declined" in r.output
    assert db.tasks.count_documents({"subject": "Call back"}) == 0


def test_log_interaction_is_searchable(ctx, db):
    opp = db.opportunities.find_one({"stage": "Negotiation"})
    r = run(ctx, "log_interaction", type="Call", opportunity_id=opp["_id"],
            notes="Customer asked about quantum flux capacitor integration timelines.")
    assert not r.is_error
    assert r.output["created"]["account_id"] == opp["account_id"]
    hits = ctx.retriever.search("quantum flux capacitor", source="interactions")
    assert hits[0]["id"] == r.output["created"]["_id"]


def test_update_opportunity(ctx, db):
    opp = db.opportunities.find_one({"stage": "Proposal"})
    r = run(ctx, "update_opportunity", opportunity_id=opp["_id"], stage="Negotiation", close_date="2031-03-31")
    assert not r.is_error and r.output["after"]["probability"] == 75
    assert db.opportunities.find_one({"_id": opp["_id"]})["stage"] == "Negotiation"
    r = run(ctx, "update_opportunity", opportunity_id=opp["_id"], stage="Closed Lost")
    assert r.is_error and "loss_reason" in r.output
    assert run(ctx, "update_opportunity", opportunity_id=opp["_id"], close_date="31/03/2031").is_error


def test_convert_lead(ctx, db):
    lead = db.leads.find_one({"status": "Qualified"})
    r = run(ctx, "convert_lead", lead_id=lead["_id"], products=["Core Platform", "AI Assist"])
    assert not r.is_error
    acc_id = r.output["account"]["_id"]
    assert db.accounts.find_one({"_id": acc_id})["name"] == lead["company"]
    assert db.opportunities.find_one({"account_id": acc_id})["amount"] == 72000
    assert db.leads.find_one({"_id": lead["_id"]})["status"] == "Converted"
    assert run(ctx, "convert_lead", lead_id=lead["_id"]).is_error  # idempotency guard


def test_tasks_lifecycle(ctx, db):
    created = run(ctx, "create_task", subject="Send SOC2 report", due_date="2030-05-01", account="Acme").output
    tid = created["created"]["_id"]
    assert created["created"]["account_id"] == "ACC-001"
    assert not run(ctx, "complete_task", task_id=tid).is_error
    assert db.tasks.find_one({"_id": tid})["status"] == "Completed"
