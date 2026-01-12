"""
Service Desk: list tickets (paged).
GET /ticket?page=0&size=25&type=VS&sort=id&asc=false
"""

from typing import Any, Dict

from app.sd.client import SDClient


def list_tickets_page(
    client: SDClient,
    token: str,
    page: int = 0,
    size: int = 25,
    type_: str = "VS",
    sort: str = "id",
    asc: bool = False,
) -> Dict[str, Any]:
    params = {
        "page": int(page),
        "size": int(size),
        "type": type_,
        "sort": sort,
        "asc": str(bool(asc)).lower(),  # backend expects "true"/"false"
    }
    resp = client.get("/ticket", token=token, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"SD list_tickets failed: {resp.status_code} {resp.text}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("SD list_tickets returned non-object JSON")
    return data
