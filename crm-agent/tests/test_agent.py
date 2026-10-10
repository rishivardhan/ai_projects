"""Exercises the full agent loop with a scripted stand-in for the Claude API."""
from types import SimpleNamespace as NS

import pytest
from crm_agent.agent import CRMAgent
from crm_agent.config import Settings


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def response(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks), stop_details=None,
              usage=NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0))


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **req):
        # snapshot the message list as it was sent
        self.requests.append(dict(req, messages=list(req["messages"])))
        return self.script.pop(0)


@pytest.fixture()
def settings():
    return Settings(mongo_uri=None, model="claude-opus-5-5", effort="medium", fallbacks=True,
                    max_tokens=16000, max_agent_steps=5)


def test_tool_loop_round_trip(ctx, settings):
    client = FakeClient([
        response("tool_use", NS(type="thinking", thinking="Need pipeline and policy."),
                 tool_use("tu_1", "pipeline_summary", group_by="stage"),
                 tool_use("tu_2", "search_knowledge", query="discount approval")),
        response("end_turn", text("Your open pipeline is healthy.")),
    ])
    agent = CRMAgent(ctx, client=client, settings=settings)
    events = list(agent.chat("How is my pipeline?"))
    kinds = [e.type for e in events]
    assert kinds.count("tool_call") == 2 and kinds.count("tool_result") == 2
    assert events[-1].type == "done" and events[-1].data["text"] == "Your open pipeline is healthy."

    first, second = client.requests
    assert first["model"] == "claude-opus-5-5"
    assert first["thinking"]["type"] == "adaptive" and first["output_config"] == {"effort": "medium"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert {t["name"] for t in first["tools"]} >= {"get_account_360", "search_knowledge", "update_opportunity"}
    # both tool results returned together in one user message, matching ids
    results = second["messages"][-1]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["tu_1", "tu_2"]
    assert not any(b.get("is_error") for b in results["content"])


def test_bad_tool_input_is_reported_back_not_raised(ctx, settings):
    client = FakeClient([
        response("tool_use", tool_use("tu_1", "get_account_360", acct="Globex")),
        response("end_turn", text("Retried.")),
    ])
    agent = CRMAgent(ctx, client=client, settings=settings)
    list(agent.chat("Globex?"))
    block = client.requests[1]["messages"][-1]["content"][0]
    assert block["is_error"] and "missing required" in block["content"]


def test_declined_write_keeps_data_unchanged(ctx, db, settings):
    ctx.approve = lambda name, args: False
    opp = db.opportunities.find_one({"stage": "Proposal"})
    client = FakeClient([
        response("tool_use", tool_use("tu_1", "update_opportunity", opportunity_id=opp["_id"], stage="Closed Won")),
        response("end_turn", text("OK, I did not change it.")),
    ])
    list(CRMAgent(ctx, client=client, settings=settings).chat("close it"))
    assert db.opportunities.find_one({"_id": opp["_id"]})["stage"] == "Proposal"


def test_refusal_rolls_back_turn(ctx, settings):
    client = FakeClient([response("refusal")])
    agent = CRMAgent(ctx, client=client, settings=settings)
    events = list(agent.chat("something"))
    assert events[0].type == "error" and agent.messages == []


def test_step_limit(ctx, settings):
    loop = [response("tool_use", tool_use(f"tu_{i}", "list_tasks")) for i in range(settings.max_agent_steps)]
    agent = CRMAgent(ctx, client=FakeClient(loop), settings=settings)
    events = list(agent.chat("loop forever"))
    assert any(e.type == "notice" for e in events)
    assert agent.messages[-1]["role"] == "assistant"


def test_multi_turn_history_is_append_only(ctx, settings):
    client = FakeClient([response("end_turn", text("Hi")), response("end_turn", text("Again"))])
    agent = CRMAgent(ctx, client=client, settings=settings)
    agent.ask("hello")
    agent.ask("and again")
    assert [m["role"] for m in client.requests[1]["messages"]] == ["user", "assistant", "user"]
