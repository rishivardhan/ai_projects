"""Step 7b - Web API + UI.

    python -m crm_agent.server            # http://localhost:8000

Endpoints
    GET  /                      chat UI with a live CRM dashboard
    GET  /api/health            backend + model info
    GET  /api/dashboard         pipeline KPIs for the sidebar
    GET  /api/records/{coll}    browse raw documents
    GET  /api/tools             tool catalog (name, description, schema, write flag)
    POST /api/tools/{name}      call a tool directly (no LLM)
    POST /api/chat              run an agent turn; streams AgentEvents as Server-Sent Events
    POST /api/reset             clear a chat session
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import db as dbmod
from .agent import CRMAgent, build_context
from .config import settings
from .tools.crm_tools import OPEN_STAGES, pipeline_summary, registry
from .tools.registry import to_json

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="CRM Copilot")


class Session:
    def __init__(self, user: str):
        self.allow_writes = False
        self.lock = threading.Lock()
        ctx = build_context(user=user, approve=lambda name, args: self.allow_writes)
        self.agent = CRMAgent(ctx)


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def _session(session_id: str | None, user: str) -> tuple[str, Session]:
    with _sessions_lock:
        if not session_id or session_id not in _sessions:
            session_id = session_id or uuid.uuid4().hex
            _sessions[session_id] = Session(user)
        return session_id, _sessions[session_id]


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user: str = "Priya Shah"
    allow_writes: bool = False


class ResetRequest(BaseModel):
    session_id: str


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"database": dbmod.backend_name(), "model": settings.model, "effort": settings.effort,
            "api_key_configured": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
            "tools": len(list(registry))}


@app.get("/api/dashboard")
def dashboard():
    db = dbmod.get_db()
    ctx = build_context()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    by_stage = pipeline_summary(ctx, group_by="stage", include_closed=True)
    closing = list(db.opportunities.find({"stage": {"$in": OPEN_STAGES},
                                          "close_date": {"$gte": today, "$lte": today + timedelta(days=30)}})
                   .sort("amount", -1).limit(6))
    names = {a["_id"]: a["name"] for a in db.accounts.find({}, {"name": 1})}
    at_risk = list(db.accounts.find({"status": "Customer", "health_score": {"$lt": 60}}).sort("health_score", 1))
    return {
        "counts": {c: db[c].count_documents({}) for c in dbmod.COLLECTIONS},
        "open_pipeline": pipeline_summary(ctx, group_by="stage")["totals"],
        "win_rate": by_stage.get("win_rate"),
        "by_stage": by_stage["groups"],
        "closing_30d": [{"id": o["_id"], "account": names.get(o["account_id"]), "stage": o["stage"],
                         "amount": o["amount"], "close_date": o["close_date"].date().isoformat()} for o in closing],
        "at_risk_customers": [{"id": a["_id"], "name": a["name"], "health_score": a["health_score"],
                               "arr": a.get("arr")} for a in at_risk],
        "overdue_tasks": db.tasks.count_documents({"status": "Open", "due_date": {"$lt": today}}),
    }


@app.get("/api/records/{collection}")
def records(collection: str, limit: int = 50):
    if collection not in dbmod.COLLECTIONS:
        raise HTTPException(404, f"unknown collection {collection}")
    docs = list(dbmod.get_db()[collection].find({}).limit(min(limit, 500)))
    return StreamingResponse(iter([to_json(docs)]), media_type="application/json")


@app.get("/api/tools")
def tools():
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
             "mutating": t.mutating} for t in registry]


@app.post("/api/tools/{name}")
def call_tool(name: str, args: dict, allow_writes: bool = False):
    ctx = build_context(approve=lambda n, a: allow_writes)
    result = registry.execute(ctx, "direct", name, args)
    return StreamingResponse(iter([to_json({"is_error": result.is_error, "output": result.output})]),
                             media_type="application/json")


@app.post("/api/chat")
def chat(req: ChatRequest):
    session_id, session = _session(req.session_id, req.user)

    def stream():
        yield f"event: session\ndata: {to_json({'session_id': session_id})}\n\n"
        with session.lock:
            session.allow_writes = req.allow_writes
            for event in session.agent.chat(req.message):
                yield f"event: {event.type}\ndata: {to_json(event.data)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/reset")
def reset(req: ResetRequest):
    with _sessions_lock:
        _sessions.pop(req.session_id, None)
    return {"ok": True}


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="CRM Copilot web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    dbmod.get_db()  # connect + seed before serving
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
