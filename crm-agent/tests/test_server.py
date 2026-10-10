from crm_agent import server
from fastapi.testclient import TestClient


def test_dashboard_and_tools(db):
    client = TestClient(server.app)
    d = client.get("/api/dashboard").json()
    assert d["counts"]["accounts"] == 25 and d["open_pipeline"]["count"] > 0
    assert any(t["mutating"] for t in client.get("/api/tools").json())
    r = client.post("/api/tools/search_accounts", json={"tier": "Strategic"}).json()
    assert not r["is_error"] and r["output"]["count"] > 0
    r = client.post("/api/tools/create_task", json={"subject": "x", "due_date": "2030-01-01"}).json()
    assert r["is_error"]  # writes are declined unless allow_writes=true
    assert client.get("/").status_code == 200
