"""
ReauthWorker: re-authenticate all users daily at configured time (settings).
Stores fresh sd_token in DB.
"""

import threading
from datetime import datetime
from typing import Any, Optional, Tuple

from loguru import logger

from app.db.repos.users_repo import list_users_with_password, update_sd_token, clear_sd_token
from app.sd.client import SDClient, SDUnauthorizedError
from app.sd.auth_api import authenticate
from app.services.telegram_sender import send_message


def _parse_hhmm(s: str) -> Optional[Tuple[int, int]]:
    try:
        parts = str(s or "").strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h, m
    except Exception:
        return None


class ReauthWorker:
    def __init__(self, settings: Any, db_conn: Any) -> None:
        self._settings = settings
        self._db = db_conn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="reauth", daemon=True)
        self._last_run_day: Optional[str] = None

    def start(self) -> None:
        if not bool(getattr(self._settings, "reauth_enable", False)):
            logger.info("Reauth worker disabled (settings.reauth_enable=false)")
            return

        at = getattr(self._settings, "reauth_time", "02:00")
        if not _parse_hhmm(at):
            logger.error("Bad settings.reauth_time: {}", at)
            return

        self._thread.start()
        logger.info(
            "Reauth worker started (time={}, check every {}s)",
            at,
            int(getattr(self._settings, "reauth_check_seconds", 60)),
        )

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("Reauth worker stopped")

    def run_now(self, *, reason: str = "manual", notify_on_fail: bool = True) -> None:
        """
        Run reauth once immediately (sync). Intended for startup relogin.
        """
        logger.info("Reauth run_now started (reason={}, notify_on_fail={})", reason, notify_on_fail)
        try:
            self._run_once(notify_on_fail=notify_on_fail)
        except Exception as e:
            logger.error("Reauth run_now failed: {}", e)

    def _run(self) -> None:
        check_s = int(getattr(self._settings, "reauth_check_seconds", 60))
        at = str(getattr(self._settings, "reauth_time", "02:00"))
        hhmm = _parse_hhmm(at)
        if not hhmm:
            logger.error("Bad settings.reauth_time: {}", at)
            return
        target_h, target_m = hhmm

        while not self._stop.is_set():
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                if self._last_run_day != today and now.hour == target_h and now.minute == target_m:
                    self._run_once(notify_on_fail=True)
                    self._last_run_day = today
            except Exception as e:
                logger.error("Reauth tick failed: {}", e)

            self._stop.wait(check_s)

    def _run_once(self, *, notify_on_fail: bool) -> None:
        users = list_users_with_password(self._db)
        if not users:
            logger.info("Reauth: no users with saved password")
            return

        client = SDClient(
            base_url=self._settings.sd_base_url,
            api_prefix=self._settings.sd_api_prefix,
            timeout_seconds=self._settings.http_timeout_seconds,
        )

        ok = 0
        fail = 0

        for u in users:
            tg_uid = int(u["telegram_user_id"])
            username = str(u.get("sd_username") or "")
            password = str(u.get("sd_password") or "")
            chat_id = u.get("tg_chat_id")

            if not username or not password:
                continue

            try:
                r = authenticate(client, username=username, password=password)
                update_sd_token(self._db, tg_uid, r.token)
                ok += 1

            except SDUnauthorizedError as e:
                # Credentials likely invalid or account blocked -> require /link
                fail += 1
                logger.warning("Reauth unauthorized (user={}): {}", tg_uid, e)
                clear_sd_token(self._db, tg_uid)

                if notify_on_fail and chat_id is not None:
                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=int(chat_id),
                            text="⚠️ Сессия ServiceDesk недействительна.\nПожалуйста, авторизуйтесь заново: /link",
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                    except Exception:
                        pass

            except Exception as e:
                fail += 1
                logger.warning("Reauth failed (user={}): {}", tg_uid, e)

                if notify_on_fail and chat_id is not None:
                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=int(chat_id),
                            text="⚠️ Не удалось обновить сессию ServiceDesk (временная ошибка). Попробуем позже.",
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                    except Exception:
                        pass

        logger.info("Reauth done: ok={} fail={}", ok, fail)
