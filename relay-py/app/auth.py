"""Login for the web page: signed cookie, with a small lockout after bad tries."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

COOKIE = "fga_relay_session"
SESSION_SECONDS = 12 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 300


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(secret: str, username: str, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + SESSION_SECONDS)
    payload = f"{username}|{expires}"
    body = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{body}.{_sign(secret, payload)}"


def read_session(secret: str, cookie: str | None, now: float | None = None) -> str | None:
    """Return the username if the cookie is valid and not expired, else None."""
    if not cookie or "." not in cookie:
        return None
    body, sig = cookie.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body.encode()).decode()
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(secret, payload)):
        return None
    try:
        username, expires = payload.rsplit("|", 1)
        if float(expires) < (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return username


def check_credentials(want_user: str, want_pass: str, got_user: str, got_pass: str) -> bool:
    """Compare both fields every time so timing does not give hints."""
    user_ok = hmac.compare_digest(want_user.encode(), got_user.encode())
    pass_ok = hmac.compare_digest(want_pass.encode(), got_pass.encode())
    return user_ok and pass_ok


class LoginLimiter:
    """Locks an address out for a few minutes after too many wrong tries."""

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}

    def _recent(self, who: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(who, []) if now - t < LOCK_SECONDS]
        self._fails[who] = recent
        return recent

    def locked(self, who: str, now: float | None = None) -> bool:
        return len(self._recent(who, now if now is not None else time.time())) >= MAX_FAILS

    def fail(self, who: str, now: float | None = None) -> None:
        t = now if now is not None else time.time()
        self._recent(who, t).append(t)

    def clear(self, who: str) -> None:
        self._fails.pop(who, None)
