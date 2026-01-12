"""
Repository for watched_tickets table (polling cache).
"""

import sqlite3
from typing import Optional, Dict, Any


def upsert_watch(
    conn: sqlite3.Connection,
    ticket_id: int,
    sd_user_id: int,
    last_status: str,
    last_seen_updated_at: Optional[str] = None,
) -> None:
    """Create or update watched ticket state."""
    conn.execute(
        """
        INSERT INTO watched_tickets (ticket_id, sd_user_id, last_status, last_seen_updated_at, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(ticket_id) DO UPDATE SET
            sd_user_id = excluded.sd_user_id,
            last_status = excluded.last_status,
            last_seen_updated_at = excluded.last_seen_updated_at,
            updated_at = datetime('now')
        ;
        """,
        (ticket_id, sd_user_id, last_status, last_seen_updated_at),
    )


def get_watch(conn: sqlite3.Connection, ticket_id: int) -> Optional[Dict[str, Any]]:
    """Return watched ticket row as dict or None."""
    row = conn.execute(
        """
        SELECT ticket_id, sd_user_id, last_status, last_seen_updated_at, last_notified_at, created_at, updated_at
        FROM watched_tickets
        WHERE ticket_id = ?;
        """,
        (ticket_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def mark_notified(conn: sqlite3.Connection, ticket_id: int) -> None:
    """Set last_notified_at to now for a ticket."""
    conn.execute(
        """
        UPDATE watched_tickets
        SET last_notified_at = datetime('now'), updated_at = datetime('now')
        WHERE ticket_id = ?;
        """,
        (ticket_id,),
    )


def delete_watch(conn: sqlite3.Connection, ticket_id: int) -> None:
    """Stop tracking a ticket."""
    conn.execute(
        "DELETE FROM watched_tickets WHERE ticket_id = ?;",
        (ticket_id,),
    )
