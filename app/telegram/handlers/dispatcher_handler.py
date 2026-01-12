"""
Dispatcher handlers:
- list tickets for dispatcher's location (region+location) using /ticket list and local filtering
- inline buttons: details + refresh
"""

from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.repos.users_repo import get_user as db_get_user
from app.db.repos.users_repo import set_location
from app.db.repos.tickets_repo import upsert_current, upsert_done, delete_current, delete_current_not_in_ids
from app.services.notify_service import send_text
from app.sd.client import SDClient
from app.sd.tickets_list_api import list_tickets_page
from app.sd.ticket_get_api import get_ticket
from app.sd.users_api import get_user as sd_get_user

TERMINAL_STATUSES = {"CLOSED", "COMPLETED", "CANCELED"}


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _norm(x: Any) -> str:
    return str(x or "").strip()


def _extract_ticket_loc(ticket: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    addr = ticket.get("address")
    if not isinstance(addr, dict):
        return None, None
    region = _norm(addr.get("region")) or None
    location = _norm(addr.get("location")) or None
    return region, location


def _kb_dispatcher(tickets: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for t in tickets[:10]:
        tid = _safe_int(t.get("id"))
        if not tid:
            continue
        rows.append([InlineKeyboardButton(f"🔎 Подробнее #{tid}", callback_data=f"ds:dt:{tid}")])
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data="ds:rf")])
    return InlineKeyboardMarkup(rows)


def _require_dispatcher(deps: Dict[str, Any], telegram_user_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    u = db_get_user(deps["db"], telegram_user_id)
    if not u:
        return None, "Сначала привяжите аккаунт ServiceDesk: /link"

    role = str(u.get("sd_role") or "").upper()
    if role != "DISPATCHER":
        return None, "Эта функция доступна только для роли Диспетчер."

    token = u.get("sd_token")
    sd_user_id = _safe_int(u.get("sd_user_id"))
    if not token or not sd_user_id:
        return None, "Не найден token или sd_user_id. Перепривяжите аккаунт: /link"

    return u, None


def _make_client(deps: Dict[str, Any]) -> SDClient:
    return SDClient(
        base_url=deps["settings"].sd_base_url,
        api_prefix=deps["settings"].sd_api_prefix,
        timeout_seconds=deps["settings"].http_timeout_seconds,
    )


async def handle_area(deps: Dict[str, Any], telegram_user_id: int) -> None:
    u, err = _require_dispatcher(deps, telegram_user_id)
    if err:
        await send_text(deps, err)
        return

    token = u["sd_token"]
    sd_user_id = int(u["sd_user_id"])
    client = _make_client(deps)

    region = _norm(u.get("sd_region")) or None
    location = _norm(u.get("sd_location")) or None
    full_addr = _norm(u.get("sd_full_address")) or None

    if not region or not location:
        prof = sd_get_user(client, user_id=sd_user_id, token=token)
        if prof.address:
            region = _norm(prof.address.region) or None
            location = _norm(prof.address.location) or None
            full_addr = _norm(prof.address.full_address) or None
            set_location(deps["db"], telegram_user_id, region, location, full_addr, prof.address.id)

    if not region or not location:
        await send_text(deps, "Не удалось определить вашу локацию (region/location). Перепривяжите аккаунт: /link")
        return

    page = 0
    size = 25
    max_pages = 5
    total_pages_seen = 1

    matched_active: List[Dict[str, Any]] = []
    matched_terminal: List[Dict[str, Any]] = []

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

    active_ids: List[int] = []
    for t in matched_active:
        upsert_current(deps["db"], telegram_user_id, t, track_kind="DISPATCHER")
        active_ids.append(int(t["id"]))

    for t in matched_terminal:
        upsert_done(deps["db"], telegram_user_id, t, track_kind="DISPATCHER")
        delete_current(deps["db"], telegram_user_id, int(t["id"]))

    delete_current_not_in_ids(deps["db"], telegram_user_id, track_kind="DISPATCHER", keep_ticket_ids=active_ids)

    lines: List[str] = []
    lines.append(f"📍 Тикеты по локации: {region} / {location}")
    if full_addr:
        lines.append(full_addr)
    lines.append("")

    if not matched_active:
        lines.append("— нет активных тикетов по вашей локации")
    else:
        for t in matched_active[:10]:
            tid = t.get("id")
            st = t.get("status") or "?"
            title = _norm(t.get("title"))
            line = f"#{tid} · {st}"
            if title:
                line += f" · {title}"
            lines.append(line)
        if len(matched_active) > 10:
            lines.append(f"… и ещё {len(matched_active) - 10}")

    lines.append("")
    lines.append("Нажмите кнопку под сообщением: Подробнее / Обновить")

    await send_text(deps, "\n".join(lines), reply_markup=_kb_dispatcher(matched_active))


async def handle_dispatcher_callback(deps: Dict[str, Any], telegram_user_id: int, data: str) -> bool:
    s = (data or "").strip()
    if not s.startswith("ds:"):
        return False

    parts = s.split(":")
    if len(parts) < 2:
        return False

    action = parts[1]

    if action == "rf":
        await handle_area(deps, telegram_user_id)
        return True

    if action == "dt":
        if len(parts) < 3:
            await send_text(deps, "Некорректная кнопка.")
            return True

        tid = _safe_int(parts[2])
        if tid is None:
            await send_text(deps, "Некорректный ticket_id.")
            return True

        u, err = _require_dispatcher(deps, telegram_user_id)
        if err:
            await send_text(deps, err)
            return True

        client = _make_client(deps)
        ticket = get_ticket(client, token=u["sd_token"], ticket_id=tid)

        title = _norm(ticket.get("title"))
        status = _norm(ticket.get("status"))
        addr = ticket.get("address")
        full = _norm(addr.get("fullAddress")) if isinstance(addr, dict) else ""
        desc = _norm(ticket.get("description"))

        lines: List[str] = []
        lines.append(f"🔎 Тикет #{tid}")
        if title:
            lines.append(f"• Тема: {title}")
        if status:
            lines.append(f"• Статус: {status}")
        if full:
            lines.append(f"• Адрес: {full}")
        if desc:
            lines.append("")
            lines.append(f"Описание:\n{desc}")

        await send_text(
            deps,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data="ds:rf")]]),
        )
        return True

    return False
