"""
Application configuration loader.
"""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str

    sd_base_url: str
    sd_api_prefix: str

    app_env: str
    log_level: str
    dry_run: bool

    sqlite_path: Path

    poll_interval_seconds: int
    session_ttl_minutes: int
    cleanup_interval_seconds: int

    http_timeout_seconds: int
    tickets_poll_interval_seconds: int
    executor_sync_interval_seconds: int

    # Done tickets cleanup
    done_retention_days: int
    done_cleanup_weekday: int
    done_cleanup_hour_start: int
    done_cleanup_hour_end: int
    done_cleanup_vacuum: bool

    reauth_enable: bool
    reauth_time: str
    reauth_check_seconds: int

    reauth_on_startup: bool


def _bool(value: str) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),

        sd_base_url=os.getenv("SD_BASE_URL", ""),
        sd_api_prefix=os.getenv("SD_API_PREFIX", "/api/v1"),

        app_env=os.getenv("APP_ENV", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=_bool(os.getenv("DRY_RUN", "true")),

        sqlite_path=Path(os.getenv("SQLITE_PATH", "./data/bot.sqlite3")),

        poll_interval_seconds=_int(os.getenv("POLL_INTERVAL_SECONDS", "120"), 120),
        session_ttl_minutes=_int(os.getenv("SESSION_TTL_MINUTES", "60"), 60),
        cleanup_interval_seconds=_int(os.getenv("CLEANUP_INTERVAL_SECONDS", "300"), 300),

        http_timeout_seconds=_int(os.getenv("HTTP_TIMEOUT_SECONDS", "15"), 15),
        tickets_poll_interval_seconds=_int(os.getenv("TICKETS_POLL_INTERVAL_SECONDS", "300"), 300),
        executor_sync_interval_seconds=_int(os.getenv("EXECUTOR_SYNC_INTERVAL_SECONDS", "300"), 300),

        done_retention_days=_int(os.getenv("DONE_RETENTION_DAYS", "30"), 30),
        done_cleanup_weekday=_int(os.getenv("DONE_CLEANUP_WEEKDAY", "6"), 6),
        done_cleanup_hour_start=_int(os.getenv("DONE_CLEANUP_HOUR_START", "1"), 1),
        done_cleanup_hour_end=_int(os.getenv("DONE_CLEANUP_HOUR_END", "5"), 5),
        done_cleanup_vacuum=_bool(os.getenv("DONE_CLEANUP_VACUUM", "true")),

        reauth_enable=_bool(os.getenv("REAUTH_ENABLE", "true")),
        reauth_time=os.getenv("REAUTH_TIME", "02:00"),
        reauth_check_seconds=_int(os.getenv("REAUTH_CHECK_SECONDS", "60"), 60),

        reauth_on_startup=_bool(os.getenv("REAUTH_ON_STARTUP", "true")),
    )
