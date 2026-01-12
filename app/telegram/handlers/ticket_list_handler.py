"""
Ticket list handler: shows current and done tickets from SQLite.
Role-aware:
- USER -> track_kind USER/NULL
- EXECUTOR -> track_kind EXECUTOR
- DISPATCHER -> track_kind DISPATCHER

UX note:
- "История заявок" = tickets_done за последние 30 дней (≈ месяц)
"""

from typing import Any, Dict

from app.db.repos.tickets_repo import list_current, list_done
from app.db.repos.users_repo import get_user
from app.services.notify_service import send_text


async def handle_my(deps: Dict[str, Any], telegram_user_id: int) -> None:
    u = get_user(deps["db"], telegram_user_id)
    sd_role = str((u or {}).get("sd_role") or "").upper()

    if sd_role == "EXECUTOR":
        current = list_current(deps["db"], telegram_user_id, track_kind="EXECUTOR")
        done = list_done(deps["db"], telegram_user_id, track_kind="EXECUTOR")

        lines = []
        lines.append("🛠 Назначенные мне заявки:")
        if not current:
            lines.append("— нет активных (обновите список: /work)")
        else:
            for r in current[:20]:
                tid = r.get("ticket_id")
                status = r.get("status") or "?"
                title = (r.get("title") or "").strip()
                addr = (r.get("address_full") or "").strip()
                line = f"#{tid} · {status}"
                if title:
                    line += f" · {title}"
                if addr:
                    line += f" · {addr}"
                lines.append(line)
            if len(current) > 20:
                lines.append(f"… и ещё {len(current) - 20}")

        lines.append("")
        lines.append("📚 История заявок (последние 30 дней):")
        if not done:
            lines.append("— нет записей за месяц")
        else:
            for r in done[:20]:
                tid = r.get("ticket_id")
                status = r.get("status") or "CLOSED"
                title = (r.get("title") or "").strip()
                done_at = (r.get("done_at") or "").strip()
                line = f"#{tid} · {status}"
                if title:
                    line += f" · {title}"
                if done_at:
                    line += f" · {done_at}"
                lines.append(line)
            if len(done) > 20:
                lines.append(f"… и ещё {len(done) - 20}")

        lines.append("")
        lines.append("Обновить список назначенных: /work")
        lines.append("Закрыть тикет: /done <id>")

        await send_text(deps, "\n".join(lines))
        return

    if sd_role == "DISPATCHER":
        current = list_current(deps["db"], telegram_user_id, track_kind="DISPATCHER")
        done = list_done(deps["db"], telegram_user_id, track_kind="DISPATCHER")

        lines = []
        lines.append("📍 Текущие тикеты по локации (локально):")
        if not current:
            lines.append("— нет активных (обновите список: «📍 Тикеты по локации»)")
        else:
            for r in current[:20]:
                tid = r.get("ticket_id")
                status = r.get("status") or "?"
                title = (r.get("title") or "").strip()
                addr = (r.get("address_full") or "").strip()
                line = f"#{tid} · {status}"
                if title:
                    line += f" · {title}"
                if addr:
                    line += f" · {addr}"
                lines.append(line)
            if len(current) > 20:
                lines.append(f"… и ещё {len(current) - 20}")

        lines.append("")
        lines.append("📚 История заявок (последние 30 дней):")
        if not done:
            lines.append("— нет записей за месяц")
        else:
            for r in done[:20]:
                tid = r.get("ticket_id")
                status = r.get("status") or "CLOSED"
                title = (r.get("title") or "").strip()
                done_at = (r.get("done_at") or "").strip()
                line = f"#{tid} · {status}"
                if title:
                    line += f" · {title}"
                if done_at:
                    line += f" · {done_at}"
                lines.append(line)
            if len(done) > 20:
                lines.append(f"… и ещё {len(done) - 20}")

        await send_text(deps, "\n".join(lines))
        return

    # USER (default)
    current = list_current(deps["db"], telegram_user_id, track_kind="USER")
    done = list_done(deps["db"], telegram_user_id, track_kind="USER")

    lines = []
    lines.append("📌 Текущие заявки:")
    if not current:
        lines.append("— нет активных заявок")
    else:
        for r in current[:20]:
            tid = r.get("ticket_id")
            status = r.get("status") or "?"
            title = (r.get("title") or "").strip()
            addr = (r.get("address_full") or "").strip()

            line = f"#{tid} · {status}"
            if title:
                line += f" · {title}"
            if addr:
                line += f" · {addr}"
            lines.append(line)

        if len(current) > 20:
            lines.append(f"… и ещё {len(current) - 20}")

    lines.append("")
    lines.append("📚 История заявок (последние 30 дней):")
    if not done:
        lines.append("— нет записей за месяц")
    else:
        for r in done[:20]:
            tid = r.get("ticket_id")
            status = r.get("status") or "CLOSED"
            title = (r.get("title") or "").strip()
            done_at = (r.get("done_at") or "").strip()

            line = f"#{tid} · {status}"
            if title:
                line += f" · {title}"
            if done_at:
                line += f" · {done_at}"
            lines.append(line)

        if len(done) > 20:
            lines.append(f"… и ещё {len(done) - 20}")

    await send_text(deps, "\n".join(lines))
