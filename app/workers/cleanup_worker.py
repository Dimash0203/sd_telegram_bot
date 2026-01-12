"""
Cleanup worker: expires sessions and scheduled cleanup for done tickets.
Also optionally performs WAL checkpoint + VACUUM to actually reduce DB size on disk.
"""

import threading
from datetime import datetime
from typing import Optional

from loguru import logger

from app.db.repos.sessions_repo import delete_expired_sessions
from app.db.repos.tickets_repo import delete_done_older_than_days


def _in_hour_window(hour: int, start: int, end: int) -> bool:
    """Inclusive hour window; supports wrap-around (e.g., 23..2)."""
    hour = int(hour)
    start = int(start)
    end = int(end)
    if start <= end:
        return start <= hour <= end
    # wrap around midnight
    return hour >= start or hour <= end


class CleanupWorker:
    def __init__(self, settings, db_conn) -> None:
        self._settings = settings
        self._db = db_conn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cleanup", daemon=True)

        # Prevent repeated heavy cleanup+vacuum during the window
        self._last_done_cleanup_day: Optional[str] = None  # "YYYY-MM-DD"

    def start(self) -> None:
        self._thread.start()
        logger.info(
            "Cleanup worker started (interval={}s, ttl={}m)",
            self._settings.cleanup_interval_seconds,
            self._settings.session_ttl_minutes,
        )

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("Cleanup worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Cleanup tick failed: {}", e)
            self._stop.wait(self._settings.cleanup_interval_seconds)

    def _tick(self) -> None:
        # 1) Sessions TTL cleanup
        expired = delete_expired_sessions(self._db, ttl_minutes=self._settings.session_ttl_minutes)
        if expired:
            logger.info("Expired sessions deleted: {}", expired)

        # 2) Done tickets cleanup (scheduled)
        now = datetime.now()
        today_key = now.strftime("%Y-%m-%d")

        should_run_today = (
            int(now.weekday()) == int(self._settings.done_cleanup_weekday)
            and _in_hour_window(int(now.hour), int(self._settings.done_cleanup_hour_start), int(self._settings.done_cleanup_hour_end))
        )

        if not should_run_today:
            return

        # run at most once per day per process
        if self._last_done_cleanup_day == today_key:
            return

        days = int(getattr(self._settings, "done_retention_days", 30) or 30)
        deleted = delete_done_older_than_days(self._db, days=days)

        if deleted:
            logger.info("Done tickets cleaned (retention={}d): {}", days, deleted)
        else:
            logger.info("Done tickets cleanup ran (retention={}d): nothing to delete", days)

        # Optional: shrink DB on disk
        if bool(getattr(self._settings, "done_cleanup_vacuum", True)):
            try:
                # Truncate WAL as much as possible, then rebuild DB file
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._db.execute("VACUUM;")
                logger.info("DB vacuum completed (WAL checkpoint + VACUUM)")
            except Exception as e:
                logger.error("DB vacuum failed: {}", e)

        self._last_done_cleanup_day = today_key
