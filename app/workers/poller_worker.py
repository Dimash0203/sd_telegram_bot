"""
Poller: checks current tickets and notifies on status changes / closure.
Now supports multiple statuses with RU mapping and terminal statuses.
Plan A: on 401/403 -> notify user once + clear stored token (forces /link).
"""

import threading
from typing import Any, Dict

from loguru import logger

from app.db.repos.users_repo import get_sd_token, get_chat_id
from app.db.repos.tickets_repo import list_all_current_pairs, upsert_current, move_to_done, mark_notified
from app.sd.client import SDClient, SDUnauthorizedError
from app.sd.ticket_get_api import get_ticket
from app.services.telegram_sender import send_message


STATUS_RU: Dict[str, str] = {
    "OPENED": "ОТКРЫТ",
    "INPROGRESS": "В РАБОТЕ",
    "ACCEPTED": "ПРИНЯТ",
    "REPAIR": "НА РЕМОНТЕ",
    "POSTPONED": "ОТЛОЖЕН",
    "COMPLETED": "ВЫПОЛНЕНО",
    "CLOSED": "ЗАКРЫТ",
    "CANCELED": "ОТМЕНЁН",
}

TERMINAL_STATUSES = {"CLOSED", "COMPLETED", "CANCELED"}


def _norm_status(x: Any) -> str:
    return str(x or "").strip().upper()


def _status_ru(code: str) -> str:
    c = _norm_status(code)
    return STATUS_RU.get(c) or (c if c else "?")


def _terminal_message(ticket_id: int, status_code: str) -> str:
    s = _norm_status(status_code)
    if s == "CLOSED":
        return f"Тикет #{ticket_id} закрыт ✅"
    if s == "COMPLETED":
        return f"Тикет #{ticket_id} выполнен ✅"
    if s == "CANCELED":
        return f"Тикет #{ticket_id} отменён ❌"
    return f"Тикет #{ticket_id} завершён ({_status_ru(s)})"


def _invalidate_sd_token(conn: Any, telegram_user_id: int) -> None:
    # direct SQL, because we don't rely on repo functions here
    conn.execute(
        """
        UPDATE telegram_users
        SET sd_token = NULL, token_updated_at = datetime('now')
        WHERE telegram_user_id = ?;
        """,
        (int(telegram_user_id),),
    )


class PollerWorker:
    def __init__(self, settings: Any, db_conn: Any) -> None:
        self._settings = settings
        self._db = db_conn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="poller", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info(
            "Poller worker started (interval={}s)",
            self._settings.tickets_poll_interval_seconds,
        )

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("Poller worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Poller tick failed: {}", e)
            self._stop.wait(self._settings.tickets_poll_interval_seconds)

    def _tick(self) -> None:
        pairs = list_all_current_pairs(self._db)
        if not pairs:
            return

        client = SDClient(
            base_url=self._settings.sd_base_url,
            api_prefix=self._settings.sd_api_prefix,
            timeout_seconds=self._settings.http_timeout_seconds,
        )

        for telegram_user_id, ticket_id, last_notified_status in pairs:
            token = get_sd_token(self._db, telegram_user_id)
            chat_id = get_chat_id(self._db, telegram_user_id)

            if not token or not chat_id:
                continue

            try:
                ticket = get_ticket(client, token=token, ticket_id=ticket_id)
            except SDUnauthorizedError as e:
                logger.warning("SD unauthorized in poller (user={} ticket={}): {}", telegram_user_id, ticket_id, e)

                try:
                    send_message(
                        token=self._settings.telegram_bot_token,
                        chat_id=int(chat_id),
                        text="⚠️ Сессия ServiceDesk истекла или была сброшена.\n"
                             "Пожалуйста, авторизуйтесь заново: /link",
                        timeout_seconds=self._settings.http_timeout_seconds,
                    )
                except Exception as ne:
                    logger.error("Auth-expired notify failed (user={}): {}", telegram_user_id, ne)

                try:
                    _invalidate_sd_token(self._db, telegram_user_id)
                except Exception as de:
                    logger.error("Failed to clear sd_token (user={}): {}", telegram_user_id, de)

                # After token cleared, next iterations will skip; avoid more work now
                continue
            except Exception as e:
                logger.error("Poll ticket {} failed (user={}): {}", ticket_id, telegram_user_id, e)
                continue

            upsert_current(self._db, telegram_user_id, ticket)

            new_status = _norm_status(ticket.get("status"))
            last = _norm_status(last_notified_status)

            if new_status in TERMINAL_STATUSES:
                if new_status and new_status != last:
                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=int(chat_id),
                            text=_terminal_message(ticket_id, new_status),
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                        mark_notified(self._db, telegram_user_id, ticket_id, new_status)
                    except Exception as e:
                        logger.error("Terminal notify failed (ticket={} user={}): {}", ticket_id, telegram_user_id, e)

                move_to_done(self._db, telegram_user_id, ticket_id)
                continue

            if new_status and new_status != last:
                try:
                    send_message(
                        token=self._settings.telegram_bot_token,
                        chat_id=int(chat_id),
                        text=f"Тикет #{ticket_id}: статус изменён → {_status_ru(new_status)}",
                        timeout_seconds=self._settings.http_timeout_seconds,
                    )
                    mark_notified(self._db, telegram_user_id, ticket_id, new_status)
                except Exception as e:
                    logger.error("Notify failed (ticket={} user={}): {}", ticket_id, telegram_user_id, e)
