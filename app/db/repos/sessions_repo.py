"""
Sessions repository.
"""

import json
import sqlite3
from typing import Any, Dict, Optional


def upsert_session(conn: sqlite3.Connection, telegram_user_id: int, state: str, data: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO sessions (telegram_user_id, state, data_json, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            state = excluded.state,
            data_json = excluded.data_json,
            updated_at = datetime('now')
        ;
        """,
        (telegram_user_id, state, json.dumps(data, ensure_ascii=False)),
    )


def get_session(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT telegram_user_id, state, data_json, updated_at
        FROM sessions
        WHERE telegram_user_id = ?;
        """,
        (telegram_user_id,),
    ).fetchone()
    if not row:
        return None
    return {"state": row["state"], "data": json.loads(row["data_json"]), "updated_at": row["updated_at"]}


def delete_session(conn: sqlite3.Connection, telegram_user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE telegram_user_id = ?;", (telegram_user_id,))


def delete_expired_sessions(conn: sqlite3.Connection, ttl_minutes: int) -> int:
    cur = conn.execute(
        f"DELETE FROM sessions WHERE updated_at < datetime('now', '-{int(ttl_minutes)} minutes');"
    )
    return int(cur.rowcount)
