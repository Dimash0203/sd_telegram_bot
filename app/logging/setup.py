"""
Loguru logging setup for the application.
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_level: str, app_env: str) -> None:
    logger.remove()

    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    logger.add(
        logs_dir / f"app_{app_env}.log",
        level=log_level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
    )
