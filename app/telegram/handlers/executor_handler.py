"""
Executor handlers:
- /work: sync assigned tickets (filter by executor.id == my sd_user_id) + inline buttons
- /done <id>: close ticket (status -> CLOSED)
- callback actions for inline buttons
Now supports multiple statuses and RU mapping + terminal statuses.
"""

from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.repos.users_repo import get_user
from app.db.repos.tickets_repo import (
    upsert_current,
    upsert_done,
    delete_current_not_in_ids,
    delete_current,
)
from app.services.notify_service import send_text
from app.sd.client import SDClient
from app.sd.tickets_list_api import list_tickets_page
from app.sd.ticket_get_api import get_ticket
from app.sd.ticket_status_api import update_ticket_status


STATUS_RU = {
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


def _status_ru(x: Any) -> str:
    s = _norm_status(x)
    return STATUS_RU.get(s) or (s if s else "?")


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _fio(u: Any) -> str:
    if not isinstance(u, dict):
        return ""
    fio = (u.get("fio") or "").strip()
    if fio:
        return fio
    first = (u.get("firstname") or "").strip()
    last = (u.get("lastname") or "").strip()
    return (first + " " + last).strip()


def _addr(u: Any) -> str:
    if not isinstance(u, dict):
        return ""
    return (u.get("fullAddress") or "").strip()


def _kb_work(tickets: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for t in tickets[:10]:
        tid = _safe_int(t.get("id"))
        if not tid:
            continue
        rows.append([
            InlineKeyboardButton(f"🔎 Подробнее #{tid}", callback_data=f"ex:dt:{tid}"),
            InlineKeyboardButton(f"✅ Закрыть #{tid}", callback_data=f"ex:cl:{tid}"),
        ])

    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data="ex:rf")])
    return InlineKeyboardMarkup(rows)


def _kb_details(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Закрыть", callback_data=f"ex:cl:{ticket_id}"),
            InlineKeyboardButton("↩️ Назад к списку", callback_data="ex:rf"),
        ]
    ])


def _kb_confirm_close(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, закрыть", callback_data=f"ex:cy:{ticket_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"ex:cn:{ticket_id}"),
        ]
    ])


def _require_executor(deps: Dict[str, Any], telegram_user_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    u = get_user(deps["db"], telegram_user_id)
    if not u:
        return None, "Сначала привяжите аккаунт ServiceDesk: /link"

    role = str(u.get("sd_role") or "").upper()
    if role != "EXECUTOR":
        return None, "Эта функция доступна только для роли EXECUTOR."

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


async def handle_work(deps: Dict[str, Any], telegram_user_id: int) -> None:
    u, err = _require_executor(deps, telegram_user_id)
    if err:
        await send_text(deps, err)
        return

    token = u["sd_token"]
    sd_user_id = int(u["sd_user_id"])
    client = _make_client(deps)

    page = 0
    size = 25
    max_pages = 5
    assigned_active: List[Dict[str, Any]] = []
    assigned_terminal: List[Dict[str, Any]] = []

    total_pages_seen = 1

    while page < total_pages_seen and page < max_pages:
        data = list_tickets_page(client, token=token, page=page, size=size, type_="VS", sort="id", asc=False)
        total_pages_seen = _safe_int(data.get("totalPages")) or 1

        tickets = data.get("tickets") or []
        if not isinstance(tickets, list):
            tickets = []

        for t in tickets:
            if not isinstance(t, dict):
                continue
            ex = t.get("executor")
            ex_id = _safe_int(ex.get("id")) if isinstance(ex, dict) else None
            if ex_id != sd_user_id:
                continue

            st = _norm_status(t.get("status"))
            if st in TERMINAL_STATUSES:
                assigned_terminal.append(t)
            else:
                assigned_active.append(t)

        page += 1

    active_ids: List[int] = []
    for t in assigned_active:
        upsert_current(deps["db"], telegram_user_id, t, track_kind="EXECUTOR")
        active_ids.append(int(t["id"]))

    for t in assigned_terminal:
        upsert_done(deps["db"], telegram_user_id, t, track_kind="EXECUTOR")
        delete_current(deps["db"], telegram_user_id, int(t["id"]))

    delete_current_not_in_ids(deps["db"], telegram_user_id, track_kind="EXECUTOR", keep_ticket_ids=active_ids)

    lines: List[str] = []
    lines.append("🛠 Назначенные мне заявки:")
    if not assigned_active:
        lines.append("— нет активных назначенных заявок")
    else:
        for t in assigned_active[:10]:
            tid = t.get("id")
            st = _status_ru(t.get("status"))
            title = (t.get("title") or "").strip()
            author = _fio(t.get("author"))
            line = f"#{tid} · {st}"
            if title:
                line += f" · {title}"
            if author:
                line += f" · {author}"
            lines.append(line)

        if len(assigned_active) > 10:
            lines.append(f"… и ещё {len(assigned_active) - 10}")

    lines.append("")
    lines.append("Нажмите кнопку под сообщением: Подробнее / Закрыть / Обновить")

    if total_pages_seen > max_pages:
        lines.append(f"⚠️ Показаны только первые {max_pages} страниц из {total_pages_seen}.")

    await send_text(deps, "\n".join(lines), reply_markup=_kb_work(assigned_active))


async def _close_ticket_as_executor(deps: Dict[str, Any], telegram_user_id: int, ticket_id: int) -> str:
    u, err = _require_executor(deps, telegram_user_id)
    if err:
        return err

    token = u["sd_token"]
    sd_user_id = int(u["sd_user_id"])
    client = _make_client(deps)

    ticket = get_ticket(client, token=token, ticket_id=ticket_id)
    ex = ticket.get("executor")
    ex_id = _safe_int(ex.get("id")) if isinstance(ex, dict) else None
    if ex_id != sd_user_id:
        return f"Тикет #{ticket_id} не назначен вам — закрыть нельзя."

    updated = dict(ticket)
    updated["status"] = "CLOSED"

    update_ticket_status(client, token=token, ticket_id=ticket_id, ticket_payload=updated)

    upsert_done(deps["db"], telegram_user_id, updated, track_kind="EXECUTOR")
    delete_current(deps["db"], telegram_user_id, ticket_id)

    return f"Тикет #{ticket_id} закрыт ✅"


async def handle_done(deps: Dict[str, Any], telegram_user_id: int, arg_text: str) -> None:
    arg = (arg_text or "").strip()
    tid = _safe_int(arg)
    if tid is None:
        await send_text(deps, "Использование: /done <ticket_id>\nПример: /done 19")
        return

    msg = await _close_ticket_as_executor(deps, telegram_user_id, tid)
    await send_text(deps, msg)


async def handle_exec_callback(deps: Dict[str, Any], telegram_user_id: int, data: str) -> bool:
    s = (data or "").strip()
    if not s.startswith("ex:"):
        return False

    parts = s.split(":")
    if len(parts) < 2:
        return False

    action = parts[1]

    if action == "rf":
        await handle_work(deps, telegram_user_id)
        return True

    if action in ("dt", "cl", "cy", "cn"):
        if len(parts) < 3:
            await send_text(deps, "Некорректная кнопка.")
            return True

        tid = _safe_int(parts[2])
        if tid is None:
            await send_text(deps, "Некорректный ticket_id.")
            return True

        if action == "dt":
            u, err = _require_executor(deps, telegram_user_id)
            if err:
                await send_text(deps, err)
                return True

            client = _make_client(deps)
            ticket = get_ticket(client, token=u["sd_token"], ticket_id=tid)

            title = (ticket.get("title") or "").strip()
            status = ticket.get("status")
            author = _fio(ticket.get("author"))
            executor = _fio(ticket.get("executor"))
            address = _addr(ticket.get("address"))
            desc = (ticket.get("description") or "").strip()

            lines = []
            lines.append(f"🔎 Тикет #{tid}")
            if title:
                lines.append(f"• Тема: {title}")
            if status is not None:
                lines.append(f"• Статус: {_status_ru(status)}")
            if author:
                lines.append(f"• Автор: {author}")
            if executor:
                lines.append(f"• Исполнитель: {executor}")
            if address:
                lines.append(f"• Адрес: {address}")
            if desc:
                lines.append("")
                lines.append(f"Описание:\n{desc}")

            await send_text(deps, "\n".join(lines), reply_markup=_kb_details(tid))
            return True

        if action == "cl":
            await send_text(deps, f"Закрыть тикет #{tid}?", reply_markup=_kb_confirm_close(tid))
            return True

        if action == "cn":
            await send_text(deps, f"Ок, не закрываем тикет #{tid}.", reply_markup=_kb_details(tid))
            return True

        if action == "cy":
            msg = await _close_ticket_as_executor(deps, telegram_user_id, tid)
            await send_text(deps, msg)
            await handle_work(deps, telegram_user_id)
            return True

    return False
