#!/usr/bin/env python3
"""
view_db.py — standalone SQLite viewer + CSV exporter for the ServiceDesk ↔ Telegram bot.

Default behavior:
- Prints tables + schema + rows (limited)
- Exports each table into CSV files in the same folder as this script (app/db)

Usage examples:
  # from anywhere (uses SQLITE_PATH env if set):
  python app/db/view_db.py

  # explicit db:
  python app/db/view_db.py --db .\data\bot.sqlite3

  # disable CSV export:
  python app/db/view_db.py --no-csv

  # export only specific tables:
  python app/db/view_db.py --tables telegram_users sessions --csv

  # export all rows to CSV (careful if huge):
  python app/db/view_db.py --csv --csv-max-rows 0

Notes:
- If SQLITE_PATH is relative (e.g. ./data/bot.sqlite3), it is resolved relative to project root,
  not current working directory (PyCharm often runs from app/db).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_DB_CANDIDATES = [
    Path("data") / "bot.sqlite3",
    Path("bot.sqlite3"),
    Path("data") / "bot.db",
]

JSONISH_COLUMNS = {"data_json", "raw_json"}


def _find_project_root(start: Path) -> Path:
    """
    Heuristic: walk up from start until we find a folder that looks like project root.
    Signals: main.py OR data/ folder OR .env
    """
    start = start.resolve()
    for p in [start] + list(start.parents):
        if (p / "main.py").exists():
            return p
        if (p / ".env").exists():
            return p
        if (p / "data").exists():
            return p
    # fallback: parent of script dir
    return start.parents[0] if start.parents else start


def _resolve_db_path(cli_db: Optional[str], script_dir: Path) -> Path:
    if cli_db:
        p = Path(cli_db)
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    env_db = os.environ.get("SQLITE_PATH")
    if env_db:
        p = Path(env_db)
        if p.is_absolute():
            return p
        # Resolve relative SQLITE_PATH from project root (not CWD)
        project_root = _find_project_root(script_dir)
        return (project_root / p).resolve()

    # Try typical defaults relative to project root
    project_root = _find_project_root(script_dir)
    for rel in DEFAULT_DB_CANDIDATES:
        cand = (project_root / rel).resolve()
        if cand.exists():
            return cand

    # fallback to first candidate under project root
    return (project_root / DEFAULT_DB_CANDIDATES[0]).resolve()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _get_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
        """
    ).fetchall()
    return [str(r["name"]) for r in rows]


def _get_table_schema(conn: sqlite3.Connection, table: str) -> Optional[str]:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?;",
        (table,),
    ).fetchone()
    return str(row["sql"]) if row and row["sql"] else None


def _get_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return [str(r["name"]) for r in rows]


def _try_pretty_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, (str, bytes)):
        return None
    try:
        s = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        obj = json.loads(s)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return None


def _json_one_line(value: Any) -> Optional[str]:
    """For CSV: keep JSON as one line if it's valid JSON; otherwise None."""
    if value is None:
        return None
    if not isinstance(value, (str, bytes)):
        return None
    try:
        s = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        obj = json.loads(s)
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return None


def _format_cell_for_console(col: str, val: Any, max_width: int) -> str:
    if val is None:
        return "NULL"

    if col in JSONISH_COLUMNS:
        pretty = _try_pretty_json(val)
        if pretty is not None:
            return pretty  # multiline ok for console printing

    s = str(val)
    if max_width > 0 and len(s) > max_width:
        s = s[: max_width - 3] + "..."
    return s


def _format_cell_for_csv(col: str, val: Any) -> str:
    if val is None:
        return ""
    if col in JSONISH_COLUMNS:
        one = _json_one_line(val)
        if one is not None:
            return one
    # ensure no weird binary
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return str(val).replace("\r\n", "\n")


def _print_hr(char: str = "-", width: int = 100) -> None:
    print(char * width)


def _print_section(title: str) -> None:
    _print_hr("=")
    print(title)
    _print_hr("=")


def _print_table_rows(conn: sqlite3.Connection, table: str, limit: int, max_width: int) -> None:
    cols = _get_columns(conn, table)
    try:
        rows = conn.execute(f"SELECT * FROM {table} LIMIT ?;", (limit,)).fetchall()
    except Exception as e:
        print(f"[ERROR] Failed to read table '{table}': {e}")
        return

    print(f"Rows (up to {limit}): {len(rows)}")
    if not rows:
        return

    for i, r in enumerate(rows, start=1):
        _print_hr("-", 80)
        print(f"{table} — row #{i}")
        for c in cols:
            val = r[c]
            formatted = _format_cell_for_console(c, val, max_width=max_width)
            if "\n" in formatted:
                print(f"{c}:")
                for line in formatted.splitlines():
                    print(f"  {line}")
            else:
                print(f"{c}: {formatted}")


def _export_table_csv(
    conn: sqlite3.Connection,
    table: str,
    out_dir: Path,
    max_rows: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{table}.csv"

    cols = _get_columns(conn, table)

    if max_rows and max_rows > 0:
        q = f"SELECT * FROM {table} LIMIT ?;"
        params = (max_rows,)
    else:
        q = f"SELECT * FROM {table};"
        params = ()

    rows = conn.execute(q, params).fetchall()

    # UTF-8 with BOM so Excel opens correctly
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_format_cell_for_csv(c, r[c]) for c in cols])

    return out_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="View contents of bot SQLite database (and export to CSV).")
    ap.add_argument("--db", help="Path to SQLite DB file (e.g., data/bot.sqlite3). If omitted uses SQLITE_PATH.")
    ap.add_argument("--tables", nargs="*", help="Optional list of tables to show/export (default: all).")
    ap.add_argument("--limit", type=int, default=200, help="Max rows per table to print (default: 200).")
    ap.add_argument("--max-width", type=int, default=180, help="Max width for non-JSON cell values (default: 180). 0 = no trunc.")
    ap.add_argument("--no-schema", action="store_true", help="Do not print CREATE TABLE schema blocks.")

    # CSV export
    ap.add_argument("--csv", action="store_true", help="Export selected tables to CSV (default ON).")
    ap.add_argument("--no-csv", action="store_true", help="Disable CSV export.")
    ap.add_argument("--csv-dir", help="Directory to write CSVs into (default: same folder as this script).")
    ap.add_argument("--csv-max-rows", type=int, default=0, help="Max rows per table in CSV. 0 = all rows (default).")

    args = ap.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    db_path = _resolve_db_path(args.db, script_dir=script_dir)

    # default: export CSV unless explicitly disabled
    export_csv = True
    if args.no_csv:
        export_csv = False
    if args.csv:
        export_csv = True

    csv_dir = Path(args.csv_dir).resolve() if args.csv_dir else script_dir

    _print_section("SQLite DB Viewer")
    print(f"CWD:     {Path.cwd().resolve()}")
    print(f"Script:  {Path(__file__).resolve()}")
    print(f"DB path: {db_path}")

    if not db_path.exists():
        print("[ERROR] DB file does not exist.")
        print("Tip: if SQLITE_PATH=./data/bot.sqlite3, this script resolves it from project root automatically.")
        print("You can also run: python app/db/view_db.py --db .\\data\\bot.sqlite3")
        return 2

    conn = _connect(db_path)
    try:
        tables = _get_tables(conn)
        if not tables:
            print("[WARN] No tables found.")
            return 0

        wanted = args.tables if args.tables else tables
        wanted_existing = []
        for t in wanted:
            if t in tables:
                wanted_existing.append(t)
            else:
                print(f"[WARN] Table not found: {t}")

        _print_section("Tables")
        for t in tables:
            print(f"- {t}")

        # Export CSV first (so even if console printing is huge, you already get files)
        if export_csv:
            _print_section(f"CSV export → {csv_dir}")
            for t in wanted_existing:
                try:
                    out_path = _export_table_csv(conn, t, out_dir=csv_dir, max_rows=args.csv_max_rows)
                    print(f"[OK] {t} -> {out_path.name}")
                except Exception as e:
                    print(f"[ERROR] Failed exporting {t}: {e}")

        # Console print
        for t in wanted_existing:
            _print_section(f"TABLE: {t}")
            if not args.no_schema:
                schema = _get_table_schema(conn, t)
                print("Schema:")
                print(schema or "(no schema found in sqlite_master)")
            _print_table_rows(conn, t, limit=args.limit, max_width=args.max_width)

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
