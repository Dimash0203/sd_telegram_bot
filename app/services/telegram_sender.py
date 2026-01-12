"""
Simple Telegram sender for workers (no PTB context needed).
"""

import httpx


def send_message(token: str, chat_id: int, text: str, timeout_seconds: int = 15) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    with httpx.Client(timeout=timeout_seconds) as client:
        r = client.post(url, json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram sendMessage failed: {r.status_code} {r.text}")
