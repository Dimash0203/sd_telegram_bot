"""
Front: local admin UI for bot SQLite.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from front.config import load_front_settings
from front.db import (
    connect,
    exec_sql,
    fetch_one,
    list_tables,
    select_page,
    table_columns,
    table_count,
    vacuum,
)
from front.constants import SD_STATUSES, TERMINAL_STATUSES, is_allowed_status, norm_status, status_ru

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

S = load_front_settings()
DB = connect(S.sqlite_path)

TABLE_META: Dict[str, Dict[str, Any]] = {
    "telegram_users": {"pk": ["telegram_user_id"], "default_order": "linked_at"},
    "sessions": {"pk": ["telegram_user_id"], "default_order": "updated_at"},
    "tickets_current": {"pk": ["telegram_user_id", "ticket_id"], "default_order": "updated_at"},
    "tickets_done": {"pk": ["telegram_user_id", "ticket_id"], "default_order": "done_at"},
    "app_kv": {"pk": ["k"], "default_order": "updated_at"},
}


def _meta(table: str) -> Dict[str, Any]:
    return TABLE_META.get(table) or {"pk": [], "default_order": None}


def _safe_table(table: str) -> bool:
    return table in set(list_tables(DB))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    ts = list_tables(DB)
    cards = [{"name": t, "count": table_count(DB, t)} for t in ts]
    return templates.TemplateResponse("index.html", {"request": request, "tables": cards})


@app.get("/table/{table}", response_class=HTMLResponse)
def table_view(request: Request, table: str, page: int = 1, page_size: int = 50, order_by: Optional[str] = None, desc: int = 1):
    if not _safe_table(table):
        return HTMLResponse("Unknown table", status_code=404)

    page = max(1, int(page))
    page_size = min(200, max(10, int(page_size)))
    offset = (page - 1) * page_size

    cols = table_columns(DB, table)
    m = _meta(table)
    ob = order_by or m.get("default_order")
    rows = select_page(DB, table, limit=page_size, offset=offset, order_by=ob, desc=bool(int(desc)))

    total = table_count(DB, table)
    pages = max(1, (total + page_size - 1) // page_size)

    if table == "tickets_current":
        tpl = "tickets_current.html"
    elif table == "tickets_done":
        tpl = "tickets_done.html"
    else:
        tpl = "table.html"

    return templates.TemplateResponse(
        tpl,
        {
            "request": request,
            "table": table,
            "cols": cols,
            "rows": rows,
            "meta": m,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "total": total,
            "order_by": ob,
            "desc": int(desc),
            "statuses": SD_STATUSES,
            "status_ru": status_ru,
            "terminal_statuses": TERMINAL_STATUSES,
        },
    )


@app.post("/row/delete")
def row_delete(
    table: str = Form(...),
    pk_json: str = Form(...),
):
    if not _safe_table(table):
        return HTMLResponse("Unknown table", status_code=404)

    import json
    pk = json.loads(pk_json)
    m = _meta(table)
    pk_cols = m.get("pk") or []
    if not pk_cols:
        return HTMLResponse("No PK configured for table", status_code=400)

    where = " AND ".join([f"{c}=?" for c in pk_cols])
    params = tuple(pk.get(c) for c in pk_cols)
    exec_sql(DB, f"DELETE FROM {table} WHERE {where};", params)
    return RedirectResponse(url=f"/table/{table}", status_code=303)


@app.post("/table/clear")
def table_clear(
    table: str = Form(...),
    confirm: str = Form(""),
    do_vacuum: int = Form(0),
):
    if not _safe_table(table):
        return HTMLResponse("Unknown table", status_code=404)

    if confirm.strip() != table:
        return RedirectResponse(url=f"/table/{table}?err=confirm", status_code=303)

    exec_sql(DB, f"DELETE FROM {table};")
    if int(do_vacuum) == 1:
        vacuum(DB)
    return RedirectResponse(url=f"/table/{table}", status_code=303)


@app.post("/tickets/status")
def tickets_set_status(
    table: str = Form(...),  # tickets_current | tickets_done
    telegram_user_id: int = Form(...),
    ticket_id: int = Form(...),
    status: str = Form(...),
    set_notified: int = Form(0),
):
    if table not in ("tickets_current", "tickets_done"):
        return HTMLResponse("Bad table", status_code=400)
    if not _safe_table(table):
        return HTMLResponse("Unknown table", status_code=404)

    st = norm_status(status)
    if not is_allowed_status(st):
        return HTMLResponse("Bad status", status_code=400)

    if table == "tickets_current":
        if int(set_notified) == 1:
            exec_sql(
                DB,
                """
                UPDATE tickets_current
                SET status=?, last_notified_status=?, updated_at=datetime('now')
                WHERE telegram_user_id=? AND ticket_id=?;
                """,
                (st, st, int(telegram_user_id), int(ticket_id)),
            )
        else:
            exec_sql(
                DB,
                """
                UPDATE tickets_current
                SET status=?, updated_at=datetime('now')
                WHERE telegram_user_id=? AND ticket_id=?;
                """,
                (st, int(telegram_user_id), int(ticket_id)),
            )
    else:
        exec_sql(
            DB,
            """
            UPDATE tickets_done
            SET status=?, done_at=done_at
            WHERE telegram_user_id=? AND ticket_id=?;
            """,
            (st, int(telegram_user_id), int(ticket_id)),
        )

    return RedirectResponse(url=f"/table/{table}", status_code=303)


@app.post("/tickets/move_to_done")
def tickets_move_to_done(
    telegram_user_id: int = Form(...),
    ticket_id: int = Form(...),
):
    row = fetch_one(
        DB,
        "SELECT * FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    )
    if not row:
        return RedirectResponse(url="/table/tickets_current", status_code=303)

    exec_sql(
        DB,
        """
        INSERT OR REPLACE INTO tickets_done (
            telegram_user_id, ticket_id, track_kind, executor_id,
            status, sla, title, description,
            created_ts, estimated_ts, closed_ts, last_updated_ts,
            executor_fio, author_fio, address_full, category_name, service_name,
            raw_json, done_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
        """,
        (
            row.get("telegram_user_id"),
            row.get("ticket_id"),
            row.get("track_kind"),
            row.get("executor_id"),
            row.get("status"),
            row.get("sla"),
            row.get("title"),
            row.get("description"),
            row.get("created_ts"),
            row.get("estimated_ts"),
            row.get("closed_ts"),
            row.get("last_updated_ts"),
            row.get("executor_fio"),
            row.get("author_fio"),
            row.get("address_full"),
            row.get("category_name"),
            row.get("service_name"),
            row.get("raw_json"),
        ),
    )
    exec_sql(
        DB,
        "DELETE FROM tickets_current WHERE telegram_user_id=? AND ticket_id=?;",
        (int(telegram_user_id), int(ticket_id)),
    )
    return RedirectResponse(url="/table/tickets_current", status_code=303)


@app.post("/db/vacuum")
def db_vacuum():
    vacuum(DB)
    return RedirectResponse(url="/", status_code=303)
