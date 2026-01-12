"""
Service Desk ticket API + response parsing to user-friendly summary.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.sd.client import SDClient


@dataclass(frozen=True)
class TicketSummary:
    id: int
    title: str
    description: str
    status: Optional[str]
    sla: Optional[str]
    category: Optional[str]
    service: Optional[str]
    execution_timestamp: Optional[int]
    address: Optional[str]
    executor: Optional[str]
    author: Optional[str]
    company: Optional[str]
    contract: Optional[str]
    created_at: Optional[str]
    kind: Optional[str]
    type: Optional[str]


@dataclass(frozen=True)
class TicketCreateResult:
    summary: TicketSummary
    raw: Dict[str, Any]
    status_code: int


_ID_RE = re.compile(r'"id"\s*:\s*(\d+)')


def _ms_to_dt_str(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _fio(u: Optional[Dict[str, Any]]) -> Optional[str]:
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


def _full_address(addr: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(addr, dict):
        return None
    fa = addr.get("fullAddress")
    if fa:
        return str(fa)
    parts = []
    for k in ("region", "location", "building", "cabinet"):
        v = addr.get(k)
        if v:
            parts.append(str(v))
    return ", ".join(parts) if parts else None


def parse_ticket_summary(data: Dict[str, Any]) -> TicketSummary:
    ticket_id = int(data["id"])
    title = str(data.get("title") or "")
    description = str(data.get("description") or "")

    category = data.get("category") or {}
    service = data.get("service") or {}

    summary = TicketSummary(
        id=ticket_id,
        title=title,
        description=description,
        status=(str(data.get("status")) if data.get("status") is not None else None),
        sla=(str(data.get("sla")) if data.get("sla") is not None else None),
        category=(str(category.get("name")) if isinstance(category, dict) and category.get("name") is not None else None),
        service=(str(service.get("name")) if isinstance(service, dict) and service.get("name") is not None else None),
        execution_timestamp=(
            int(service.get("executionTimestamp"))
            if isinstance(service, dict) and service.get("executionTimestamp") is not None
            else None
        ),
        address=_full_address(data.get("address")),
        executor=_fio(data.get("executor")),
        author=_fio(data.get("author")),
        company=(str(data.get("company")) if data.get("company") is not None else None),
        contract=(str(data.get("contract")) if data.get("contract") is not None else None),
        created_at=_ms_to_dt_str(data.get("createdTimestamp")),
        kind=(str(data.get("kind")) if data.get("kind") is not None else None),
        type=(str(data.get("type")) if data.get("type") is not None else None),
    )
    return summary


def _extract_json_object_prefix(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.lstrip()
    if not s.startswith("{"):
        return None
    depth = 0
    for i, ch in enumerate(s):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[: i + 1]
    return None


def _try_parse_created_ticket(text: str) -> Optional[Dict[str, Any]]:
    prefix = _extract_json_object_prefix(text)
    if not prefix:
        return None
    try:
        return json.loads(prefix)
    except Exception:
        return None


def create_ticket(
    client: SDClient,
    token: str,
    title: str,
    description: str,
    author_id: int,
    address_id: int,
    category: Optional[Dict[str, Any]],
    service: Optional[Dict[str, Any]],
    kind: str = "TICKET_VS",
) -> TicketCreateResult:
    payload: Dict[str, Any] = {
        "title": title,
        "description": description,
        "author": {"id": author_id},
        "address": {"id": address_id},
        "kind": str(kind or "TICKET_VS"),
        "files": [],
        "executor": None,
    }

    # Only include category/service if provided (website tickets often send nulls)
    if category is not None:
        payload["category"] = category
    if service is not None:
        payload["service"] = service

    resp = client.post("/ticket", json=payload, token=token)
    text = resp.text or ""

    if resp.status_code in (200, 201):
        data = resp.json() if resp.content else {}
        if not isinstance(data, dict) or "id" not in data:
            raise RuntimeError(f"SD create_ticket unexpected response: {resp.status_code} {text}")
        summary = parse_ticket_summary(data)
        return TicketCreateResult(summary=summary, raw=data, status_code=resp.status_code)

    created = _try_parse_created_ticket(text)
    if created and isinstance(created, dict) and created.get("id") is not None:
        summary = parse_ticket_summary(created)
        return TicketCreateResult(summary=summary, raw=created, status_code=resp.status_code)

    m = _ID_RE.search(text)
    if m:
        ticket_id = int(m.group(1))
        minimal = {"id": ticket_id, "title": title, "description": description}
        summary = parse_ticket_summary(minimal)
        return TicketCreateResult(summary=summary, raw=minimal, status_code=resp.status_code)

    raise RuntimeError(f"SD create_ticket failed: {resp.status_code} {text}")
