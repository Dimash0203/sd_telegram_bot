"""
Telegram update router.
"""

from dataclasses import dataclass
from typing import Any, Dict

from loguru import logger

from app.services.notify_service import send_text
from app.db.repos.users_repo import (
    is_linked,
    set_chat_id,
    get_user,
    upsert_user,
    clear_sd_token,
)

from app.sd.auth_api import authenticate
from app.sd.client import SDUnauthorizedError

from app.telegram.handlers.start_handler import handle_start
from app.telegram.handlers.ticket_create_handler import (
    handle_new,
    handle_cancel,
    handle_text,
    handle_ticket_callback,
)
from app.telegram.handlers.ticket_list_handler import handle_my
from app.telegram.handlers.link_handler import handle_link, handle_link_text
from app.telegram.handlers.executor_handler import handle_work, handle_done, handle_exec_callback
from app.telegram.handlers.dispatcher_handler import handle_area, handle_dispatcher_callback
from app.telegram.handlers.admin_handler import (
    handle_admin_menu,
    handle_admin_role_list,
    handle_admin_callback,
)
from app.telegram.keyboards import kb_unauth


def _help_text(is_user_linked: bool, sd_role: str) -> str:
    if not is_user_linked:
        return "Команды:\n/start\n/help\n/link"

    r = (sd_role or "").upper()
    if r == "ADMIN":
        return (
            "Команды:\n/start\n/help\n/admin\n/cancel\n\n"
            "Кнопки:\n"
            "— «👥 Пользователи»\n"
            "— «🧑‍🔧 Исполнители»\n"
            "— «🧑‍💼 Диспетчеры»"
        )
    if r == "EXECUTOR":
        return "Команды:\n/start\n/help\n/work\n/done <id>\n/my\n/cancel"
    if r == "DISPATCHER":
        return "Команды:\n/start\n/help\n/my\n/cancel\n\nКнопка: «📍 Тикеты по локации»"
    return "Команды:\n/start\nhelp\n/new\n/my\n/cancel"


def _ensure_linked(deps: Dict[str, Any], telegram_user_id: int, chat_id: int) -> bool:
    """
    If user has no token but has saved username/password, try to re-auth silently.
    Returns True if token exists after this.
    """
    # Always store chat_id if user row exists (harmless if no row)
    try:
        set_chat_id(deps["db"], telegram_user_id, chat_id)
    except Exception:
        pass

    if is_linked(deps["db"], telegram_user_id):
        return True

    u = get_user(deps["db"], telegram_user_id)
    if not u:
        return False

    username = str(u.get("sd_username") or "")
    password = str(u.get("sd_password") or "")
    if not username or not password:
        return False

    try:
        r = authenticate(deps["sd_client"], username=username, password=password)

        # Update everything important, keep existing stored password (pass sd_password=None)
        upsert_user(
            deps["db"],
            telegram_user_id=telegram_user_id,
            sd_user_id=int(r.sd_user_id),
            sd_username=str(r.username),
            sd_role=str(r.role),
            sd_token=str(r.token),
            sd_password=None,
        )

        logger.info("Auto-reauth ok (tg_user_id={})", telegram_user_id)
        return True

    except SDUnauthorizedError as e:
        # creds likely invalid -> require /link
        logger.warning("Auto-reauth unauthorized (tg_user_id={}): {}", telegram_user_id, e)
        try:
            clear_sd_token(deps["db"], telegram_user_id)
        except Exception:
            pass
        return False

    except Exception as e:
        # temporary issue -> do not clear token (already empty), just fail silently
        logger.warning("Auto-reauth failed (tg_user_id={}): {}", telegram_user_id, e)
        return False


@dataclass
class Router:
    deps: Dict[str, Any]

    async def handle_command(self, update, context, command: str) -> None:
        telegram_user_id = int(update.effective_user.id)
        chat_id = int(update.effective_chat.id)

        deps = dict(self.deps)
        deps["tg"] = {"chat_id": chat_id, "context": context}

        # Do NOT auto-reauth on /link (let user relink explicitly)
        if command != "/link":
            linked = _ensure_linked(deps, telegram_user_id, chat_id)
        else:
            linked = is_linked(deps["db"], telegram_user_id)
            if linked:
                set_chat_id(deps["db"], telegram_user_id, chat_id)

        if command == "/start":
            await handle_start(deps, telegram_user_id)
            return

        if command == "/help":
            u = get_user(deps["db"], telegram_user_id) if linked else None
            sd_role = (u.get("sd_role") if u else "") or ""
            await send_text(deps, _help_text(linked, str(sd_role)))
            return

        if command == "/link":
            await handle_link(deps, telegram_user_id)
            return

        if command == "/admin":
            if not linked:
                await send_text(
                    deps,
                    "Сначала привяжите аккаунт ServiceDesk: /link",
                    reply_markup=kb_unauth(),
                )
                return
            u = get_user(deps["db"], telegram_user_id) or {}
            role = str(u.get("sd_role") or "").upper()
            if role != "ADMIN":
                await send_text(deps, "Недостаточно прав.")
                return
            await handle_admin_menu(deps, telegram_user_id)
            return

        if command in ("/new", "/my", "/work", "/done") and not linked:
            await send_text(
                deps,
                "Сначала привяжите аккаунт ServiceDesk: /link",
                reply_markup=kb_unauth(),
            )
            return

        if command == "/new":
            await handle_new(deps, telegram_user_id)
            return

        if command == "/cancel":
            await handle_cancel(deps, telegram_user_id)
            return

        if command == "/my":
            await handle_my(deps, telegram_user_id)
            return

        if command == "/work":
            await handle_work(deps, telegram_user_id)
            return

        if command == "/done":
            full_text = (getattr(update.effective_message, "text", "") or "").strip()
            parts = full_text.split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
            await handle_done(deps, telegram_user_id, arg)
            return

        await send_text(deps, "Неизвестная команда. /help")

    async def handle_callback(self, update, context, data: str) -> None:
        telegram_user_id = int(update.effective_user.id)
        chat_id = int(update.effective_chat.id)

        deps = dict(self.deps)
        deps["tg"] = {"chat_id": chat_id, "context": context}

        linked = _ensure_linked(deps, telegram_user_id, chat_id)
        if not linked:
            await send_text(deps, "Сначала привяжите аккаунт ServiceDesk: /link", reply_markup=kb_unauth())
            return

        handled = await handle_ticket_callback(deps, telegram_user_id, data)
        if handled:
            return

        handled = await handle_exec_callback(deps, telegram_user_id, data)
        if handled:
            return

        handled = await handle_dispatcher_callback(deps, telegram_user_id, data)
        if handled:
            return

        handled = await handle_admin_callback(deps, telegram_user_id, data)
        if handled:
            return

        await send_text(deps, "Неизвестное действие. /help")

    async def handle_text(self, update, context, text: str) -> None:
        telegram_user_id = int(update.effective_user.id)
        chat_id = int(update.effective_chat.id)

        deps = dict(self.deps)
        deps["tg"] = {"chat_id": chat_id, "context": context}

        t = (text or "").strip()

        if t == "🔐 Авторизоваться":
            await handle_link(deps, telegram_user_id)
            return

        handled = await handle_link_text(deps, telegram_user_id, t)
        if handled:
            return

        if t in ("ℹ️ Помощь", "ℹ️ Help"):
            await self.handle_command(update, context, "/help")
            return

        linked = _ensure_linked(deps, telegram_user_id, chat_id)
        if not linked:
            await send_text(deps, "Сначала привяжите аккаунт ServiceDesk: /link", reply_markup=kb_unauth())
            return

        u = get_user(deps["db"], telegram_user_id) or {}
        role = str(u.get("sd_role") or "").upper()

        if role == "ADMIN":
            if t in ("🛡 Админ", "🛡 Админ-панель"):
                await handle_admin_menu(deps, telegram_user_id)
                return
            if t == "👥 Пользователи":
                await handle_admin_role_list(deps, telegram_user_id, role_filter="USER", page=0)
                return
            if t == "🧑‍🔧 Исполнители":
                await handle_admin_role_list(deps, telegram_user_id, role_filter="EXECUTOR", page=0)
                return
            if t == "🧑‍💼 Диспетчеры":
                await handle_admin_role_list(deps, telegram_user_id, role_filter="DISPATCHER", page=0)
                return

            await send_text(deps, "Выберите раздел на клавиатуре или /help.")
            return

        if t == "🛠 Назначенные":
            await handle_work(deps, telegram_user_id)
            return

        if t == "📍 Тикеты по локации":
            await handle_area(deps, telegram_user_id)
            return

        if t == "📚 История заявок":
            await handle_my(deps, telegram_user_id)
            return

        if t in ("📌 Мои (локально)", "📌 Мои заявки", "📌 Мои"):
            await handle_my(deps, telegram_user_id)
            return

        if t == "🆕 Новая заявка":
            await handle_new(deps, telegram_user_id)
            return

        await handle_text(deps, telegram_user_id, t)
