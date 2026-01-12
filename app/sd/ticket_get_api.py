"""
Service Desk: get ticket by id.
"""

from typing import Any, Dict

from app.sd.client import SDClient


def get_ticket(client: SDClient, token: str, ticket_id: int) -> Dict[str, Any]:
    resp = client.get(f"/ticket/{ticket_id}", token=token)
    if resp.status_code != 200:
        raise RuntimeError(f"SD get_ticket failed: {resp.status_code} {resp.text}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("SD get_ticket returned non-object JSON")
    return data
