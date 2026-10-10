from crm_agent.seed import generate


def test_generate_is_deterministic_and_consistent():
    a, b = generate(), generate()
    assert [d["_id"] for d in a["opportunities"]] == [d["_id"] for d in b["opportunities"]]
    account_ids = {x["_id"] for x in a["accounts"]}
    contact_ids = {x["_id"] for x in a["contacts"]}
    assert len(a["accounts"]) == 25 and len(a["leads"]) == 30
    for c in a["contacts"]:
        assert c["account_id"] in account_ids
    for o in a["opportunities"]:
        assert o["account_id"] in account_ids and o["primary_contact_id"] in contact_ids
    for i in a["interactions"]:
        assert i["account_id"] in account_ids or i["lead_id"]
    assert any(x["status"] == "Churned" for x in a["accounts"])


def test_seeded_database_counts(db):
    assert db.accounts.count_documents({}) == 25
    assert db.contacts.count_documents({}) > 50
    assert db.interactions.count_documents({}) > 100
