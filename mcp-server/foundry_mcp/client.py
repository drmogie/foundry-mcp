"""Small async client for the ThreeHats Foundry REST API relay."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_RELAY_URL = "http://ha-pi4:3010"
MAX_CHARS = 60_000


class RelayError(Exception):
    """A problem talking to the relay, worded so a person can act on it."""


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

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise RelayError(
                "No API key. Set FOUNDRY_API_KEY to the key from the relay dashboard."
            )
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:
            resp = await self._http.get(
                f"{self.base_url}{path}", params=clean, headers={"x-api-key": self.api_key}
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


def to_text(data: Any) -> str:
    """Turn a relay reply into compact text, cut to a safe size."""
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    if len(text) > MAX_CHARS:
        text = (
            text[:MAX_CHARS]
            + f"\n... cut off at {MAX_CHARS} characters. Ask for less (a smaller limit, a filter, or a single uuid)."
        )
    return text
