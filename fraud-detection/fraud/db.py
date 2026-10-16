"""Database connection helpers."""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/frauddb"
)
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

_engine = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL)
    return _engine


def init_schema(engine: Engine, reset: bool = False) -> None:
    """Create the `fraud` schema. With reset=True, drop everything first."""
    with engine.begin() as conn:
        if reset:
            conn.execute(text("DROP SCHEMA IF EXISTS fraud CASCADE"))
        conn.exec_driver_sql(SCHEMA_FILE.read_text())
