"""
Repository for telegram_users table.
"""

import sqlite3
from typing import Optional, Dict, Any, List


def upsert_user(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    sd_user_id: int,
    sd_username: Optional[str],
    sd_role: Optional[str],
    sd_token: Optional[str],
    sd_password: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO telegram_users (
            telegram_user_id, sd_user_id, sd_username, sd_role, sd_token, token_updated_at, sd_password
        )
        VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            sd_user_id = excluded.sd_user_id,
            sd_username = excluded.sd_username,
            sd_role = excluded.sd_role,
            sd_token = excluded.sd_token,
            token_updated_at = datetime('now'),
            sd_password = COALESCE(excluded.sd_password, telegram_users.sd_password)
        ;
        """,
        (telegram_user_id, sd_user_id, sd_username, sd_role, sd_token, sd_password),
    )


def set_location(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    region: Optional[str],
    location: Optional[str],
    full_address: Optional[str],
    address_id: Optional[int],
) -> None:
    conn.execute(
        """
        UPDATE telegram_users
        SET sd_region = ?, sd_location = ?, sd_full_address = ?, sd_address_id = ?
        WHERE telegram_user_id = ?;
        """,
        (region, location, full_address, address_id, int(telegram_user_id)),
    )


def clear_sd_token(conn: sqlite3.Connection, telegram_user_id: int) -> None:
    conn.execute(
        """
        UPDATE telegram_users
        SET sd_token = NULL, token_updated_at = datetime('now')
        WHERE telegram_user_id = ?;
        """,
        (int(telegram_user_id),),
    )


def update_sd_token(conn: sqlite3.Connection, telegram_user_id: int, sd_token: str) -> None:
    conn.execute(
        """
        UPDATE telegram_users
        SET sd_token = ?, token_updated_at = datetime('now')
        WHERE telegram_user_id = ?;
        """,
        (sd_token, int(telegram_user_id)),
    )


def get_user(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT telegram_user_id, sd_user_id, sd_username, sd_role, sd_token, token_updated_at, linked_at,
               tg_chat_id, sd_password, sd_region, sd_location, sd_full_address, sd_address_id
        FROM telegram_users
        WHERE telegram_user_id = ?;
        """,
        (telegram_user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_sd_token(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT sd_token FROM telegram_users WHERE telegram_user_id = ?;",
        (telegram_user_id,),
    ).fetchone()
    if not row:
        return None
    return str(row["sd_token"]) if row["sd_token"] else None


def is_linked(conn: sqlite3.Connection, telegram_user_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM telegram_users
        WHERE telegram_user_id = ?
          AND sd_token IS NOT NULL AND sd_token <> '';
        """,
        (telegram_user_id,),
    ).fetchone()
    return row is not None


def get_sd_user_id(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT sd_user_id FROM telegram_users WHERE telegram_user_id = ?;",
        (telegram_user_id,),
    ).fetchone()
    return int(row["sd_user_id"]) if row else None


def set_chat_id(conn: sqlite3.Connection, telegram_user_id: int, chat_id: int) -> None:
    conn.execute(
        """
        UPDATE telegram_users
        SET tg_chat_id = ?
        WHERE telegram_user_id = ?;
        """,
        (chat_id, telegram_user_id),
    )


def get_chat_id(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT tg_chat_id FROM telegram_users WHERE telegram_user_id = ?;",
        (telegram_user_id,),
    ).fetchone()
    return int(row["tg_chat_id"]) if row and row["tg_chat_id"] is not None else None


def list_executors(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT telegram_user_id, sd_user_id, sd_username, sd_token, tg_chat_id
        FROM telegram_users
        WHERE upper(coalesce(sd_role,'')) = 'EXECUTOR'
          AND sd_token IS NOT NULL AND sd_token <> ''
          AND tg_chat_id IS NOT NULL;
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_dispatchers(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT telegram_user_id, sd_user_id, sd_username, sd_token, tg_chat_id,
               sd_region, sd_location, sd_full_address, sd_address_id, sd_password
        FROM telegram_users
        WHERE upper(coalesce(sd_role,'')) = 'DISPATCHER'
          AND sd_token IS NOT NULL AND sd_token <> ''
          AND tg_chat_id IS NOT NULL;
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_users_with_password(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT telegram_user_id, sd_user_id, sd_username, sd_role, sd_token, tg_chat_id,
               sd_password, sd_region, sd_location, sd_full_address, sd_address_id
        FROM telegram_users
        WHERE sd_username IS NOT NULL AND sd_username <> ''
          AND sd_password IS NOT NULL AND sd_password <> ''
          AND tg_chat_id IS NOT NULL;
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_people_by_role(conn: sqlite3.Connection, role_filter: str) -> List[Dict[str, Any]]:
    rf = (role_filter or "").upper().strip()

    # "зарегистрирован и залогинен" = есть token + chat_id
    base_where = """
        sd_token IS NOT NULL AND sd_token <> ''
        AND tg_chat_id IS NOT NULL
    """

    if rf == "USER":
        where_role = "(sd_role IS NULL OR sd_role = '' OR upper(sd_role) = 'USER')"
        sql = f"""
            SELECT telegram_user_id, sd_user_id, sd_username, sd_role, token_updated_at, linked_at, tg_chat_id,
                   sd_region, sd_location, sd_full_address, sd_address_id
            FROM telegram_users
            WHERE {base_where} AND {where_role}
            ORDER BY token_updated_at DESC, linked_at DESC;
        """
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    sql = f"""
        SELECT telegram_user_id, sd_user_id, sd_username, sd_role, token_updated_at, linked_at, tg_chat_id,
               sd_region, sd_location, sd_full_address, sd_address_id
        FROM telegram_users
        WHERE {base_where}
          AND upper(coalesce(sd_role,'')) = ?
        ORDER BY token_updated_at DESC, linked_at DESC;
    """
    rows = conn.execute(sql, (rf,)).fetchall()
    return [dict(r) for r in rows]
