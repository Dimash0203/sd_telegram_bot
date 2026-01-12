"""
Telegram runtime: long-polling with full inbound update logging.
"""

import asyncio
import json
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from app.telegram.router import Router


@dataclass
class TelegramApp:
    deps: Dict[str, Any]

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="telegram", daemon=True)
        self._router = Router(self.deps)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._app: Optional[Application] = None
        self._shutdown_started = False

    def start(self) -> None:
        self._thread.start()
        logger.info("Telegram app started (dry_run={})", self.deps["settings"].dry_run)

    def stop(self) -> None:
        # ✅ Do NOT schedule shutdown here; let the polling loop exit and call _shutdown once.
        self._stop.set()
        self._thread.join(timeout=10)
        logger.info("Telegram app stopped")

    def _run(self) -> None:
        if self.deps["settings"].dry_run:
            self._dry_loop()
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_polling())

    async def _run_polling(self) -> None:
        token = self.deps["settings"].telegram_bot_token
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN is empty")
            return

        self._app = Application.builder().token(token).build()

        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("help", self._on_help))
        self._app.add_handler(CommandHandler("link", self._on_link))
        self._app.add_handler(CommandHandler("new", self._on_new))
        self._app.add_handler(CommandHandler("my", self._on_my))
        self._app.add_handler(CommandHandler("cancel", self._on_cancel))
        self._app.add_handler(CommandHandler("work", self._on_work))
        self._app.add_handler(CommandHandler("done", self._on_done))
        self._app.add_handler(CommandHandler("admin", self._on_admin))  # ✅ NEW

        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        await self._app.initialize()
        await self._app.start()

        # start_polling may not be running if startup fails later; shutdown must handle that
        await self._app.updater.start_polling(allowed_updates=["message", "callback_query"])
        logger.info("Telegram polling started")

        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.5)
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if not self._app:
            return

        try:
            # updater.stop can raise if not running: guard with try/except
            try:
                await self._app.updater.stop()
            except RuntimeError:
                pass

            try:
                await self._app.stop()
            except Exception:
                pass

            try:
                await self._app.shutdown()
            except Exception:
                pass

            logger.info("Telegram polling stopped")
        except Exception as e:
            logger.exception("Telegram shutdown error: {}", e)
        finally:
            self._app = None

    async def _on_start(self, update, context) -> None:
        self._log_update(update, command="/start")
        await self._router.handle_command(update, context, "/start")

    async def _on_help(self, update, context) -> None:
        self._log_update(update, command="/help")
        await self._router.handle_command(update, context, "/help")

    async def _on_link(self, update, context) -> None:
        self._log_update(update, command="/link")
        await self._router.handle_command(update, context, "/link")

    async def _on_new(self, update, context) -> None:
        self._log_update(update, command="/new")
        await self._router.handle_command(update, context, "/new")

    async def _on_my(self, update, context) -> None:
        self._log_update(update, command="/my")
        await self._router.handle_command(update, context, "/my")

    async def _on_cancel(self, update, context) -> None:
        self._log_update(update, command="/cancel")
        await self._router.handle_command(update, context, "/cancel")

    async def _on_work(self, update, context) -> None:
        self._log_update(update, command="/work")
        await self._router.handle_command(update, context, "/work")

    async def _on_done(self, update, context) -> None:
        text = update.message.text if update.message else ""
        self._log_update(update, command="/done", text=text)
        await self._router.handle_command(update, context, "/done")

    async def _on_admin(self, update, context) -> None:
        self._log_update(update, command="/admin")
        await self._router.handle_command(update, context, "/admin")

    async def _on_callback(self, update, context) -> None:
        q = getattr(update, "callback_query", None)
        data = q.data if q else None

        self._log_update(update, command="callback", text=str(data) if data is not None else None)

        try:
            await q.answer()
        except Exception:
            pass

        await self._router.handle_callback(update, context, str(data) if data is not None else "")

    async def _on_text(self, update, context) -> None:
        text = update.message.text if update.message else ""
        self._log_update(update, text=text)
        await self._router.handle_text(update, context, text)

    def _log_update(self, update, command: Optional[str] = None, text: Optional[str] = None) -> None:
        user = update.effective_user
        chat = update.effective_chat
        msg = getattr(update, "message", None)

        if msg is None:
            cq = getattr(update, "callback_query", None)
            if cq is not None:
                msg = getattr(cq, "message", None)

        payload = {
            "user_id": int(user.id) if user else None,
            "username": user.username if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "language_code": user.language_code if user else None,
            "chat_id": int(chat.id) if chat else None,
            "chat_type": chat.type if chat else None,
            "message_id": int(msg.message_id) if msg else None,
            "date": str(msg.date) if msg and msg.date else None,
            "command": command,
            "text": text,
        }

        logger.info("TG UPDATE: {}", json.dumps(payload, ensure_ascii=False))

    def _dry_loop(self) -> None:
        logger.info("DRY_RUN: Telegram loop running. Type 'start' to simulate /start, Ctrl+C to stop service.")
        while not self._stop.is_set():
            try:
                line = input().strip()
            except EOFError:
                return
            if not line:
                continue
            if line.lower() in ("start", "/start"):
                continue
