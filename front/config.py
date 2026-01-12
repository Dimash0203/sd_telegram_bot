"""
Front config loader.
"""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class FrontSettings:
    sqlite_path: Path
    host: str
    port: int


def _int(v: str, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def load_front_settings() -> FrontSettings:
    load_dotenv()
    return FrontSettings(
        sqlite_path=Path(os.getenv("FRONT_SQLITE_PATH", "./data/bot.sqlite3")),
        host=os.getenv("FRONT_HOST", "127.0.0.1"),
        port=_int(os.getenv("FRONT_PORT", "8010"), 8010),
    )
