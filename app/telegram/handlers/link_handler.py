"""
Account linking flow: /link -> username -> password -> authenticate.
Stores password (plaintext) + user location for DISPATCHER filtering.
"""

from typing import Any, Dict

from loguru import logger

from app.db.repos.sessions_repo import upsert_session, get_session, delete_session
from app.db.repos.users_repo import upsert_user, set_location
from app.services.notify_service import send_text
from app.sd.client import SDClient
from app.sd.auth_api import authenticate
from app.sd.users_api import get_user
from app.telegram.handlers.start_handler import handle_start


async def handle_link(deps: Dict[str, Any], telegram_user_id: int) -> None:
    upsert_session(deps["db"], telegram_user_id, "LINK_USERNAME", {"link": {}})
    await send_text(deps, "Введите логин (username/email) для ServiceDesk:")


async def handle_link_text(deps: Dict[str, Any], telegram_user_id: int, text: str) -> bool:
    session = get_session(deps["db"], telegram_user_id)
    if not session:
        return False

    state = session["state"]
    data = session["data"]
    link = data.get("link", {})

    t = text.strip()
    if not t:
        await send_text(deps, "Пожалуйста, отправьте текст.")
        return True

    if state == "LINK_USERNAME":
        link["username"] = t
        upsert_session(deps["db"], telegram_user_id, "LINK_PASSWORD", {"link": link})
        await send_text(deps, "Введите пароль ServiceDesk:")
        return True

    if state == "LINK_PASSWORD":
        username = str(link.get("username") or "")
        password = t

        client = SDClient(
            base_url=deps["settings"].sd_base_url,
            api_prefix=deps["settings"].sd_api_prefix,
            timeout_seconds=deps["settings"].http_timeout_seconds,
        )

        try:
            result = authenticate(client, username=username, password=password)
        except Exception as e:
            logger.exception("SD authenticate failed: {}", e)
            delete_session(deps["db"], telegram_user_id)
            await send_text(deps, "Ошибка авторизации. Попробуйте снова: /link")
            return True

        upsert_user(
            deps["db"],
            telegram_user_id=telegram_user_id,
            sd_user_id=result.sd_user_id,
            sd_username=result.username,
            sd_role=result.role,
            sd_token=result.token,
            sd_password=password,
        )

        try:
            prof = get_user(client, user_id=result.sd_user_id, token=result.token)
            if prof.address:
                set_location(
                    deps["db"],
                    telegram_user_id=telegram_user_id,
                    region=prof.address.region,
                    location=prof.address.location,
                    full_address=prof.address.full_address,
                    address_id=prof.address.id,
                )
        except Exception as e:
            logger.warning("Failed to fetch/store user profile location: {}", e)

        delete_session(deps["db"], telegram_user_id)

        await handle_start(deps, telegram_user_id)
        return True

    return False
