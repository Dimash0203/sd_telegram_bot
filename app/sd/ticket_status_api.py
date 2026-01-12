"""
Service Desk: update ticket status.
PUT /ticket/status/{id} with full ticket body.
"""

from typing import Any, Dict

from app.sd.client import SDClient


def update_ticket_status(
    client: SDClient,
    token: str,
    ticket_id: int,
    ticket_payload: Dict[str, Any],
) -> None:
    resp = client.put(f"/ticket/status/{int(ticket_id)}", json=ticket_payload, token=token)
    if resp.status_code != 200:
        raise RuntimeError(f"SD update_ticket_status failed: {resp.status_code} {resp.text}")
