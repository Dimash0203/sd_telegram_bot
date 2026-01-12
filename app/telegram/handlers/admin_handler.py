"""
Admin handler (lists users + view tickets + force logout + close ticket).
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.repos.users_repo import get_user, list_people_by_role, clear_sd_token
from app.db.repos.tickets_repo import (
    list_current,
    list_done,
    get_current_row,
    get_done_row,
    upsert_current,
    move_to_done,
)
from app.services.notify_service import send_text
from app.telegram.keyboards import kb_admin, kb_unauth

from app.sd.client import SDUnauthorizedError, SDClient
from app.sd.ticket_get_api import get_ticket
from app.sd.ticket_status_api import update_ticket_status

_PAGE_SIZE_USERS = 10
_PAGE_SIZE_TICKETS = 10


def _is_admin(deps: Dict[str, Any], telegram_user_id: int) -> bool:
    u = get_user(deps["db"], telegram_user_id) or {}
    return str(u.get("sd_role") or "").upper() == "ADMIN"


def _role_title(role_filter: str) -> str:
    rf = (role_filter or "").upper()
    if rf == "USER":
        return "👥 Пользователи"
    if rf == "EXECUTOR":
        return "🧑‍🔧 Исполнители"
    if rf == "DISPATCHER":
        return "🧑‍💼 Диспетчеры"
    return "Список"


def _chunk(items: List[Dict[str, Any]], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    if page < 0:
        page = 0
    total = len(items)
    max_page = max(0, (total - 1) // page_size) if total else 0
    if page > max_page:
        page = max_page
    start = page * page_size
    end = start + page_size
    return items[start:end], page


def _get_sd_client(deps: Dict[str, Any]) -> SDClient:
    c = deps.get("sd_client") or deps.get("sd") or deps.get("client")
    if not c:
        raise RuntimeError("SD client not found in deps (expected deps['sd_client'] or deps['sd']).")
    return c  # type: ignore[return-value]


def _admin_sd_token(deps: Dict[str, Any], admin_tg_id: int) -> str:
    u = get_user(deps["db"], admin_tg_id) or {}
    tok = (u.get("sd_token") or "").strip()
    if not tok:
        raise RuntimeError("ADMIN sd_token is empty (admin needs /link).")
    return tok


async def _plan_a_admin_token_expired(deps: Dict[str, Any], admin_tg_id: int) -> None:
    clear_sd_token(deps["db"], admin_tg_id)
    await send_text(deps, "🔐 Сессия ServiceDesk истекла. Пожалуйста, выполните /link заново.", reply_markup=kb_unauth())



async def handle_admin_menu(deps: Dict[str, Any], telegram_user_id: int) -> None:
    if not _is_admin(deps, telegram_user_id):
        await send_text(deps, "Недостаточно прав.")
        return

    await send_text(
        deps,
        "🛡 Админ-панель\n\n"
        "Выберите раздел на клавиатуре:\n"
        "— 👥 Пользователи\n"
        "— 🧑‍🔧 Исполнители\n"
        "— 🧑‍💼 Диспетчеры",
        reply_markup=kb_admin(),
    )


async def handle_admin_role_list(deps: Dict[str, Any], telegram_user_id: int, role_filter: str, page: int = 0) -> None:
    if not _is_admin(deps, telegram_user_id):
        await send_text(deps, "Недостаточно прав.")
        return

    people = list_people_by_role(deps["db"], role_filter=role_filter)
    page_items, page = _chunk(people, page, _PAGE_SIZE_USERS)

    title = _role_title(role_filter)
    lines = [f"{title} (залогинены):"]
    if not people:
        lines.append("— никого нет")
        await send_text(deps, "\n".join(lines), reply_markup=kb_admin())
        return

    kbd_rows: List[List[InlineKeyboardButton]] = []
    for p in page_items:
        tg_id = int(p["telegram_user_id"])
        sd_user_id = p.get("sd_user_id")
        sd_username = (p.get("sd_username") or "").strip()
        sd_role = (p.get("sd_role") or "").strip()
        label = sd_username or f"tg:{tg_id}"
        if sd_user_id is not None:
            label = f"{label} · sd:{sd_user_id}"
        if sd_role:
            label = f"{label} · {sd_role}"
        kbd_rows.append([InlineKeyboardButton(label[:64], callback_data=f"ad:u:{tg_id}:{role_filter}:p{page}")])

    total = len(people)
    max_page = max(0, (total - 1) // _PAGE_SIZE_USERS)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"ad:role:{role_filter}:p{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{max_page+1}", callback_data="ad:noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton("▶", callback_data=f"ad:role:{role_filter}:p{page+1}"))
    kbd_rows.append(nav)

    await send_text(deps, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kbd_rows))


async def _send_user_card(deps: Dict[str, Any], target: Dict[str, Any], role_filter: str, back_page: int) -> None:
    tg_id = int(target["telegram_user_id"])
    sd_user_id = target.get("sd_user_id")
    sd_username = (target.get("sd_username") or "").strip()
    sd_role = (target.get("sd_role") or "").strip()
    token_updated_at = (target.get("token_updated_at") or "").strip()
    linked_at = (target.get("linked_at") or "").strip()

    region = (target.get("sd_region") or "").strip()
    location = (target.get("sd_location") or "").strip()
    full_addr = (target.get("sd_full_address") or "").strip()

    lines = []
    lines.append("👤 Пользователь")
    if sd_username:
        lines.append(f"Логин SD: {sd_username}")
    if sd_user_id is not None:
        lines.append(f"SD user id: {sd_user_id}")
    if sd_role:
        lines.append(f"Роль: {sd_role}")
    lines.append(f"Telegram id: {tg_id}")
    if token_updated_at:
        lines.append(f"Token обновлён: {token_updated_at}")
    if linked_at:
        lines.append(f"Связка создана: {linked_at}")

    if region or location:
        loc_line = "Локация:"
        if region:
            loc_line += f" {region}"
        if location:
            loc_line += f" / {location}" if region else f" {location}"
        lines.append(loc_line)
    if full_addr:
        lines.append(f"Адрес: {full_addr}")

    kbd = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📌 Текущие тикеты", callback_data=f"ad:tcur:{tg_id}:p0:{role_filter}:p{back_page}"),
                InlineKeyboardButton("📚 История", callback_data=f"ad:tdone:{tg_id}:p0:{role_filter}:p{back_page}"),
            ],
            [InlineKeyboardButton("🚪 Разлогинить", callback_data=f"ad:logout:{tg_id}:{role_filter}:p{back_page}")],
            [InlineKeyboardButton("⬅ Назад", callback_data=f"ad:role:{role_filter}:p{back_page}")],
        ]
    )

    await send_text(deps, "\n".join(lines), reply_markup=kbd)


async def _send_tickets_list(
    deps: Dict[str, Any],
    target_tg_id: int,
    kind: str,
    page: int,
    role_filter: str,
    back_page: int,
) -> None:
    if kind == "cur":
        tickets = list_current(deps["db"], target_tg_id, track_kind=None)
        title = "📌 Текущие тикеты"
        cb_prefix = "ad:tviewc"
        list_prefix = f"ad:tcur:{target_tg_id}"
    else:
        tickets = list_done(deps["db"], target_tg_id, track_kind=None)
        title = "📚 История тикетов"
        cb_prefix = "ad:tviewd"
        list_prefix = f"ad:tdone:{target_tg_id}"

    page_items, page = _chunk(tickets, page, _PAGE_SIZE_TICKETS)

    lines = [f"{title} (пользователь tg:{target_tg_id})"]
    if not tickets:
        lines.append("— пусто")
        kbd = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅ Назад", callback_data=f"ad:u:{target_tg_id}:{role_filter}:p{back_page}")]]
        )
        await send_text(deps, "\n".join(lines), reply_markup=kbd)
        return

    kbd_rows: List[List[InlineKeyboardButton]] = []
    for r in page_items:
        tid = int(r["ticket_id"])
        status = (r.get("status") or "?").strip()
        title_short = (r.get("title") or "").strip()
        text = f"#{tid} · {status}"
        if title_short:
            text += f" · {title_short}"
        kbd_rows.append(
            [InlineKeyboardButton(text[:64], callback_data=f"{cb_prefix}:{target_tg_id}:{tid}:{role_filter}:p{back_page}:p{page}")]
        )

    total = len(tickets)
    max_page = max(0, (total - 1) // _PAGE_SIZE_TICKETS)
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀", callback_data=f"{list_prefix}:p{page-1}:{role_filter}:p{back_page}"))
    nav_row.append(InlineKeyboardButton(f"{page+1}/{max_page+1}", callback_data="ad:noop"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton("▶", callback_data=f"{list_prefix}:p{page+1}:{role_filter}:p{back_page}"))
    kbd_rows.append(nav_row)

    kbd_rows.append([InlineKeyboardButton("⬅ Назад к пользователю", callback_data=f"ad:u:{target_tg_id}:{role_filter}:p{back_page}")])

    await send_text(deps, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kbd_rows))


def _safe_str(x: Any) -> str:
    return str(x).strip() if x is not None else ""


def _track_kind_for_upsert(row: Dict[str, Any]) -> str:
    tk = row.get("track_kind")
    if tk is None or _safe_str(tk) == "":
        return "USER"
    return _safe_str(tk)


async def _send_ticket_view(
    deps: Dict[str, Any],
    target_tg_id: int,
    ticket_id: int,
    kind: str,
    role_filter: str,
    back_page: int,
    list_page: int,
) -> None:
    if kind == "cur":
        row = get_current_row(deps["db"], target_tg_id, ticket_id)
        back_cb = f"ad:tcur:{target_tg_id}:p{list_page}:{role_filter}:p{back_page}"
        title = "📌 Тикет (текущий)"
    else:
        row = get_done_row(deps["db"], target_tg_id, ticket_id)
        back_cb = f"ad:tdone:{target_tg_id}:p{list_page}:{role_filter}:p{back_page}"
        title = "📚 Тикет (история)"

    if not row:
        await send_text(
            deps,
            "Тикет не найден в локальной базе.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data=back_cb)]]),
        )
        return

    raw = row.get("raw_json") or ""
    data: Dict[str, Any] = {}
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    status = _safe_str(row.get("status") or (data.get("status") if isinstance(data, dict) else "") or "?")
    ttitle = _safe_str(row.get("title") or (data.get("title") if isinstance(data, dict) else "") or "")
    addr = _safe_str(row.get("address_full"))
    cat = _safe_str(row.get("category_name"))
    svc = _safe_str(row.get("service_name"))
    exfio = _safe_str(row.get("executor_fio"))
    aufio = _safe_str(row.get("author_fio"))

    lines = [title, f"#{ticket_id} · {status}"]
    if ttitle:
        lines.append(f"Тема: {ttitle}")
    if addr:
        lines.append(f"Адрес: {addr}")
    if cat:
        lines.append(f"Категория: {cat}")
    if svc:
        lines.append(f"Сервис: {svc}")
    if exfio:
        lines.append(f"Исполнитель: {exfio}")
    if aufio:
        lines.append(f"Автор: {aufio}")

    kbd_rows: List[List[InlineKeyboardButton]] = []

    # ✅ Закрывать имеет смысл только для "текущих" тикетов
    if kind == "cur":
        kbd_rows.append(
            [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"ad:tcloseq:{target_tg_id}:{ticket_id}:{role_filter}:p{back_page}:p{list_page}")]
        )

    kbd_rows.append([InlineKeyboardButton("⬅ Назад к списку", callback_data=back_cb)])
    kbd_rows.append([InlineKeyboardButton("⬅ Назад к пользователю", callback_data=f"ad:u:{target_tg_id}:{role_filter}:p{back_page}")])

    await send_text(deps, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kbd_rows))


async def _do_logout(deps: Dict[str, Any], target_tg_id: int, role_filter: str, back_page: int) -> None:
    clear_sd_token(deps["db"], target_tg_id)
    await send_text(
        deps,
        f"✅ Пользователь tg:{target_tg_id} разлогинен (sd_token очищен).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data=f"ad:u:{target_tg_id}:{role_filter}:p{back_page}")]]),
    )


async def _send_close_confirm(
    deps: Dict[str, Any],
    target_tg_id: int,
    ticket_id: int,
    role_filter: str,
    back_page: int,
    list_page: int,
) -> None:
    txt = (
        f"⚠️ Подтвердите действие\n\n"
        f"Закрыть тикет #{ticket_id} для пользователя tg:{target_tg_id}?\n"
        f"Статус будет установлен в CLOSED."
    )
    kbd = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Да, закрыть", callback_data=f"ad:tclose:{target_tg_id}:{ticket_id}:{role_filter}:p{back_page}:p{list_page}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"ad:tviewc:{target_tg_id}:{ticket_id}:{role_filter}:p{back_page}:p{list_page}"),
            ]
        ]
    )
    await send_text(deps, txt, reply_markup=kbd)


async def _do_close_ticket(
    deps: Dict[str, Any],
    admin_tg_id: int,
    target_tg_id: int,
    ticket_id: int,
    role_filter: str,
    back_page: int,
    list_page: int,
) -> None:
    row = get_current_row(deps["db"], target_tg_id, ticket_id)
    if not row:
        await send_text(
            deps,
            "Тикет не найден в tickets_current.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Назад", callback_data=f"ad:tcur:{target_tg_id}:p{list_page}:{role_filter}:p{back_page}")]]
            ),
        )
        return

    client = _get_sd_client(deps)
    try:
        token = _admin_sd_token(deps, admin_tg_id)

        payload = get_ticket(client, token=token, ticket_id=int(ticket_id))
        if not isinstance(payload, dict):
            raise RuntimeError("SD get_ticket returned non-object JSON")

        payload["status"] = "CLOSED"
        update_ticket_status(client, token=token, ticket_id=int(ticket_id), ticket_payload=payload)

        # Обновим из SD ещё раз (чтобы взять актуальные поля, если SD что-то проставил сам)
        updated = get_ticket(client, token=token, ticket_id=int(ticket_id))

        track_kind = _track_kind_for_upsert(row)
        upsert_current(deps["db"], target_tg_id, updated, track_kind=track_kind)

        # CLOSED — терминальный статус по вашему описанию
        move_to_done(deps["db"], target_tg_id, int(ticket_id))

        await send_text(
            deps,
            f"✅ Тикет #{ticket_id} закрыт.\n"
            f"Локальная база обновлена (tickets_current → tickets_done).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Назад к тикетам", callback_data=f"ad:tcur:{target_tg_id}:p{list_page}:{role_filter}:p{back_page}")]]
            ),
        )
        return

    except SDUnauthorizedError:
        await _plan_a_admin_token_expired(deps, admin_tg_id)
        return
    except Exception as e:
        await send_text(
            deps,
            f"❌ Не удалось закрыть тикет #{ticket_id}.\n{e}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Назад", callback_data=f"ad:tviewc:{target_tg_id}:{ticket_id}:{role_filter}:p{back_page}:p{list_page}")]]
            ),
        )
        return


async def handle_admin_callback(deps: Dict[str, Any], telegram_user_id: int, data: str) -> bool:
    if not data or not data.startswith("ad:"):
        return False

    if not _is_admin(deps, telegram_user_id):
        await send_text(deps, "Недостаточно прав.")
        return True

    if data == "ad:noop":
        return True

    # ad:role:{ROLE}:p{page}
    if data.startswith("ad:role:"):
        try:
            _, _, role_filter, p = data.split(":", 3)
            page = int(p.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка навигации.")
            return True
        await handle_admin_role_list(deps, telegram_user_id, role_filter=role_filter, page=page)
        return True

    # ad:u:{tgid}:{ROLE}:p{back_page}
    if data.startswith("ad:u:"):
        try:
            _, _, tgid_s, role_filter, p = data.split(":", 4)
            target_tg_id = int(tgid_s)
            back_page = int(p.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка выбора пользователя.")
            return True

        target = get_user(deps["db"], target_tg_id)
        if not target:
            await send_text(deps, "Пользователь не найден.")
            return True

        await _send_user_card(deps, target, role_filter=role_filter, back_page=back_page)
        return True

    # ad:tcur:{tgid}:p{page}:{ROLE}:p{back_page}
    if data.startswith("ad:tcur:"):
        try:
            _, _, tgid_s, p_list, role_filter, p_back = data.split(":", 5)
            target_tg_id = int(tgid_s)
            page = int(p_list.lstrip("p"))
            back_page = int(p_back.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка списка тикетов.")
            return True
        await _send_tickets_list(deps, target_tg_id, kind="cur", page=page, role_filter=role_filter, back_page=back_page)
        return True

    # ad:tdone:{tgid}:p{page}:{ROLE}:p{back_page}
    if data.startswith("ad:tdone:"):
        try:
            _, _, tgid_s, p_list, role_filter, p_back = data.split(":", 5)
            target_tg_id = int(tgid_s)
            page = int(p_list.lstrip("p"))
            back_page = int(p_back.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка истории тикетов.")
            return True
        await _send_tickets_list(deps, target_tg_id, kind="done", page=page, role_filter=role_filter, back_page=back_page)
        return True

    # ad:tviewc:{tgid}:{ticket_id}:{ROLE}:p{back_page}:p{list_page}
    if data.startswith("ad:tviewc:"):
        try:
            _, _, tgid_s, tid_s, role_filter, p_back, p_list = data.split(":", 6)
            target_tg_id = int(tgid_s)
            ticket_id = int(tid_s)
            back_page = int(p_back.lstrip("p"))
            list_page = int(p_list.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка карточки тикета.")
            return True
        await _send_ticket_view(deps, target_tg_id, ticket_id, kind="cur", role_filter=role_filter, back_page=back_page, list_page=list_page)
        return True

    # ad:tviewd:{tgid}:{ticket_id}:{ROLE}:p{back_page}:p{list_page}
    if data.startswith("ad:tviewd:"):
        try:
            _, _, tgid_s, tid_s, role_filter, p_back, p_list = data.split(":", 6)
            target_tg_id = int(tgid_s)
            ticket_id = int(tid_s)
            back_page = int(p_back.lstrip("p"))
            list_page = int(p_list.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка карточки тикета.")
            return True
        await _send_ticket_view(deps, target_tg_id, ticket_id, kind="done", role_filter=role_filter, back_page=back_page, list_page=list_page)
        return True

    # ad:logout:{tgid}:{ROLE}:p{back_page}
    if data.startswith("ad:logout:"):
        try:
            _, _, tgid_s, role_filter, p_back = data.split(":", 4)
            target_tg_id = int(tgid_s)
            back_page = int(p_back.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка logout.")
            return True
        await _do_logout(deps, target_tg_id, role_filter=role_filter, back_page=back_page)
        return True

    # ad:tcloseq:{tgid}:{ticket_id}:{ROLE}:p{back_page}:p{list_page}
    if data.startswith("ad:tcloseq:"):
        try:
            _, _, tgid_s, tid_s, role_filter, p_back, p_list = data.split(":", 6)
            target_tg_id = int(tgid_s)
            ticket_id = int(tid_s)
            back_page = int(p_back.lstrip("p"))
            list_page = int(p_list.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка подтверждения закрытия.")
            return True
        await _send_close_confirm(deps, target_tg_id, ticket_id, role_filter=role_filter, back_page=back_page, list_page=list_page)
        return True

    # ad:tclose:{tgid}:{ticket_id}:{ROLE}:p{back_page}:p{list_page}
    if data.startswith("ad:tclose:"):
        try:
            _, _, tgid_s, tid_s, role_filter, p_back, p_list = data.split(":", 6)
            target_tg_id = int(tgid_s)
            ticket_id = int(tid_s)
            back_page = int(p_back.lstrip("p"))
            list_page = int(p_list.lstrip("p"))
        except Exception:
            await send_text(deps, "Ошибка закрытия тикета.")
            return True
        await _do_close_ticket(
            deps,
            admin_tg_id=telegram_user_id,
            target_tg_id=target_tg_id,
            ticket_id=ticket_id,
            role_filter=role_filter,
            back_page=back_page,
            list_page=list_page,
        )
        return True

    await send_text(deps, "Неизвестное действие админа.")
    return True
