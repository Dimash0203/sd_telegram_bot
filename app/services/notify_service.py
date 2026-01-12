"""
Telegram messaging helper.
"""

from typing import Any, Dict, Optional


async def send_text(
    deps: Dict[str, Any],
    text: str,
    reply_markup: Optional[Any] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
) -> None:
    chat_id = deps["tg"]["chat_id"]
    context = deps["tg"]["context"]
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )
