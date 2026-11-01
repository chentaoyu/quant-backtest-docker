"""告警存储：SQLite（agent 独占的文件，不与 web 共享写入）。"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from agent.monitor.rules import LEVELS

DB_PATH = Path(os.getenv("MONITOR_DB", Path(__file__).resolve().parents[2] / "data" / "agent" / "monitor.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    rule TEXT NOT NULL,
    level TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    title TEXT NOT NULL,
    message TEXT,
    note TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_day ON alerts(day);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["data"] = json.loads(d["data"] or "{}")
    return d


def fired(day: str) -> dict[tuple, int]:
    """当天已报过的 (rule, symbol) -> 最高级别，用于去重/升级。"""
    with _conn() as conn:
        rows = conn.execute("SELECT rule, symbol, level FROM alerts WHERE day = ?", (day,)).fetchall()
    out: dict[tuple, int] = {}
    for r in rows:
        key = (r["rule"], r["symbol"])
        out[key] = max(out.get(key, -1), LEVELS[r["level"]])
    return out


def add(ts: str, day: str, alerts: list[dict]) -> list[dict]:
    with _conn() as conn:
        for a in alerts:
            cur = conn.execute(
                "INSERT INTO alerts (ts, day, rule, level, symbol, name, title, message, note, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, day, a["rule"], a["level"], a.get("symbol"), a.get("name"), a["title"], a.get("message"),
                 a.get("note"), json.dumps(a.get("data") or {}, ensure_ascii=False, default=str)),
            )
            a.update(id=cur.lastrowid, ts=ts, day=day)
    return alerts


def recent(limit: int = 100, since_id: int = 0, day: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM alerts WHERE id > ?", [since_id]
    if day:
        sql += " AND day = ?"
        args.append(day)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _conn() as conn:
        return [_row(r) for r in conn.execute(sql, args).fetchall()]


def max_id() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
