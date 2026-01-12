"""
SQLite schema initialization with minimal migrations.
"""

import sqlite3


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_users (
            telegram_user_id INTEGER PRIMARY KEY,
            sd_user_id INTEGER NOT NULL,
            role TEXT,
            linked_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    _ensure_column(conn, "telegram_users", "sd_username", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_role", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_token", "TEXT")
    _ensure_column(conn, "telegram_users", "token_updated_at", "TEXT")
    _ensure_column(conn, "telegram_users", "tg_chat_id", "INTEGER")

    # ✅ NEW: plaintext password + location fields
    _ensure_column(conn, "telegram_users", "sd_password", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_region", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_location", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_full_address", "TEXT")
    _ensure_column(conn, "telegram_users", "sd_address_id", "INTEGER")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            telegram_user_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            data_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets_current (
            telegram_user_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            track_kind TEXT,
            executor_id INTEGER,

            status TEXT,
            sla TEXT,
            title TEXT,
            description TEXT,
            created_ts INTEGER,
            estimated_ts INTEGER,
            closed_ts INTEGER,
            last_updated_ts INTEGER,
            executor_fio TEXT,
            author_fio TEXT,
            address_full TEXT,
            category_name TEXT,
            service_name TEXT,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_notified_status TEXT,
            PRIMARY KEY (telegram_user_id, ticket_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_current_user ON tickets_current(telegram_user_id);")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets_done (
            telegram_user_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            track_kind TEXT,
            executor_id INTEGER,

            status TEXT,
            sla TEXT,
            title TEXT,
            description TEXT,
            created_ts INTEGER,
            estimated_ts INTEGER,
            closed_ts INTEGER,
            last_updated_ts INTEGER,
            executor_fio TEXT,
            author_fio TEXT,
            address_full TEXT,
            category_name TEXT,
            service_name TEXT,
            raw_json TEXT NOT NULL,
            done_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (telegram_user_id, ticket_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_done_user ON tickets_done(telegram_user_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_done_done_at ON tickets_done(done_at);")

    _ensure_column(conn, "tickets_current", "track_kind", "TEXT")
    _ensure_column(conn, "tickets_current", "executor_id", "INTEGER")
    _ensure_column(conn, "tickets_done", "track_kind", "TEXT")
    _ensure_column(conn, "tickets_done", "executor_id", "INTEGER")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_kv (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()]
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type};")
