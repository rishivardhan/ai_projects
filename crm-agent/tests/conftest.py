import mongomock
import pytest
from crm_agent import db as dbmod
from crm_agent.agent import build_context
from crm_agent.seed import seed_database


@pytest.fixture()
def db(tmp_path, monkeypatch):
    database = mongomock.MongoClient()["crm_test"]
    seed_database(database)
    dbmod.ensure_indexes(database)
    dbmod.set_db(database)
    # never touch the real snapshot file from tests
    monkeypatch.setattr(dbmod, "save_snapshot", lambda *a, **k: None)
    yield database
    dbmod.set_db(None)


@pytest.fixture()
def ctx(db):
    return build_context(user="Test User", db=db)
