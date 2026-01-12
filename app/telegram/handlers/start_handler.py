"""
/start handler.
"""

from typing import Any, Dict

from loguru import logger

from app.db.repos.sessions_repo import upsert_session
from app.db.repos.users_repo import is_linked, get_user, upsert_user, clear_sd_token
from app.services.notify_service import send_text
from app.telegram.keyboards import kb_unauth, kb_executor, kb_user, kb_dispatcher, kb_admin

from app.sd.auth_api import authenticate
from app.sd.client import SDUnauthorizedError


def _try_startup_reauth(deps: Dict[str, Any], telegram_user_id: int) -> bool:
    """
    If token missing but creds exist, try to re-auth silently.
    """
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
        upsert_user(
            deps["db"],
            telegram_user_id=telegram_user_id,
            sd_user_id=int(r.sd_user_id),
            sd_username=str(r.username),
            sd_role=str(r.role),
            sd_token=str(r.token),
            sd_password=None,
        )
        logger.info("Start auto-reauth ok (tg_user_id={})", telegram_user_id)
        return True
    except SDUnauthorizedError:
        try:
            clear_sd_token(deps["db"], telegram_user_id)
        except Exception:
            pass
        return False
    except Exception as e:
        logger.warning("Start auto-reauth failed (tg_user_id={}): {}", telegram_user_id, e)
        return False


async def handle_start(deps: Dict[str, Any], telegram_user_id: int) -> None:
    upsert_session(
        deps["db"],
        telegram_user_id=telegram_user_id,
        state="IDLE",
        data={"menu": "root"},
    )

    linked = _try_startup_reauth(deps, telegram_user_id)

    if not linked:
        await send_text(
            deps,
            "Привет! Я бот ServiceDesk.\n\n"
            "Чтобы начать — нажмите кнопку ниже.\n"
            "Справка: /help",
            reply_markup=kb_unauth(),
        )
        return

    u = get_user(deps["db"], telegram_user_id) or {}
    role = str(u.get("sd_role") or "").upper()

    if role == "ADMIN":
        await send_text(
            deps,
            "Вы авторизованы как ADMIN.\n\n"
            "Откройте раздел (Пользователи/Исполнители/Диспетчеры), чтобы управлять доступом и тикетами.\n"
            "Справка: /help",
            reply_markup=kb_admin(),
        )
        return

    if role == "EXECUTOR":
        await send_text(
            deps,
            "Вы авторизованы как EXECUTOR.\n\n"
            "Нажмите «🛠 Назначенные», чтобы увидеть тикеты.\n"
            "Справка: /help",
            reply_markup=kb_executor(),
        )
        return

    if role == "DISPATCHER":
        await send_text(
            deps,
            "Вы авторизованы как Диспетчер.\n\n"
            "Нажмите «📍 Тикеты по локации», чтобы увидеть заявки вашей локации.\n"
            "Справка: /help",
            reply_markup=kb_dispatcher(),
        )
        return

    await send_text(
        deps,
        "Вы авторизованы.\n\n"
        "Нажмите «🆕 Новая заявка» или «📚 История заявок».\n"
        "Справка: /help",
        reply_markup=kb_user(),
    )
