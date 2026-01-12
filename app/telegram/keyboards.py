"""
Telegram keyboards (reply menu buttons).
"""

from telegram import ReplyKeyboardMarkup, KeyboardButton


def kb_unauth() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔐 Авторизоваться")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def kb_executor() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🛠 Назначенные")],
            [KeyboardButton("📚 История заявок"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def kb_dispatcher() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Тикеты по локации")],
            [KeyboardButton("📚 История заявок"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def kb_user() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🆕 Новая заявка")],
            [KeyboardButton("📚 История заявок"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def kb_admin() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("👥 Пользователи")],
            [KeyboardButton("🧑‍🔧 Исполнители")],
            [KeyboardButton("🧑‍💼 Диспетчеры")],
            [KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
