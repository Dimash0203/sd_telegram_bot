"""
DispatcherSyncWorker: periodically pulls /ticket list and notifies dispatchers about NEW tickets for their location.
Filtering is done by comparing ticket.address.region+location with dispatcher's address region+location.
"""

import threading
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.db.repos.users_repo import list_dispatchers, clear_sd_token, set_location
from app.db.repos.tickets_repo import upsert_current, upsert_done, delete_current, delete_current_not_in_ids, current_exists
from app.sd.client import SDClient, SDUnauthorizedError
from app.sd.tickets_list_api import list_tickets_page
from app.sd.users_api import get_user
from app.services.telegram_sender import send_message


TERMINAL_STATUSES = {"CLOSED", "COMPLETED", "CANCELED"}


def _norm(x: Any) -> str:
    return str(x or "").strip()


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _extract_location_from_profile(profile: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    addr = profile.get("address")
    if not isinstance(addr, dict):
        return None, None, None, None
    region = _norm(addr.get("region")) or None
    location = _norm(addr.get("location")) or None
    full = _norm(addr.get("fullAddress")) or None
    aid = _safe_int(addr.get("id"))
    return region, location, full, aid


def _extract_ticket_loc(ticket: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    addr = ticket.get("address")
    if not isinstance(addr, dict):
        return None, None
    region = _norm(addr.get("region")) or None
    location = _norm(addr.get("location")) or None
    return region, location


class DispatcherSyncWorker:
    def __init__(self, settings: Any, db_conn: Any) -> None:
        self._settings = settings
        self._db = db_conn
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dispatcher_sync", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info("DispatcherSync worker started (interval={}s)", self._settings.executor_sync_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("DispatcherSync worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("DispatcherSync tick failed: {}", e)
            self._stop.wait(self._settings.executor_sync_interval_seconds)

    def _tick(self) -> None:
        dispatchers = list_dispatchers(self._db)
        if not dispatchers:
            return

        client = SDClient(
            base_url=self._settings.sd_base_url,
            api_prefix=self._settings.sd_api_prefix,
            timeout_seconds=self._settings.http_timeout_seconds,
        )

        for d in dispatchers:
            telegram_user_id = int(d["telegram_user_id"])
            sd_user_id = int(d["sd_user_id"])
            token = str(d["sd_token"])
            chat_id = int(d["tg_chat_id"])

            region = _norm(d.get("sd_region")) or None
            location = _norm(d.get("sd_location")) or None

            # ensure location
            if not region or not location:
                try:
                    prof = get_user(client, token=token, sd_user_id=sd_user_id)
                    region, location, full, aid = _extract_location_from_profile(prof)
                    set_location(self._db, telegram_user_id, region, location, full, aid)
                except SDUnauthorizedError:
                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=chat_id,
                            text="⚠️ Сессия ServiceDesk истекла.\nПожалуйста, авторизуйтесь заново: /link",
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                    except Exception:
                        pass
                    clear_sd_token(self._db, telegram_user_id)
                    continue
                except Exception as e:
                    logger.warning("Dispatcher location fetch failed (user={}): {}", telegram_user_id, e)
                    continue

            if not region or not location:
                continue

            page = 0
            size = 25
            max_pages = 5
            total_pages_seen = 1

            matched_active: List[Dict[str, Any]] = []
            matched_terminal: List[Dict[str, Any]] = []

            try:
                while page < total_pages_seen and page < max_pages:
                    data = list_tickets_page(client, token=token, page=page, size=size, type_="VS", sort="id", asc=False)
                    total_pages_seen = _safe_int(data.get("totalPages")) or 1

                    tickets = data.get("tickets") or []
                    if not isinstance(tickets, list):
                        tickets = []

                    for t in tickets:
                        if not isinstance(t, dict):
                            continue
                        tr, tl = _extract_ticket_loc(t)
                        if tr != region or tl != location:
                            continue

                        st = str(t.get("status") or "").upper()
                        if st in TERMINAL_STATUSES:
                            matched_terminal.append(t)
                        else:
                            matched_active.append(t)

                    page += 1

            except SDUnauthorizedError:
                try:
                    send_message(
                        token=self._settings.telegram_bot_token,
                        chat_id=chat_id,
                        text="⚠️ Сессия ServiceDesk истекла.\nПожалуйста, авторизуйтесь заново: /link",
                        timeout_seconds=self._settings.http_timeout_seconds,
                    )
                except Exception:
                    pass
                clear_sd_token(self._db, telegram_user_id)
                continue

            keep_ids: List[int] = []
            for t in matched_active:
                tid = int(t["id"])
                keep_ids.append(tid)

                is_new = not current_exists(self._db, telegram_user_id, tid)
                upsert_current(self._db, telegram_user_id, t, track_kind="DISPATCHER")

                if is_new:
                    title = _norm(t.get("title"))
                    status = _norm(t.get("status")) or "OPENED"
                    text = f"🆕 Новый тикет по вашей локации #{tid} · {status}"
                    if title:
                        text += f"\n{title}"
                    try:
                        send_message(
                            token=self._settings.telegram_bot_token,
                            chat_id=chat_id,
                            text=text,
                            timeout_seconds=self._settings.http_timeout_seconds,
                        )
                    except Exception:
                        pass

            for t in matched_terminal:
                tid = int(t["id"])
                upsert_done(self._db, telegram_user_id, t, track_kind="DISPATCHER")
                delete_current(self._db, telegram_user_id, tid)

            delete_current_not_in_ids(self._db, telegram_user_id, track_kind="DISPATCHER", keep_ticket_ids=keep_ids)
