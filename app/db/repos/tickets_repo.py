"""
Repository for tickets_current and tickets_done.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def _fio(u: Any) -> Optional[str]:
    if not isinstance(u, dict):
        return None
    fio = u.get("fio")
    if fio:
        return str(fio)
    first = (u.get("firstname") or "").strip()
    last = (u.get("lastname") or "").strip()
    name = (first + " " + last).strip()
    if name:
        return name
    username = u.get("username")
    return str(username) if username else None


def _addr_full(a: Any) -> Optional[str]:
    if not isinstance(a, dict):
        return None
    fa = a.get("fullAddress")
    if fa:
        return str(fa)
    return None


def _cat_name(c: Any) -> Optional[str]:
    return str(c.get("name")) if isinstance(c, dict) and c.get("name") is not None else None


def _svc_name(s: Any) -> Optional[str]:
    return str(s.get("name")) if isinstance(s, dict) and s.get("name") is not None else None


def _executor_id(ticket: Dict[str, Any]) -> Optional[int]:
    ex = ticket.get("executor")
    if isinstance(ex, dict) and ex.get("id") is not None:
        try:
            return int(ex["id"])
        except Exception:
            return None
    return None


def current_exists(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    ).fetchone()
    return row is not None


def upsert_current(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    ticket: Dict[str, Any],
    track_kind: str = "USER",
) -> None:
    status = ticket.get("status")
    conn.execute(
        """
        INSERT INTO tickets_current (
            telegram_user_id, ticket_id, track_kind, executor_id,
            status, sla, title, description,
            created_ts, estimated_ts, closed_ts, last_updated_ts,
            executor_fio, author_fio, address_full, category_name, service_name,
            raw_json, updated_at, last_notified_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
        ON CONFLICT(telegram_user_id, ticket_id) DO UPDATE SET
            track_kind=excluded.track_kind,
            executor_id=excluded.executor_id,
            status=excluded.status,
            sla=excluded.sla,
            title=excluded.title,
            description=excluded.description,
            created_ts=excluded.created_ts,
            estimated_ts=excluded.estimated_ts,
            closed_ts=excluded.closed_ts,
            last_updated_ts=excluded.last_updated_ts,
            executor_fio=excluded.executor_fio,
            author_fio=excluded.author_fio,
            address_full=excluded.address_full,
            category_name=excluded.category_name,
            service_name=excluded.service_name,
            raw_json=excluded.raw_json,
            updated_at=datetime('now')
        ;
        """,
        (
            int(telegram_user_id),
            int(ticket["id"]),
            str(track_kind),
            _executor_id(ticket),
            status,
            ticket.get("sla"),
            ticket.get("title"),
            ticket.get("description"),
            ticket.get("createdTimestamp"),
            ticket.get("estimatedTimestamp"),
            ticket.get("closedTimestamp"),
            ticket.get("lastUpdatedTimestamp"),
            _fio(ticket.get("executor")),
            _fio(ticket.get("author")),
            _addr_full(ticket.get("address")),
            _cat_name(ticket.get("category")),
            _svc_name(ticket.get("service")),
            json.dumps(ticket, ensure_ascii=False),
            status,  # ✅ last_notified_status on INSERT
        ),
    )


def upsert_done(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    ticket: Dict[str, Any],
    track_kind: str = "USER",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tickets_done (
            telegram_user_id, ticket_id, track_kind, executor_id,
            status, sla, title, description,
            created_ts, estimated_ts, closed_ts, last_updated_ts,
            executor_fio, author_fio, address_full, category_name, service_name,
            raw_json, done_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
        """,
        (
            int(telegram_user_id),
            int(ticket["id"]),
            str(track_kind),
            _executor_id(ticket),
            ticket.get("status"),
            ticket.get("sla"),
            ticket.get("title"),
            ticket.get("description"),
            ticket.get("createdTimestamp"),
            ticket.get("estimatedTimestamp"),
            ticket.get("closedTimestamp"),
            ticket.get("lastUpdatedTimestamp"),
            _fio(ticket.get("executor")),
            _fio(ticket.get("author")),
            _addr_full(ticket.get("address")),
            _cat_name(ticket.get("category")),
            _svc_name(ticket.get("service")),
            json.dumps(ticket, ensure_ascii=False),
        ),
    )


def delete_current(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int) -> None:
    conn.execute(
        "DELETE FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    )


def delete_current_not_in_ids(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    track_kind: str,
    keep_ticket_ids: List[int],
) -> int:
    if keep_ticket_ids:
        placeholders = ",".join(["?"] * len(keep_ticket_ids))
        cur = conn.execute(
            f"""
            DELETE FROM tickets_current
            WHERE telegram_user_id=?
              AND track_kind=?
              AND ticket_id NOT IN ({placeholders});
            """,
            (int(telegram_user_id), str(track_kind), *[int(x) for x in keep_ticket_ids]),
        )
        return int(cur.rowcount)

    cur = conn.execute(
        """
        DELETE FROM tickets_current
        WHERE telegram_user_id=? AND track_kind=?;
        """,
        (int(telegram_user_id), str(track_kind)),
    )
    return int(cur.rowcount)


def mark_notified(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int, status: str) -> None:
    conn.execute(
        """
        UPDATE tickets_current
        SET last_notified_status = ?, updated_at = datetime('now')
        WHERE telegram_user_id = ? AND ticket_id = ?;
        """,
        (status, int(telegram_user_id), int(ticket_id)),
    )


def move_to_done(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int) -> None:
    row = conn.execute(
        "SELECT * FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    ).fetchone()
    if not row:
        return

    r = dict(row)

    conn.execute(
        """
        INSERT OR REPLACE INTO tickets_done (
            telegram_user_id, ticket_id, track_kind, executor_id,
            status, sla, title, description,
            created_ts, estimated_ts, closed_ts, last_updated_ts,
            executor_fio, author_fio, address_full, category_name, service_name,
            raw_json, done_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
        """,
        (
            r["telegram_user_id"],
            r["ticket_id"],
            r.get("track_kind"),
            r.get("executor_id"),
            r["status"],
            r["sla"],
            r["title"],
            r["description"],
            r["created_ts"],
            r["estimated_ts"],
            r["closed_ts"],
            r["last_updated_ts"],
            r["executor_fio"],
            r["author_fio"],
            r["address_full"],
            r["category_name"],
            r["service_name"],
            r["raw_json"],
        ),
    )

    conn.execute(
        "DELETE FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    )


def _where_track_kind(track_kind: Optional[str]) -> str:
    if not track_kind:
        return ""
    if str(track_kind).upper() == "USER":
        return " AND (track_kind IS NULL OR track_kind = 'USER')"
    return " AND track_kind = ?"


def list_current(conn: sqlite3.Connection, telegram_user_id: int, track_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    where_kind = _where_track_kind(track_kind)
    sql = f"""
        SELECT ticket_id, status, sla, title, executor_fio, address_full, updated_at
        FROM tickets_current
        WHERE telegram_user_id=?{where_kind}
        ORDER BY updated_at DESC;
    """
    params: Tuple[Any, ...]
    if not track_kind or str(track_kind).upper() == "USER":
        params = (int(telegram_user_id),)
    else:
        params = (int(telegram_user_id), str(track_kind))

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_done(conn: sqlite3.Connection, telegram_user_id: int, track_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    where_kind = _where_track_kind(track_kind)
    sql = f"""
        SELECT ticket_id, status, sla, title, executor_fio, address_full, done_at
        FROM tickets_done
        WHERE telegram_user_id=?{where_kind}
        ORDER BY done_at DESC;
    """
    params: Tuple[Any, ...]
    if not track_kind or str(track_kind).upper() == "USER":
        params = (int(telegram_user_id),)
    else:
        params = (int(telegram_user_id), str(track_kind))

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_current_row(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    ).fetchone()
    return dict(row) if row else None


def get_done_row(conn: sqlite3.Connection, telegram_user_id: int, ticket_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM tickets_done WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    ).fetchone()
    return dict(row) if row else None


def list_all_current_pairs(conn: sqlite3.Connection) -> List[Tuple[int, int, Optional[str]]]:
    rows = conn.execute(
        """
        SELECT telegram_user_id, ticket_id, last_notified_status
        FROM tickets_current;
        """
    ).fetchall()
    return [(int(r["telegram_user_id"]), int(r["ticket_id"]), r["last_notified_status"]) for r in rows]


def delete_done_older_than_days(conn: sqlite3.Connection, days: int) -> int:
    cur = conn.execute(
        f"DELETE FROM tickets_done WHERE done_at < datetime('now', '-{int(days)} days');"
    )
    return int(cur.rowcount)
