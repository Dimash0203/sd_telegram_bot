from app.bootstrap import build_app
from loguru import logger


def main() -> None:
    app = build_app()
    logger.info("Service started (dry_run={})", app["settings"].dry_run)
    app["runner"].run_forever()


if __name__ == "__main__":
    main()
