"""Base async client. FgaClient (fga.py) builds on it and talks to the Foundry VTT MCP & Rest Relay."""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any

import httpx

DEFAULT_RELAY_URL = "https://rest-relay.mogie.io"
MAX_CHARS = 60_000


class RelayError(Exception):
    """A problem talking to the relay, worded so a person can act on it."""


def write_allowed_worlds() -> set[str]:
    """World ids that writes may touch. Default: only the test world."""
    raw = os.environ.get("FOUNDRY_WRITE_WORLDS", "mcp-test")
    return {w.strip() for w in raw.split(",") if w.strip()}


def _flag(value: bool) -> str:
    return "true" if value else "false"


class RelayClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        client_id: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("FOUNDRY_RELAY_URL") or DEFAULT_RELAY_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("FOUNDRY_API_KEY") or ""
        self.client_id = client_id or os.environ.get("FOUNDRY_CLIENT_ID") or ""
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.api_key:
            raise RelayError(
                "No API key. Set FOUNDRY_API_KEY to the key from the relay dashboard."
            )
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:
            resp = await self._http.request(
                method,
                f"{self.base_url}{path}",
                params=clean,
                json=body,
                headers={"x-api-key": self.api_key},
            )
        except httpx.ConnectError as exc:
            raise RelayError(
                f"Cannot reach the relay at {self.base_url}. Is the add-on running? ({exc})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RelayError(
                "The relay did not answer in time. Foundry may be closed or busy."
            ) from exc
        if resp.status_code == 401 or resp.status_code == 403:
            raise RelayError("The relay rejected the API key (or its scopes). Check FOUNDRY_API_KEY.")
        if resp.status_code == 404:
            raise RelayError(f"Relay said not found for {path}. {self._detail(resp)}")
        if resp.status_code >= 400:
            raise RelayError(f"Relay error {resp.status_code} for {path}. {self._detail(resp)}")
        try:
            return resp.json()
        except ValueError as exc:
            raise RelayError(f"Relay sent something that is not JSON for {path}.") from exc

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text[:300]
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body)[:300]
        return str(body)[:300]

    async def list_clients(self) -> Any:
        return await self._request("/clients")

    async def resolve_client_id(self) -> str:
        """Use the configured id, else the only world that is online right now."""
        if self.client_id:
            return self.client_id
        data = await self.list_clients()
        clients = data.get("clients", []) if isinstance(data, dict) else []
        online = [c for c in clients if c.get("isOnline")]
        if len(online) == 1 and online[0].get("clientId"):
            return str(online[0]["clientId"])
        if not online:
            raise RelayError(
                "No Foundry world is online. Launch the world as GM and check the module Connection menu."
            )
        names = ", ".join(str(c.get("worldTitle") or c.get("worldId") or c.get("clientId")) for c in online)
        raise RelayError(
            f"More than one world is online ({names}). Set FOUNDRY_CLIENT_ID to pick one."
        )

    async def get(self, endpoint: str, **params: Any) -> Any:
        params["clientId"] = await self.resolve_client_id()
        for key, value in list(params.items()):
            if isinstance(value, bool):
                params[key] = _flag(value)
            elif isinstance(value, (list, dict)):
                params[key] = json.dumps(value)
        return await self._request(endpoint, params)

    async def check_write_target(self) -> tuple[str, str]:
        """Return (client_id, world_id) if writing to this world is allowed. Otherwise raise."""
        client_id = await self.resolve_client_id()
        data = await self.list_clients()
        clients = data.get("clients", []) if isinstance(data, dict) else []
        match = next((c for c in clients if c.get("clientId") == client_id), None)
        if not match or not match.get("isOnline"):
            raise RelayError("That world is not online, so nothing was changed.")
        world = str(match.get("worldId") or "")
        allowed = write_allowed_worlds()
        if world not in allowed:
            raise RelayError(
                f"Writes are blocked for world '{world}'. Allowed worlds: {', '.join(sorted(allowed))}. "
                "Nothing was changed. (Set FOUNDRY_WRITE_WORLDS to change this.)"
            )
        return client_id, world

    async def write(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Send a change to Foundry. Only to an allowed world. Logs each write to stderr."""
        client_id, world = await self.check_write_target()
        query = {"clientId": client_id, **(params or {})}
        clean_body = {k: v for k, v in (body or {}).items() if v is not None and v != ""}
        print(f"[foundry-mcp] WRITE {method} {endpoint} world={world}", file=sys.stderr, flush=True)
        return await self._request(endpoint, query, method=method, body=clean_body or None)

    async def list_dir(self, path: str, source: str = "data") -> list[dict[str, Any]]:
        """One folder level: a list of {name, path, type} where type is directory or file."""
        data = await self.get("/file-system", path=path, source=source, recursive=False)
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RelayError(f"Could not read the folder list for {path}.")
        return [i for i in items if isinstance(i, dict)]

    async def download(self, path: str, source: str = "data") -> tuple[bytes, str]:
        """Fetch one file from Foundry. Returns (bytes, mime type)."""
        data = await self.get("/download", path=path, source=source, format="base64")
        blob = data.get("fileData") if isinstance(data, dict) else None
        if not isinstance(blob, str) or not blob:
            raise RelayError(f"Foundry sent no file data for {path}.")
        b64 = blob.split(",", 1)[1] if blob.startswith("data:") and "," in blob else blob
        try:
            raw = base64.b64decode(b64)
        except ValueError as exc:
            raise RelayError(f"The file data for {path} was not valid base64.") from exc
        return raw, str(data.get("mimeType") or "application/octet-stream")


def to_text(data: Any) -> str:
    """Turn a relay reply into compact text, cut to a safe size."""
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    if len(text) > MAX_CHARS:
        text = (
            text[:MAX_CHARS]
            + f"\n... cut off at {MAX_CHARS} characters. Ask for less (a smaller limit, a filter, or a single uuid)."
        )
    return text
