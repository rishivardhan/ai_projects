"""Step 1 - The NoSQL database.

The CRM lives in a MongoDB document database with six collections:

    accounts, contacts, opportunities, leads, interactions, tasks

Two backends share the exact same pymongo API:

* **MongoDB** - set ``MONGO_URI`` (e.g. ``docker compose up -d`` then
  ``MONGO_URI=mongodb://localhost:27017``).
* **Embedded** - when ``MONGO_URI`` is unset we use ``mongomock`` (an in-process
  MongoDB implementation) and persist it to a JSON snapshot on disk, so the whole
  system runs with zero infrastructure.
"""
from __future__ import annotations

import threading

from bson import json_util

from .config import settings

COLLECTIONS = ("accounts", "contacts", "opportunities", "leads", "interactions", "tasks")

# Secondary indexes - the access paths the agent's tools rely on.
INDEXES = {
    "accounts": ["name", "industry", "tier", "status", "owner"],
    "contacts": ["account_id", "email", "last_name"],
    "opportunities": ["account_id", "stage", "owner", "close_date"],
    "leads": ["status", "source", "owner", "score"],
    "interactions": ["account_id", "contact_id", "opportunity_id", "lead_id", "timestamp"],
    "tasks": ["status", "owner", "due_date", "account_id"],
}

_lock = threading.Lock()
_db = None


def _is_mock(db) -> bool:
    return type(db).__module__.startswith("mongomock")


def ensure_indexes(db) -> None:
    for coll, fields in INDEXES.items():
        for field in fields:
            db[coll].create_index(field)


def load_snapshot(db, path=None) -> bool:
    path = path or settings.snapshot_path
    if not path.exists():
        return False
    data = json_util.loads(path.read_text())
    for coll in COLLECTIONS:
        db[coll].delete_many({})
        docs = data.get(coll, [])
        if docs:
            db[coll].insert_many(docs)
    return True


def save_snapshot(db=None, path=None) -> None:
    """Persist the embedded database. No-op when running against a real MongoDB."""
    db = db if db is not None else get_db()
    if not _is_mock(db):
        return
    path = path or settings.snapshot_path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {coll: list(db[coll].find({})) for coll in COLLECTIONS}
    with _lock:
        path.write_text(json_util.dumps(data, indent=1))


def connect(mongo_uri: str | None = None, db_name: str | None = None, *, auto_seed: bool = True):
    """Create a database handle (real MongoDB or embedded) and seed it if empty."""
    mongo_uri = mongo_uri if mongo_uri is not None else settings.mongo_uri
    db_name = db_name or settings.mongo_db
    if mongo_uri:
        import pymongo

        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, tz_aware=False)
        client.admin.command("ping")
        db = client[db_name]
    else:
        import mongomock

        db = mongomock.MongoClient()[db_name]
        load_snapshot(db)

    if auto_seed and db.accounts.count_documents({}) == 0:
        from .seed import seed_database

        seed_database(db)
        save_snapshot(db)
    ensure_indexes(db)
    return db


def get_db():
    """Process-wide singleton handle."""
    global _db
    if _db is None:
        _db = connect()
    return _db


def set_db(db) -> None:
    """Override the singleton (used by tests)."""
    global _db
    _db = db


def backend_name(db=None) -> str:
    db = db if db is not None else get_db()
    return "embedded (mongomock)" if _is_mock(db) else "MongoDB"
