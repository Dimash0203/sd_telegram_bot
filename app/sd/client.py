"""
HTTP client for Service Desk API.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


class SDUnauthorizedError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"SD unauthorized: {status_code} {body}")
        self.status_code = int(status_code)
        self.body = str(body or "")


@dataclass
class SDClient:
    base_url: str
    api_prefix: str
    timeout_seconds: int

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        prefix = (self.api_prefix or "").strip()
        if prefix and not prefix.startswith("/"):
            prefix = "/" + prefix
        prefix = prefix.rstrip("/")
        path = path if path.startswith("/") else "/" + path
        return f"{base}{prefix}{path}"

    def _headers(self, token: Optional[str], json: bool = False) -> Dict[str, str]:
        h: Dict[str, str] = {"accept": "*/*"}
        if json:
            h["Content-Type"] = "application/json"
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _raise_if_unauthorized(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise SDUnauthorizedError(resp.status_code, resp.text)

    def post(self, path: str, json: Dict[str, Any], token: Optional[str] = None) -> httpx.Response:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(self._url(path), headers=self._headers(token, json=True), json=json)
        self._raise_if_unauthorized(resp)
        return resp

    def put(self, path: str, json: Dict[str, Any], token: Optional[str] = None) -> httpx.Response:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.put(self._url(path), headers=self._headers(token, json=True), json=json)
        self._raise_if_unauthorized(resp)
        return resp

    def get(self, path: str, token: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.get(self._url(path), headers=self._headers(token, json=False), params=params)
        self._raise_if_unauthorized(resp)
        return resp
