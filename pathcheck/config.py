"""Settings from the environment, with a tiny .env loader (no dependencies)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def flag(name: str) -> bool:
    return env(name).lower() in ("1", "true", "yes", "on")


# SAMPLE_MODE: run with no Zetaris and no Nightshift (local SQLite + recorded model replies).
SAMPLE_MODE = flag("SAMPLE_MODE")
# LLM_LIVE: in SAMPLE_MODE, still send model requests to Nightshift (data stays on the local copy).
LLM_LIVE = flag("LLM_LIVE")

ZETARIS_REST_URL = env("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0")
ZETARIS_ORG_ID = env("ZETARIS_ORG_ID", "1")
ZETARIS_API_KEY = env("ZETARIS_API_KEY")
ZETARIS_DB = env("ZETARIS_DB", "pathcheck")

METERLESS_BASE_URL = env("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1")
METERLESS_RUNTIME_TOKEN = env("METERLESS_RUNTIME_TOKEN")
METERLESS_APP_ID = env("METERLESS_APP_ID", "pathcheck")
# Lanes map agent roles to Nightshift routing modes or concrete model ids.
LANE_FAST = env("LANE_FAST", "meterless/fast")
LANE_DEEP = env("LANE_DEEP", "meterless/deep")
LANE_JUDGE = env("LANE_JUDGE", "meterless/auto")

TODAY = env("PATHCHECK_TODAY", "2026-10-27")
FRESH_DAYS = int(env("FRESH_DAYS", "240"))
MAX_ROUNDS = int(env("MAX_ROUNDS", "3"))
LOG_DIR = ROOT / "logs"
