"""
Service Desk authentication.
"""

from dataclasses import dataclass
from typing import Any, Dict

from app.sd.client import SDClient


@dataclass(frozen=True)
class AuthResult:
    sd_user_id: int
    username: str
    role: str
    token: str
    raw: Dict[str, Any]


def authenticate(client: SDClient, username: str, password: str) -> AuthResult:
    resp = client.post(
        "/auth/authenticate",
        json={"username": username, "password": password},
        token=None,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"SD auth failed: {resp.status_code} {resp.text}")

    data = resp.json()
    sd_user_id = int(data.get("userId") or data.get("id"))
    role = str(data.get("role") or "")
    token = str(data.get("token") or "")
    if not token:
        raise RuntimeError("SD auth failed: token missing in response")

    return AuthResult(
        sd_user_id=sd_user_id,
        username=str(data.get("username") or username),
        role=role,
        token=token,
        raw=data,
    )
