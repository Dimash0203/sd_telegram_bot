"""
Service Desk users API.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.sd.client import SDClient


@dataclass(frozen=True)
class Address:
    id: int
    full_address: Optional[str]
    region: Optional[str]
    location: Optional[str]


@dataclass(frozen=True)
class UserProfile:
    id: int
    username: str
    role: str
    address: Optional[Address]
    raw: Dict[str, Any]


def get_user(client: SDClient, user_id: int, token: str) -> UserProfile:
    resp = client.get(f"/users/{user_id}", token=token)
    if resp.status_code != 200:
        raise RuntimeError(f"SD get_user failed: {resp.status_code} {resp.text}")

    data = resp.json()
    addr = data.get("address")
    address = None
    if isinstance(addr, dict) and addr.get("id") is not None:
        address = Address(
            id=int(addr["id"]),
            full_address=addr.get("fullAddress"),
            region=addr.get("region"),
            location=addr.get("location"),
        )

    return UserProfile(
        id=int(data["id"]),
        username=str(data.get("username") or ""),
        role=str(data.get("role") or ""),
        address=address,
        raw=data,
    )
