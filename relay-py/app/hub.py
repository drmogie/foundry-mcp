"""Keeps track of connected Foundry clients and sends them commands."""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


class HubError(Exception):
    """A problem worded so a person can act on it."""


@dataclass
class Client:
    client_id: str
    ws: WebSocket
    info: dict[str, Any]
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {
            "clientId": self.client_id,
            "worldId": self.info.get("worldId"),
            "worldTitle": self.info.get("worldTitle"),
            "foundryVersion": self.info.get("foundryVersion"),
            "systemId": self.info.get("systemId"),
            "systemVersion": self.info.get("systemVersion"),
            "userName": self.info.get("userName"),
            "isGM": self.info.get("isGM"),
            "moduleVersion": self.info.get("moduleVersion"),
            "connectedAt": self.connected_at,
            "lastSeen": self.last_seen,
        }


class Hub:
    def __init__(self) -> None:
        self.clients: dict[str, Client] = {}
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)

    def add(self, client: Client) -> None:
        old = self.clients.get(client.client_id)
        self.clients[client.client_id] = client
        if old is not None and old.ws is not client.ws:
            asyncio.ensure_future(_close_quietly(old.ws, 4409, "Replaced by a newer connection"))

    def remove(self, client: Client) -> None:
        if self.clients.get(client.client_id) is client:
            del self.clients[client.client_id]

    def pick(self, client_id: str | None) -> Client:
        if client_id:
            if client_id not in self.clients:
                raise HubError(f"No Foundry client called {client_id} is connected.")
            return self.clients[client_id]
        if not self.clients:
            raise HubError(
                "No Foundry client is connected. Open Foundry in a browser, log in, and check the module settings."
            )
        if len(self.clients) > 1:
            raise HubError("More than one Foundry client is connected. Say which one with client_id.")
        return next(iter(self.clients.values()))

    def resolve(self, message: dict[str, Any]) -> None:
        fut = self._pending.pop(message.get("id"), None)
        if fut is not None and not fut.done():
            fut.set_result(message)

    async def request(self, client: Client, kind: str, data: dict | None = None, timeout: float = 15.0) -> Any:
        rid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await client.ws.send_json({"id": rid, "type": kind, "data": data or {}})
            reply = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as exc:
            raise HubError("Foundry did not answer in time. The browser tab may be asleep or busy.") from exc
        except Exception as exc:  # socket closed mid send
            raise HubError(f"Lost the link to Foundry ({exc}).") from exc
        finally:
            self._pending.pop(rid, None)
        if not reply.get("ok", False):
            raise HubError(str(reply.get("error") or "Foundry reported an error."))
        return reply.get("data")

    async def close_all(self, code: int, reason: str) -> None:
        for client in list(self.clients.values()):
            await _close_quietly(client.ws, code, reason)


async def _close_quietly(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        pass
