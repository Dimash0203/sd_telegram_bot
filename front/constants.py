"""
Front constants.
"""

SD_STATUSES = [
    "OPENED",
    "CLOSED",
    "INPROGRESS",
    "CANCELED",
    "REPAIR",
    "COMPLETED",
    "POSTPONED",
    "ACCEPTED",
]

STATUS_RU = {
    "OPENED": "ОТКРЫТ",
    "INPROGRESS": "В РАБОТЕ",
    "ACCEPTED": "ПРИНЯТ",
    "REPAIR": "НА РЕМОНТЕ",
    "POSTPONED": "ОТЛОЖЕН",
    "COMPLETED": "ВЫПОЛНЕНО",
    "CLOSED": "ЗАКРЫТ",
    "CANCELED": "ОТМЕНЁН",
}

TERMINAL_STATUSES = {"CLOSED", "COMPLETED", "CANCELED"}


def norm_status(x) -> str:
    return str(x or "").strip().upper()


def is_allowed_status(x) -> bool:
    return norm_status(x) in set(SD_STATUSES)


def status_ru(x) -> str:
    s = norm_status(x)
    return STATUS_RU.get(s) or (s if s else "?")
