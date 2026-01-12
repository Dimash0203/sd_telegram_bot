ServiceDesk ↔ Telegram Bot (VS)

## Назначение
Telegram-бот интегрируется с ServiceDesk (SD) по REST API и:
- создаёт заявки (USER)
- показывает назначенные заявки и закрывает их (EXECUTOR)
- показывает заявки по локации (DISPATCHER)
- хранит токены/состояния/историю локально в SQLite
- имеет локальный web UI (front) для администрирования SQLite

## Роли (меню и действия)
| Роль | Основные команды | Что делает |
|---|---|---|
| USER | /link, /new, /my | Авторизация, создание заявки, просмотр текущих/истории (локально) |
| EXECUTOR | /link, /work, /done `<id>`, /my | Просмотр назначенных, закрытие тикетов (SD PUT /ticket/status/{id}), уведомления и синхронизация |
| DISPATCHER | /link, /my | Просмотр тикетов по локации (region+location из SD /users/{id}), уведомления и синхронизация по SD /ticket list |
| ADMIN | /admin | Видит списки пользователей/исполнителей/диспетчеров и управляет ими (админ-операции по текущей реализации) |

## Ключевая логика (Workers)
- PollerWorker — отслеживает статусы тикетов из tickets_current через SD GET /ticket/{id}
- ExecutorSyncWorker — синхронизирует назначенные исполнителю тикеты через SD /ticket list
- DispatcherSyncWorker — синхронизирует тикеты по локации через SD /ticket list (фильтрация на стороне бота)
- ReauthWorker — авто-перелогин (обновление sd_token) по сохранённым username/password
- CleanupWorker — TTL сессий + очистка tickets_done (и опционально VACUUM)

## Хранилище (SQLite)
- Файл: data/bot.sqlite3 (НЕ коммитить в git)
- Таблицы: telegram_users, sessions, tickets_current, tickets_done, app_kv
- sd_password хранится в plaintext (по требованию) — осознанный риск

## Front UI
- Локальный веб-интерфейс для просмотра/управления SQLite
- По умолчанию: http://127.0.0.1:8010

## Запуск
1) Настроить .env  
2) python main.py

## ENV 
| Переменная | Пример | Назначение                              |
|---|---|-----------------------------------------|
| TELEGRAM_BOT_TOKEN | 123:ABC... | Токен Telegram бота                     |
| SD_BASE_URL | http://10.200.200.1:8081 | Основной адрес ServiceDesk (обязателен) |
| SD_API_PREFIX | /api/v1 | Префикс API SD                          |
| SQLITE_PATH | ./data/bot.sqlite3 | Путь к локальной SQLite базе            |
