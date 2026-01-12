"""
Ticket create flow: title -> description -> confirm -> create in SD.
Uses inline buttons instead of yes/no.
"""

from typing import Any, Dict

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.repos.sessions_repo import upsert_session, get_session, delete_session
from app.db.repos.users_repo import get_sd_token, get_sd_user_id
from app.services.notify_service import send_text
from app.services.ticket_service import create_simple_ticket
from app.db.repos.tickets_repo import upsert_current


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Отправить", callback_data="tc:send")],
            [InlineKeyboardButton("✏️ Изменить описание", callback_data="tc:edit_desc")],
            [InlineKeyboardButton("❌ Отмена", callback_data="tc:cancel")],
        ]
    )


def _preview_text(draft: Dict[str, Any]) -> str:
    title = str(draft.get("title") or "").strip()
    desc = str(draft.get("description") or "").strip()
    return (
        "Проверьте заявку:\n\n"
        f"Заголовок: {title}\n"
        f"Описание: {desc}\n\n"
        "Нажмите кнопку ниже:"
    )


async def handle_new(deps: Dict[str, Any], telegram_user_id: int) -> None:
    upsert_session(deps["db"], telegram_user_id, "TICKET_TITLE", {"draft": {}})
    await send_text(deps, "Введите заголовок заявки:")


async def handle_cancel(deps: Dict[str, Any], telegram_user_id: int) -> None:
    delete_session(deps["db"], telegram_user_id)
    await send_text(deps, "Ок, отменено.")


async def handle_text(deps: Dict[str, Any], telegram_user_id: int, text: str) -> None:
    session = get_session(deps["db"], telegram_user_id)
    if not session:
        await send_text(deps, "Нажмите «🆕 Новая заявка» или используйте команду /new.")
        return

    state = session["state"]
    data = session["data"]
    draft = data.get("draft", {})

    t = (text or "").strip()
    if not t:
        await send_text(deps, "Пожалуйста, отправьте текст.")
        return

    if state == "TICKET_TITLE":
        draft["title"] = t
        upsert_session(deps["db"], telegram_user_id, "TICKET_DESC", {"draft": draft})
        await send_text(deps, "Введите описание проблемы:")
        return

    if state == "TICKET_DESC":
        draft["description"] = t
        upsert_session(deps["db"], telegram_user_id, "TICKET_CONFIRM", {"draft": draft})
        await send_text(deps, _preview_text(draft), reply_markup=_kb_confirm())
        return

    if state == "TICKET_CONFIRM":
        await send_text(deps, "Пожалуйста, используйте кнопки ниже.", reply_markup=_kb_confirm())
        return

    await send_text(deps, "Нажмите «🆕 Новая заявка» или используйте /new.")


async def handle_ticket_callback(deps: Dict[str, Any], telegram_user_id: int, data: str) -> bool:
    """
    Inline confirm buttons:
      tc:send
      tc:edit_desc
      tc:cancel
    """
    s = (data or "").strip()
    if not s.startswith("tc:"):
        return False

    session = get_session(deps["db"], telegram_user_id)
    if not session:
        await send_text(deps, "Сессия не найдена. Начните заново: /new")
        return True

    state = session["state"]
    draft = (session.get("data") or {}).get("draft", {}) or {}

    action = s.split(":", 1)[1].strip()

    if action == "cancel":
        delete_session(deps["db"], telegram_user_id)
        await send_text(deps, "Ок, отменено.")
        return True

    if action == "edit_desc":
        upsert_session(deps["db"], telegram_user_id, "TICKET_DESC", {"draft": draft})
        await send_text(deps, "Ок. Введите описание проблемы заново:")
        return True

    if action == "send":
        if state != "TICKET_CONFIRM":
            await send_text(deps, "Сначала заполните заявку: /new")
            return True

        token = get_sd_token(deps["db"], telegram_user_id)
        sd_user_id = get_sd_user_id(deps["db"], telegram_user_id)

        if not token or not sd_user_id:
            delete_session(deps["db"], telegram_user_id)
            await send_text(deps, "Сначала привяжите аккаунт ServiceDesk: /link")
            return True

        title = str(draft.get("title") or "").strip()
        description = str(draft.get("description") or "").strip()

        if not title or not description:
            delete_session(deps["db"], telegram_user_id)
            await send_text(deps, "Черновик поврежден. Начните заново: /new")
            return True

        # защита от двойного клика
        upsert_session(deps["db"], telegram_user_id, "TICKET_SENDING", {"draft": draft})

        try:
            result = create_simple_ticket(
                settings=deps["settings"],
                token=token,
                sd_user_id=int(sd_user_id),
                title=title,
                description=description,
            )

            upsert_current(deps["db"], telegram_user_id, result.raw)

            ticket = result.summary

            msg_lines = ["Заявка создана ✅", f"ID: {ticket.id}"]

            if ticket.status:
                msg_lines.append(f"Статус: {ticket.status}")
            if ticket.category:
                msg_lines.append(f"Категория: {ticket.category}")

            if ticket.service:
                if ticket.execution_timestamp is not None:
                    msg_lines.append(f"Услуга: {ticket.service} (время: {ticket.execution_timestamp} мин)")
                else:
                    msg_lines.append(f"Услуга: {ticket.service}")

            if ticket.address:
                msg_lines.append(f"Адрес: {ticket.address}")

            msg_lines.append(f"Исполнитель: {ticket.executor}" if ticket.executor else "Исполнитель: не назначен")

            if ticket.company:
                msg_lines.append(f"Компания: {ticket.company}")
            if ticket.contract:
                msg_lines.append(f"Договор: {ticket.contract}")
            if ticket.created_at:
                msg_lines.append(f"Создано: {ticket.created_at}")
            if ticket.kind:
                msg_lines.append(f"Тип: {ticket.kind}")

            await send_text(deps, "\n".join(msg_lines))

        except Exception as e:
            logger.error("Create ticket failed: {}", e)
            await send_text(deps, "Ошибка создания заявки. Попробуйте позже или обратитесь к администратору.")
        finally:
            delete_session(deps["db"], telegram_user_id)

        return True

    await send_text(deps, "Неизвестная кнопка.")
    return True
