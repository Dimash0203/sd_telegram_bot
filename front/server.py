"""
Front server runner (uvicorn in background thread).
"""

import threading
from typing import Optional

import uvicorn
from loguru import logger

from front.config import load_front_settings


class FrontServer:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None

    def start(self) -> None:
        s = load_front_settings()

        cfg = uvicorn.Config(
            "front.app:app",
            host=s.host,
            port=int(s.port),
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(cfg)

        def _run() -> None:
            try:
                self._server.run()
            except Exception as e:
                logger.error("Front UI crashed: {}", e)

        self._thread = threading.Thread(target=_run, name="front_ui", daemon=True)
        self._thread.start()
        logger.info("Front UI started on http://{}:{}", s.host, s.port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Front UI stopped")
