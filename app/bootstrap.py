"""
Application bootstrap: config, logging, db, workers, telegram runtime.
"""

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Optional

from loguru import logger

from app.config.settings import Settings, load_settings
from app.logging.setup import setup_logging
from app.db.sqlite import connect
from app.db.schema import init_schema

from app.sd.client import SDClient

from app.telegram.app import TelegramApp
from app.workers.cleanup_worker import CleanupWorker
from app.workers.poller_worker import PollerWorker
from app.workers.executor_sync_worker import ExecutorSyncWorker
from app.workers.reauth_worker import ReauthWorker
from app.workers.dispatcher_sync_worker import DispatcherSyncWorker

from front.server import FrontServer


def _bool(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Runner:
    settings: Settings
    db_conn: Any
    telegram: TelegramApp
    poller: PollerWorker
    cleanup: CleanupWorker
    executor_sync: ExecutorSyncWorker
    reauth: ReauthWorker
    dispatcher_sync: DispatcherSyncWorker
    front: Optional[FrontServer] = None

    def start(self) -> None:
        if self.front is not None:
            self.front.start()

        # NEW: run startup reauth before Telegram starts (so /start sees fresh tokens)
        try:
            if (not self.settings.dry_run) and bool(getattr(self.settings, "reauth_on_startup", True)):
                self.reauth.run_now(reason="startup", notify_on_fail=False)
        except Exception as e:
            logger.warning("Startup reauth failed: {}", e)

        self.telegram.start()
        self.poller.start()
        self.cleanup.start()
        self.executor_sync.start()
        self.reauth.start()
        self.dispatcher_sync.start()

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested (Ctrl+C)")
        finally:
            try:
                self.telegram.stop()
            finally:
                try:
                    self.poller.stop()
                finally:
                    try:
                        self.cleanup.stop()
                    finally:
                        try:
                            self.executor_sync.stop()
                        finally:
                            try:
                                self.reauth.stop()
                            finally:
                                try:
                                    self.dispatcher_sync.stop()
                                finally:
                                    if self.front is not None:
                                        self.front.stop()
                                    self.db_conn.close()
                                    logger.info("Service stopped")


def build_app() -> Dict[str, Any]:
    settings = load_settings()
    setup_logging(settings.log_level, settings.app_env)

    db_conn = connect(settings.sqlite_path)
    init_schema(db_conn)

    sd_client = SDClient(
        base_url=settings.sd_base_url,
        api_prefix=settings.sd_api_prefix,
        timeout_seconds=int(settings.http_timeout_seconds),
    )

    telegram_app = TelegramApp(deps={"settings": settings, "db": db_conn, "sd_client": sd_client})
    poller = PollerWorker(settings=settings, db_conn=db_conn)
    cleanup = CleanupWorker(settings=settings, db_conn=db_conn)
    executor_sync = ExecutorSyncWorker(settings=settings, db_conn=db_conn)

    reauth = ReauthWorker(settings=settings, db_conn=db_conn)
    dispatcher_sync = DispatcherSyncWorker(settings=settings, db_conn=db_conn)

    front_server: Optional[FrontServer] = None
    if _bool(os.getenv("FRONT_ENABLE", "true")):
        front_server = FrontServer()

    runner = Runner(
        settings=settings,
        db_conn=db_conn,
        telegram=telegram_app,
        poller=poller,
        cleanup=cleanup,
        executor_sync=executor_sync,
        reauth=reauth,
        dispatcher_sync=dispatcher_sync,
        front=front_server,
    )

    return {
        "settings": settings,
        "db": db_conn,
        "sd_client": sd_client,
        "telegram": telegram_app,
        "poller": poller,
        "cleanup": cleanup,
        "executor_sync": executor_sync,
        "reauth": reauth,
        "dispatcher_sync": dispatcher_sync,
        "front": front_server,
        "runner": runner,
    }
