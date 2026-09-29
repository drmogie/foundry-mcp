"""Settings read from the environment (the add-on turns its options into these)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path
    admin_username: str
    admin_password: str
    port: int = 3011
    log_level: str = "info"

    @property
    def login_configured(self) -> bool:
        return bool(self.admin_username and self.admin_password)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            admin_username=os.environ.get("ADMIN_USERNAME", ""),
            admin_password=os.environ.get("ADMIN_PASSWORD", ""),
            port=int(os.environ.get("PORT", "3011")),
            log_level=os.environ.get("LOG_LEVEL", "info"),
        )


def _read_or_create(path: Path, make) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text().strip()
        if value:
            return value
    value = make()
    path.write_text(value + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def session_secret(settings: Settings) -> str:
    return _read_or_create(settings.data_dir / "session_secret.txt", lambda: secrets.token_hex(32))


def load_connect_key(settings: Settings) -> str:
    return _read_or_create(settings.data_dir / "connect_key.txt", lambda: "fga_" + secrets.token_urlsafe(24))


def new_connect_key(settings: Settings) -> str:
    path = settings.data_dir / "connect_key.txt"
    value = "fga_" + secrets.token_urlsafe(24)
    path.write_text(value + "\n")
    return value
