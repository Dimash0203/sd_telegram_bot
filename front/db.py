"""
SQLite helpers for front.
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def fetch_all(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def fetch_one(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def exec_sql(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> int:
    cur = conn.execute(sql, params)
    return int(cur.rowcount)


def list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = fetch_all(
        conn,
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;",
    )
    return [r["name"] for r in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = fetch_all(conn, f"PRAGMA table_info({table});")
    return [r["name"] for r in rows]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    row = fetch_one(conn, f"SELECT COUNT(*) AS c FROM {table};")
    return int((row or {}).get("c") or 0)


def select_page(
    conn: sqlite3.Connection,
    table: str,
    limit: int,
    offset: int,
    order_by: Optional[str] = None,
    desc: bool = True,
) -> List[Dict[str, Any]]:
    cols = table_columns(conn, table)
    ob = order_by if order_by in cols else None
    sql = f"SELECT * FROM {table}"
    if ob:
        sql += f" ORDER BY {ob} {'DESC' if desc else 'ASC'}"
    sql += " LIMIT ? OFFSET ?;"
    return fetch_all(conn, sql, (int(limit), int(offset)))


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.execute("VACUUM;")
