"""Client for our own FGA relay. It keeps the same call style as the base client,
so every tool keeps its name and its answers keep their shape as far as we can."""

from __future__ import annotations

import base64
import sys
from typing import Any

import httpx

from .client import RelayClient, RelayError, write_allowed_worlds

DEFAULT_FGA_URL = "https://rest-relay.mogie.io"
SEARCH_TYPES = ["Actor", "Item", "Scene", "JournalEntry", "Macro", "RollTable", "Playlist"]
STRUCTURE_TYPES = ["Scene", "Actor", "Item", "JournalEntry", "RollTable", "Macro", "Playlist"]
FEATURE_TYPES = {"feat", "class", "subclass", "background", "race"}


def _last(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


class FgaClient(RelayClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        import os

        if not (kwargs.get("base_url") or os.environ.get("FOUNDRY_RELAY_URL")):
            self.base_url = DEFAULT_FGA_URL

    # ----- plumbing -----

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text[:300]
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("error") or body)[:400]
        return str(body)[:400]

    async def _fga(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise RelayError("No API token. Set FOUNDRY_API_KEY to a token from the FGA relay page (it starts with fgat_).")
        query = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        for key, value in list(query.items()):
            if isinstance(value, bool):
                query[key] = "true" if value else "false"
        if self.client_id:
            query["client_id"] = self.client_id
        if body is not None:
            body = {k: v for k, v in body.items() if v is not None}
        try:
            resp = await self._http.request(
                method, f"{self.base_url}{path}", params=query, json=body, headers={"x-api-key": self.api_key}
            )
        except httpx.ConnectError as exc:
            raise RelayError(f"Cannot reach the relay at {self.base_url}. Is the add-on running, and are you on the home network? ({exc})") from exc
        except httpx.TimeoutException as exc:
            raise RelayError("The relay did not answer in time. Foundry may be closed or busy.") from exc
        if resp.status_code >= 400:
            raise RelayError(self._detail(resp))
        try:
            reply = resp.json()
        except ValueError as exc:
            raise RelayError(f"Relay sent something that is not JSON for {path}.") from exc
        return reply.get("data") if isinstance(reply, dict) and "data" in reply else reply

    async def list_clients(self) -> Any:
        data = await self._fga("GET", "/api/v1/clients")
        clients = data.get("clients", []) if isinstance(data, dict) else []
        return {"total": len(clients), "clients": [{**c, "isOnline": True} for c in clients]}

    async def resolve_client_id(self) -> str:
        if self.client_id:
            return self.client_id
        clients = (await self.list_clients())["clients"]
        if len(clients) == 1:
            return str(clients[0]["clientId"])
        if not clients:
            raise RelayError("No Foundry client is connected. Open Foundry in a browser, log in, and check the FGA Relay Connect settings.")
        names = ", ".join(str(c.get("worldTitle") or c.get("worldId") or c.get("clientId")) for c in clients)
        raise RelayError(f"More than one Foundry client is connected ({names}). Set FOUNDRY_CLIENT_ID to pick one.")

    async def check_write_target(self) -> tuple[str, str]:
        client_id = await self.resolve_client_id()
        clients = (await self.list_clients())["clients"]
        match = next((c for c in clients if c.get("clientId") == client_id), None)
        if not match:
            raise RelayError("That Foundry client is not connected, so nothing was changed.")
        world = str(match.get("worldId") or "")
        allowed = write_allowed_worlds()
        if world not in allowed:
            raise RelayError(
                f"Writes are blocked for world '{world}'. Allowed worlds: {', '.join(sorted(allowed))}. "
                "Nothing was changed. (Set FOUNDRY_WRITE_WORLDS to change this.)"
            )
        return client_id, world

    # ----- reading -----

    async def get(self, endpoint: str, **params: Any) -> Any:
        name = "_get_" + endpoint.strip("/").replace("-", "_").replace("/", "_")
        handler = getattr(self, name, None)
        if handler is None:
            raise RelayError(f"The FGA relay does not have {endpoint} yet.")
        return await handler(**params)

    async def _docs(self, document_type: str, q: str = "", limit: int = 50) -> dict[str, Any]:
        return await self._fga("GET", f"/api/v1/documents/{document_type}", {"q": q, "limit": limit})

    async def _actor_data(self, uuid: str) -> dict[str, Any]:
        doc = await self._fga("GET", "/api/v1/document", {"uuid": uuid})
        return doc["data"] if isinstance(doc, dict) and "data" in doc else doc

    async def _get_world_info(self) -> Any:
        return await self._fga("GET", "/api/v1/world")

    async def _get_structure(self, path: str = "", types: str = "", recursive: bool = True, includeEntityData: bool = False) -> Any:
        wanted = [t.strip() for t in types.split(",") if t.strip()] or STRUCTURE_TYPES
        out: dict[str, Any] = {}
        for t in wanted:
            if t == "Cards":
                continue
            out[t] = (await self._docs(t, limit=500))["results"]
        return {"types": out}

    async def _get_search(self, query: str = "", filter: str = "", limit: int = 50, minified: bool = True, excludeCompendiums: bool = False) -> Any:
        doc_types = list(SEARCH_TYPES)
        sub = ""
        if "documentType:" in filter or "subType:" in filter:
            pairs = dict(p.split(":", 1) for p in filter.split(",") if ":" in p)
            if pairs.get("documentType"):
                doc_types = [pairs["documentType"].strip()]
            sub = pairs.get("subType", "").strip().lower()
        elif filter.strip():
            doc_types = [filter.strip()]
        results: list[dict[str, Any]] = []
        for t in doc_types:
            found = (await self._docs(t, query, limit))["results"]
            results.extend(r for r in found if not sub or str(r.get("type", "")).lower() == sub)
        return {"total": len(results), "results": results[:limit]}

    async def _get_get(self, uuid: str) -> Any:
        return await self._fga("GET", "/api/v1/document", {"uuid": uuid})

    async def _get_dnd5e_get_actor_details(self, actorUuid: str, details: list[str] | None = None) -> Any:
        data = await self._actor_data(actorUuid)
        want = set(details or ["resources", "items", "spells", "features"])
        system = data.get("system", {}) if isinstance(data, dict) else {}
        items = data.get("items", []) if isinstance(data, dict) else []

        def brief(i: dict[str, Any]) -> dict[str, Any]:
            s = i.get("system", {}) or {}
            return {"id": i.get("_id"), "name": i.get("name"), "type": i.get("type"),
                    "quantity": s.get("quantity"), "equipped": s.get("equipped"),
                    "level": s.get("level"), "preparation": s.get("preparation")}

        out: dict[str, Any] = {"uuid": actorUuid, "name": data.get("name"), "type": data.get("type")}
        if "resources" in want:
            out["resources"] = {k: system.get(k) for k in ("attributes", "abilities", "resources", "currency", "details") if k in system}
        if "items" in want:
            out["items"] = [brief(i) for i in items if i.get("type") not in FEATURE_TYPES | {"spell"}]
        if "spells" in want:
            out["spells"] = [brief(i) for i in items if i.get("type") == "spell"]
        if "features" in want:
            out["features"] = [brief(i) for i in items if i.get("type") in FEATURE_TYPES]
        return out

    async def _get_scene(self, sceneId: str = "", name: str = "", active: Any = None, viewed: Any = None, all: Any = None) -> Any:
        if all:
            return (await self._docs("Scene", limit=500))["results"]
        return await self._fga("GET", "/api/v1/scene", {"id": sceneId, "name": name, "viewed": bool(viewed) or None})

    async def _get_users(self) -> Any:
        return await self._fga("GET", "/api/v1/users")

    async def _messages(self, limit: int) -> list[dict[str, Any]]:
        return await self._fga("GET", "/api/v1/chat", {"limit": min(max(limit, 1), 200)})

    async def _get_chat(self, limit: int = 10, offset: int = 0, chatType: int | None = None, speaker: str = "") -> Any:
        filtered = bool(speaker) or chatType in (3, 4)
        messages = await self._messages(200 if filtered else limit + offset)
        if speaker:
            s = speaker.lower()
            messages = [m for m in messages if s in str(m.get("alias") or "").lower()]
        if chatType == 4:
            messages = [m for m in messages if m.get("rolls")]
        elif chatType == 3:
            messages = [m for m in messages if m.get("whisper")]
        if offset:
            messages = messages[: max(len(messages) - offset, 0)]
        return messages[-limit:]

    async def _get_rolls(self, limit: int = 20) -> Any:
        rolled = [m for m in await self._messages(200) if m.get("rolls")]
        return [{"id": m["id"], "timestamp": m.get("timestamp"), "author": m.get("author"), "alias": m.get("alias"),
                 "flavor": m.get("flavor"), "rolls": m["rolls"]} for m in rolled[-limit:]]

    async def _get_encounters(self) -> Any:
        return await self._fga("GET", "/api/v1/encounters")

    async def _get_macros(self) -> Any:
        return (await self._docs("Macro", limit=500))["results"]

    async def _get_effects(self, uuid: str) -> Any:
        return await self._fga("GET", "/api/v1/effects", {"uuid": uuid})

    async def _get_file_system(self, path: str = "", source: str = "data", recursive: bool = False) -> Any:
        if not recursive:
            return {"results": await self.list_dir(path, source)}
        results: list[dict[str, Any]] = []
        stack, seen = [path], 0
        while stack and seen < 500:
            folder = stack.pop()
            for item in await self.list_dir(folder, source):
                results.append(item)
                seen += 1
                if item["type"] == "directory":
                    stack.append(item["path"])
        return {"results": results, "note": "Cut off at 500 entries." if seen >= 500 else ""}

    async def list_dir(self, path: str, source: str = "data") -> list[dict[str, Any]]:
        data = await self._fga("GET", "/api/v1/files", {"path": path, "source": source})
        items = [{"name": _last(d), "path": d, "type": "directory"} for d in data.get("dirs", [])]
        items += [{"name": _last(f), "path": f, "type": "file"} for f in data.get("files", [])]
        return items

    async def download(self, path: str, source: str = "data") -> tuple[bytes, str]:
        data = await self._fga("GET", "/api/v1/file", {"path": path, "source": source})
        blob = data.get("base64") if isinstance(data, dict) else None
        if not isinstance(blob, str):
            raise RelayError(f"Foundry sent no file data for {path}.")
        try:
            raw = base64.b64decode(blob)
        except ValueError as exc:
            raise RelayError(f"The file data for {path} was not valid base64.") from exc
        return raw, str(data.get("mimeType") or "application/octet-stream")

    # ----- writing -----

    async def write(self, method: str, endpoint: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
        client_id, world = await self.check_write_target()
        print(f"[foundry-mcp] WRITE {method} {endpoint} world={world} (fga)", file=sys.stderr, flush=True)
        b = {k: v for k, v in (body or {}).items() if v is not None and v != ""}
        p = params or {}
        if endpoint == "/chat":
            return await self._fga("POST", "/api/v1/chat", body={
                "content": b.get("content"), "flavor": b.get("flavor"), "alias": b.get("alias"),
                "actorId": b.get("speaker"), "whisper": b.get("whisper")})
        if endpoint == "/roll":
            return await self._fga("POST", "/api/v1/rolls", body={
                "formula": b.get("formula"), "flavor": b.get("flavor"),
                "chat": b.get("createChatMessage", True), "whisper": b.get("whisper")})
        if endpoint == "/create":
            data = dict(b.get("data") or {})
            if b.get("folder"):
                data["folder"] = b["folder"]
            return await self._fga("POST", f"/api/v1/documents/{b.get('entityType')}", body={"data": data})
        if endpoint == "/update":
            return await self._update(p["uuid"], dict(b.get("data") or {}))
        if endpoint == "/delete":
            return await self._fga("DELETE", "/api/v1/document", {"uuid": p["uuid"], "confirm": True})
        if endpoint == "/switch-scene":
            return await self._fga("POST", "/api/v1/scene/switch", body={"id": b.get("sceneId"), "name": b.get("name"), "activate": True})
        if endpoint == "/dnd5e/use-item":
            return await self._use_item(b)
        if endpoint == "/move-token":
            uuid = b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId"))
            return await self._fga("POST", "/api/v1/tokens/move", body={"uuid": uuid, "x": b["x"], "y": b["y"]})
        if endpoint == "/rest":
            uuid = b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId"))
            return await self._fga("POST", "/api/v1/rest", body={"uuid": uuid, "type": b.get("type") or "long", "hitDice": b.get("hitDice") or None})
        if endpoint == "/combat/create":
            return await self._combat_create(b)
        if endpoint == "/combat/control":
            return await self._fga("POST", "/api/v1/combat/control", body={
                "action": b.get("action"), "combatId": b.get("combatId"), "confirm": bool(b.get("confirm"))})
        if endpoint == "/damage":
            uuid = b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId"))
            return await self._fga("POST", "/api/v1/damage", body={
                "uuid": uuid, "amount": b["amount"], "mode": b.get("mode") or "damage",
                "type": b.get("damageType"), "multiplier": b.get("multiplier")})
        raise RelayError(f"The FGA relay does not have {endpoint} yet. Nothing was changed.")

    async def _combat_create(self, b: dict[str, Any]) -> Any:
        uuids = list(b.get("tokenUuids") or [])
        if b.get("allTokens") or b.get("tokenNames"):
            scene = await self._fga("GET", "/api/v1/scene", {"id": b.get("sceneId")})
            tokens = scene["data"].get("tokens", [])
            names = {str(n).lower() for n in b.get("tokenNames") or []}
            picked = tokens if b.get("allTokens") else [t for t in tokens if str(t.get("name", "")).lower() in names]
            missing = names - {str(t.get("name", "")).lower() for t in tokens}
            if missing:
                raise RelayError(f"No token called {', '.join(sorted(missing))} on scene {scene['data'].get('name')}. Nothing was changed.")
            uuids += [f"Scene.{scene['id']}.Token.{t['_id']}" for t in picked]
        return await self._fga("POST", "/api/v1/combat", body={
            "sceneId": b.get("sceneId"), "tokenUuids": uuids or None,
            "rollInitiative": bool(b.get("rollInitiative")), "start": bool(b.get("start"))})

    async def _get_activity(self, limit: int = 20, token: str = "", kind: str = "") -> Any:
        return await self._fga("GET", "/api/v1/activity", {"limit": limit, "token": token, "kind": kind})

    async def _update(self, uuid: str, data: dict[str, Any]) -> Any:
        """Foundry's own update cannot add embedded items or effects, so those become creates on the parent."""
        result: dict[str, Any] = {}
        for key, doc_type in (("items", "Item"), ("effects", "ActiveEffect")):
            rows = data.pop(key, None)
            if isinstance(rows, list) and rows:
                result[f"{key}_created"] = await self._fga(
                    "POST", f"/api/v1/documents/{doc_type}", body={"data": rows, "parentUuid": uuid})
        if data:
            result["updated"] = await self._fga("PATCH", "/api/v1/document", body={"uuid": uuid, "data": data})
        return result

    async def _token_uuid(self, name: str, scene_id: str | None) -> str:
        scene = await self._fga("GET", "/api/v1/scene", {"id": scene_id})
        data = scene["data"]
        matches = [t for t in data.get("tokens", []) if t.get("name") == name]
        if not matches:
            raise RelayError(f"No token called {name} on scene {data.get('name')}. Nothing was changed.")
        if len(matches) > 1:
            raise RelayError(f"{len(matches)} tokens are called {name}. Use a uuid instead. Nothing was changed.")
        return f"Scene.{scene['id']}.Token.{matches[0]['_id']}"

    async def _use_item(self, b: dict[str, Any]) -> Any:
        actor_uuid = b["actorUuid"]
        item_uuid = b.get("abilityUuid")
        if not item_uuid:
            actor = await self._actor_data(actor_uuid)
            wanted = str(b["abilityName"]).lower()
            hits = [i for i in actor.get("items", []) if str(i.get("name", "")).lower() == wanted]
            if not hits:
                names = ", ".join(sorted(str(i.get("name")) for i in actor.get("items", [])))[:300]
                raise RelayError(f"{actor.get('name')} has no item called {b['abilityName']}. Items: {names}. Nothing was changed.")
            item_uuid = f"{actor_uuid}.Item.{hits[0]['_id']}"
        target = b.get("targetUuid")
        if not target and b.get("targetName"):
            target = await self._token_uuid(b["targetName"], None)
        return await self._fga("POST", "/api/v1/items/use", body={"uuid": item_uuid, "targets": [target] if target else None})
