"""
ExecutorSyncWorker: periodically pulls /ticket list and notifies executors about NEW assigned tickets.
Plan A: on 401/403 -> notify executor once + clear stored token (forces /link).
"""

import threading
from typing import Any, Dict, List

from loguru import logger

from app.db.repos.users_repo import list_executors
from app.db.repos.tickets_repo import upsert_current, upsert_done, delete_current, delete_current_not_in_ids, current_exists
from app.sd.client import SDClient, SDUnauthorizedError
from app.sd.tickets_list_api import list_tickets_page
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


def _status_ru(code: Any) -> str:
    c = _norm_status(code)
    return STATUS_RU.get(c) or (c if c else "?")


def _fio(u: Any) -> str:
    if not isinstance(u, dict):
        return ""
    fio = (u.get("fio") or "").strip()
    if fio:
        return fio
    first = (u.get("firstname") or "").strip()
    last = (u.get("lastname") or "").strip()
    return (first + " " + last).strip()


def _addr(a: Any) -> str:
    if not isinstance(a, dict):
        return ""
    return (a.get("fullAddress") or "").strip()


def _invalidate_sd_token(conn: Any, telegram_user_id: int) -> None:
    conn.execute(
        """
        UPDATE telegram_users
        SET sd_token = NULL, token_updated_at = datetime('now')
        WHERE telegram_user_id = ?;
        """,
        (int(telegram_user_id),),
    )


class ExecutorSyncWorker:
    def __init__(self, settings: Any, db_conn: Any) -> None:
        self._settings = settings
        self._db = db_conn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="executor_sync", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info(
            "ExecutorSync worker started (interval={}s)",
            self._settings.executor_sync_interval_seconds,
        )

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("ExecutorSync worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("ExecutorSync tick failed: {}", e)
            self._stop.wait(self._settings.executor_sync_interval_seconds)

    def _tick(self) -> None:
        executors = list_executors(self._db)
        if not executors:
            return

        client = SDClient(
            base_url=self._settings.sd_base_url,
            api_prefix=self._settings.sd_api_prefix,
            timeout_seconds=self._settings.http_timeout_seconds,
        )

        for ex in executors:
            telegram_user_id = int(ex["telegram_user_id"])
            sd_user_id = int(ex["sd_user_id"])
            token = str(ex["sd_token"])
            chat_id = int(ex["tg_chat_id"])

            page = 0
            size = 25
            max_pages = 5
            total_pages_seen = 1

            assigned_active: List[Dict[str, Any]] = []
            assigned_terminal: List[Dict[str, Any]] = []

            try:
                while page < total_pages_seen and page < max_pages:
                    data = list_tickets_page(
                        client,
                        token=token,
                        page=page,
                        size=size,
                        type_="VS",
                        sort="id",
                        asc=False,
                    )
                    try:
                        total_pages_seen = int(data.get("totalPages") or 1)
                    except Exception:
                        total_pages_seen = 1

                    tickets = data.get("tickets") or []
                    if not isinstance(tickets, list):
                        tickets = []

                    for t in tickets:
                        if not isinstance(t, dict):
                            continue
                        executor = t.get("executor")
                        ex_id = None
                        if isinstance(executor, dict):
                            try:
                                ex_id = int(executor.get("id"))
                            except Exception:
                                ex_id = None
                        if ex_id != sd_user_id:
                            continue

                        st = _norm_status(t.get("status"))
                        if st in TERMINAL_STATUSES:
                            assigned_terminal.append(t)
                        else:
                            assigned_active.append(t)

                    page += 1

            except SDUnauthorizedError as e:
                logger.warning("SD unauthorized in executor sync (user={}): {}", telegram_user_id, e)

                try:
                    send_message(
                        token=self._settings.telegram_bot_token,
                        chat_id=chat_id,
                        text="⚠️ Сессия ServiceDesk истекла или была сброшена.\n"
                             "Пожалуйста, авторизуйтесь заново: /link",
                        timeout_seconds=self._settings.http_timeout_seconds,
                    )
                except Exception as ne:
                    logger.error("Auth-expired notify failed (executor user={}): {}", telegram_user_id, ne)

                try:
                    _invalidate_sd_token(self._db, telegram_user_id)
                except Exception as de:
                    logger.error("Failed to clear sd_token (executor user={}): {}", telegram_user_id, de)

                continue

            # Notify + persist active assigned
            keep_ids: List[int] = []
            for t in assigned_active:
                tid = int(t["id"])
                keep_ids.append(tid)

                is_new = not current_exists(self._db, telegram_user_id, tid)
                upsert_current(self._db, telegram_user_id, t, track_kind="EXECUTOR")

                if is_new:
                    title = (t.get("title") or "").strip()
                    status = _norm_status(t.get("status") or "OPENED")
                    author = _fio(t.get("author"))
                    address = _addr(t.get("address"))

                    text = f"🆕 Вам назначен тикет #{tid} · {_status_ru(status)}"
                    if title:
                        text += f"\n{title}"
                    if author:
                        text += f"\nАвтор: {author}"
                    if address:
                        text += f"\nАдрес: {address}"

                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=chat_id,
                            text=text,
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                    except Exception as e:
                        logger.error("Executor new-ticket notify failed (ticket={} user={}): {}", tid, telegram_user_id, e)

            for t in assigned_terminal:
                tid = int(t["id"])
                upsert_done(self._db, telegram_user_id, t, track_kind="EXECUTOR")
                delete_current(self._db, telegram_user_id, tid)

            delete_current_not_in_ids(self._db, telegram_user_id, track_kind="EXECUTOR", keep_ticket_ids=keep_ids)
