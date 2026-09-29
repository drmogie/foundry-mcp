"""API tokens. Only a hash is stored, so a token can be shown once and never read back."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PREFIX = "fgat_"
SCOPES = ("read", "write")
TOUCH_EVERY = 30  # seconds between last-used writes


class TokenError(Exception):
    """A problem worded so a person can act on it."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Token:
    id: int
    name: str
    scope: str
    world_id: str | None
    created_at: float
    expires_at: float | None
    last_used_at: float | None
    hint: str

    def public(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "worldId": self.world_id,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "expired": self.expires_at is not None and self.expires_at <= now,
            "lastUsedAt": self.last_used_at,
            "hint": self.hint,
        }

    def allows(self, needed: str) -> bool:
        return needed == "read" or self.scope == "write"


class TokenStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    hash TEXT NOT NULL UNIQUE,
                    hint TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    world_id TEXT,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    last_used_at REAL
                )"""
            )
            self._db.commit()
        try:
            path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _row(row: tuple) -> Token:
        return Token(id=row[0], name=row[1], hint=row[2], scope=row[3], world_id=row[4],
                     created_at=row[5], expires_at=row[6], last_used_at=row[7])

    _COLS = "id, name, hint, scope, world_id, created_at, expires_at, last_used_at"

    def create(self, name: str, scope: str = "read", world_id: str | None = None,
               expires_days: int | None = None, now: float | None = None) -> tuple[str, Token]:
        name = (name or "").strip()
        if not name:
            raise TokenError("Give the token a name, so you can tell it apart later.")
        if len(name) > 60:
            raise TokenError("Keep the name under 60 characters.")
        if scope not in SCOPES:
            raise TokenError("Access must be read or write.")
        if expires_days is not None and not (1 <= expires_days <= 3650):
            raise TokenError("Expiry must be between 1 and 3650 days.")
        now = now if now is not None else time.time()
        token = PREFIX + secrets.token_urlsafe(32)
        expires_at = now + expires_days * 86400 if expires_days else None
        hint = f"{token[:9]}...{token[-4:]}"
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tokens (name, hash, hint, scope, world_id, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (name, _hash(token), hint, scope, (world_id or None), now, expires_at),
            )
            self._db.commit()
            row = self._db.execute(f"SELECT {self._COLS} FROM tokens WHERE id=?", (cur.lastrowid,)).fetchone()
        return token, self._row(row)

    def list(self) -> list[Token]:
        with self._lock:
            rows = self._db.execute(f"SELECT {self._COLS} FROM tokens ORDER BY id DESC").fetchall()
        return [self._row(r) for r in rows]

    def delete(self, token_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM tokens WHERE id=?", (token_id,))
            self._db.commit()
            return cur.rowcount > 0

    def verify(self, token: str | None, now: float | None = None) -> Token | None:
        """Return the token record if it is real and not expired, else None."""
        if not token or not token.startswith(PREFIX):
            return None
        now = now if now is not None else time.time()
        with self._lock:
            row = self._db.execute(
                f"SELECT {self._COLS} FROM tokens WHERE hash=?", (_hash(token),)
            ).fetchone()
            if row is None:
                return None
            rec = self._row(row)
            if rec.expires_at is not None and rec.expires_at <= now:
                return None
            if rec.last_used_at is None or now - rec.last_used_at >= TOUCH_EVERY:
                self._db.execute("UPDATE tokens SET last_used_at=? WHERE id=?", (now, rec.id))
                self._db.commit()
                rec.last_used_at = now
        return rec
