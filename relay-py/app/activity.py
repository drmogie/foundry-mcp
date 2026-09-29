"""A short history of what each API token did. Only writes are kept."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

KEEP = 1000  # rows kept; older ones are dropped
MAX_SUMMARY = 300


def summarize(kind: str, data: dict[str, Any]) -> str:
    """One short line. Never the whole payload, so big documents do not fill the log."""
    parts = []
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            text = json.dumps(value, separators=(",", ":"), default=str)
        else:
            text = str(value)
        parts.append(f"{key}={text[:60]}")
    return (kind + " " + " ".join(parts))[:MAX_SUMMARY]


class ActivityLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS activity ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, token_id INTEGER, token_name TEXT, "
                "world_id TEXT, kind TEXT, summary TEXT, ok INTEGER, error TEXT)"
            )
            self._db.commit()

    def add(self, *, token_id: int, token_name: str, world_id: str | None, kind: str,
            data: dict[str, Any], ok: bool, error: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO activity (at, token_id, token_name, world_id, kind, summary, ok, error) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), token_id, token_name, world_id, kind, summarize(kind, data), 1 if ok else 0,
                 (error or "")[:300] or None),
            )
            self._db.execute(
                "DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - ?", (KEEP,)
            )
            self._db.commit()

    def recent(self, limit: int = 50, token_name: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        where, args = [], []
        if token_name:
            where.append("token_name = ?")
            args.append(token_name)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        sql = "SELECT id, at, token_id, token_name, world_id, kind, summary, ok, error FROM activity"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        return [
            {"id": r[0], "at": r[1], "tokenId": r[2], "token": r[3], "worldId": r[4], "kind": r[5],
             "summary": r[6], "ok": bool(r[7]), "error": r[8]}
            for r in rows
        ]
