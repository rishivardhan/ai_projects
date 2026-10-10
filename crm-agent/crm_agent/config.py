"""Runtime configuration, read from environment variables (and an optional .env file)."""
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_DIR = Path(__file__).resolve().parent / "rag" / "knowledge"


def _load_dotenv() -> None:
    """Minimal .env loader so the project needs no extra dependency for it."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    mongo_uri: str | None = os.getenv("MONGO_URI") or None
    mongo_db: str = os.getenv("MONGO_DB", "crm")
    snapshot_path: Path = Path(os.getenv("CRM_SNAPSHOT", str(DATA_DIR / "crm_snapshot.json")))
    model: str = os.getenv("CRM_MODEL", "claude-opus-5-5")
    effort: str = os.getenv("CRM_EFFORT", "medium")
    fallbacks: bool = os.getenv("CRM_FALLBACKS", "1") not in ("0", "false", "False", "")
    max_tokens: int = int(os.getenv("CRM_MAX_TOKENS", "16000"))
    max_agent_steps: int = int(os.getenv("CRM_MAX_STEPS", "15"))


settings = Settings()
