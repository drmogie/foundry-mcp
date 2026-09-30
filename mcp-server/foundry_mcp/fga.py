"""Client for the Foundry VTT MCP & Rest Relay. It keeps the same call style as the base client,
so every tool keeps its name and its answers keep their shape as far as we can."""

from __future__ import annotations

import asyncio
import base64
import sys
from typing import Any

import httpx

from .client import RelayClient, RelayError, write_allowed_worlds
from . import tactics

DEFAULT_FGA_URL = "https://rest-relay.mogie.io"
SEARCH_TYPES = ["Actor", "Item", "Scene", "JournalEntry", "Macro", "RollTable", "Playlist"]
STRUCTURE_TYPES = ["Scene", "Actor", "Item", "JournalEntry", "RollTable", "Macro", "Playlist"]
FEATURE_TYPES = {"feat", "class", "subclass", "background", "race"}


def _last(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


class FgaClient(RelayClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._applied: set[str] = set()
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

    async def _fga(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None, retry: bool | None = None) -> Any:
        """One call to the relay. A timed-out read is tried once more. A write is only tried again when the caller says it is safe to repeat."""
        again = (method == "GET") if retry is None else retry
        try:
            return await self._fga_once(method, path, params, body)
        except RelayError as exc:
            if not (again and str(exc).startswith("The relay did not answer in time")):
                raise
            await asyncio.sleep(1.0)
            return await self._fga_once(method, path, params, body)

    async def _fga_once(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise RelayError("No API token. Set FOUNDRY_API_KEY to a token from the Rest Relay page (it starts with fgat_).")
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
            raise RelayError(f"The Rest Relay does not have {endpoint} yet.")
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
            return await self._fga("POST", f"/api/v1/documents/{b.get('entityType')}", body={"data": data, "parentUuid": b.get("parentUuid") or None})
        if endpoint == "/update":
            return await self._update(p["uuid"], dict(b.get("data") or {}))
        if endpoint == "/delete":
            return await self._fga("DELETE", "/api/v1/document", {"uuid": p["uuid"], "confirm": True})
        if endpoint == "/switch-scene":
            return await self._fga("POST", "/api/v1/scene/switch", body={"id": b.get("sceneId"), "name": b.get("name"), "activate": True}, retry=True)
        if endpoint == "/dnd5e/use-item":
            return await self._use_item(b)
        if endpoint == "/dnd5e/attack":
            return await self._attack(b)
        if endpoint == "/tactics/move-adjacent":
            return await self._move_adjacent(b)
        if endpoint == "/tactics/move-away":
            return await self._move_away(b)
        if endpoint == "/tactics/apply-hits":
            return await self._apply_hits(b)
        if endpoint == "/rest-all":
            return await self._rest_all(b)
        if endpoint == "/combat/end-all":
            return await self._end_all_combats()
        if endpoint == "/move-token":
            uuid = b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId"))
            return await self._fga("POST", "/api/v1/tokens/move", body={"uuid": uuid, "x": b["x"], "y": b["y"]}, retry=True)
        if endpoint == "/rest":
            uuid = b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId"))
            return await self._fga("POST", "/api/v1/rest", body={"uuid": uuid, "type": b.get("type") or "long", "hitDice": b.get("hitDice") or None}, retry=not b.get("hitDice"))
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
        if endpoint == "/conditions":
            return await self._fga("POST", "/api/v1/conditions", body={
                "uuid": await self._actor_uuid(b.get("uuid", ""), b.get("name", ""), b.get("sceneId", "")),
                "condition": b["condition"], "state": b.get("state") or "add"})
        if endpoint == "/death-save":
            return await self._fga("POST", "/api/v1/death-save", body={
                "uuid": await self._actor_uuid(b.get("uuid", ""), b.get("name", ""), b.get("sceneId", ""))})
        if endpoint == "/check":
            return await self._fga("POST", "/api/v1/check", body={
                "uuid": await self._actor_uuid(b.get("uuid", ""), b.get("name", ""), b.get("sceneId", "")),
                "kind": b.get("kind") or "ability", "key": b["key"], "dc": b.get("dc"),
                "advantage": bool(b.get("advantage")), "disadvantage": bool(b.get("disadvantage"))})
        if endpoint == "/resources":
            target = b.get("target") or "slot"
            uuid = await self._actor_uuid(b.get("uuid", ""), b.get("name", ""), b.get("sceneId", "")) if target == "slot" else None
            return await self._fga("POST", "/api/v1/resources", body={
                "uuid": uuid, "target": target, "level": b.get("level"), "itemUuid": b.get("itemUuid"),
                "mode": b.get("mode") or "spend", "amount": b.get("amount", 1)})
        if endpoint == "/target":
            uuids = list(b.get("uuids") or [])
            for n in b.get("names") or []:
                uuids.append(await self._token_uuid(n, b.get("sceneId")))
            return await self._fga("POST", "/api/v1/target", body={"uuids": uuids}, retry=True)
        if endpoint == "/tokens/create":
            return await self._fga("POST", "/api/v1/tokens", body={
                "actorUuid": b["actorUuid"], "sceneId": b.get("sceneId"), "x": b.get("x"), "y": b.get("y"),
                "hidden": bool(b.get("hidden")), "name": b.get("tokenName")})
        if endpoint == "/tokens/set":
            return await self._fga("PATCH", "/api/v1/tokens", body={
                "uuid": b.get("uuid") or await self._token_uuid(b["name"], b.get("sceneId")),
                "hidden": b.get("hidden"), "rotation": b.get("rotation"), "elevation": b.get("elevation"),
                "x": b.get("x"), "y": b.get("y")})
        if endpoint == "/journals":
            return await self._fga("POST", "/api/v1/journals", body={
                "uuid": b.get("uuid"), "name": b.get("name"), "content": b.get("content"),
                "pages": b.get("pages"), "folder": b.get("folder")})
        if endpoint == "/tables/roll":
            return await self._fga("POST", "/api/v1/tables/roll", body={
                "uuid": b.get("uuid"), "name": b.get("name"), "chat": b.get("chat", True)})
        if endpoint == "/compendium/import":
            return await self._fga("POST", "/api/v1/compendium/import", body={
                "pack": b["pack"], "id": b.get("id"), "ids": b.get("ids"), "actorUuid": b.get("actorUuid"),
                "name": b.get("name"), "folder": b.get("folder"),
                "place": bool(b.get("place")), "sceneId": b.get("sceneId"), "x": b.get("x"), "y": b.get("y"),
                "hidden": bool(b.get("hidden"))})
        raise RelayError(f"The Rest Relay does not have {endpoint} yet. Nothing was changed.")

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

    async def _actor_uuid(self, uuid: str = "", name: str = "", sceneId: str = "") -> str:
        if bool(uuid) == bool(name):
            raise RelayError("Give exactly one of uuid or name.")
        return uuid or await self._token_uuid(name, sceneId or None)

    async def _get_conditions(self, uuid: str = "", name: str = "", sceneId: str = "") -> Any:
        return await self._fga("GET", "/api/v1/conditions", {"uuid": await self._actor_uuid(uuid, name, sceneId)})

    async def _get_resources(self, uuid: str = "", name: str = "", sceneId: str = "") -> Any:
        return await self._fga("GET", "/api/v1/resources", {"uuid": await self._actor_uuid(uuid, name, sceneId)})

    async def _get_last_attack(self, alias: str = "", limit: int = 60) -> Any:
        return await self._fga("GET", "/api/v1/last-attack", {"alias": alias, "limit": limit})

    async def _get_packs(self, type: str = "", q: str = "") -> Any:
        return await self._fga("GET", "/api/v1/packs", {"type": type, "q": q})

    async def _get_pack_index(self, pack: str, q: str = "", limit: int = 25) -> Any:
        return await self._fga("GET", "/api/v1/pack-index", {"pack": pack, "q": q, "limit": limit})

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

    @staticmethod
    def _find_item(actor_uuid: str, actor: dict[str, Any], b: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """The item to use, by uuid or by name, with its data. Nothing is changed when it is missing."""
        items = actor.get("items", [])
        wanted_uuid = b.get("abilityUuid")
        if wanted_uuid:
            item_id = str(wanted_uuid).rsplit(".", 1)[-1]
            match = next((i for i in items if i.get("_id") == item_id), {})
            return wanted_uuid, match
        wanted = str(b["abilityName"]).lower()
        hits = [i for i in items if str(i.get("name", "")).lower() == wanted]
        if not hits:
            names = ", ".join(sorted(str(i.get("name")) for i in items))[:300]
            raise RelayError(f"{actor.get('name')} has no item called {b['abilityName']}. Items: {names}. Nothing was changed.")
        return f"{actor_uuid}.Item.{hits[0]['_id']}", hits[0]

    async def _latest_attack(self, alias: str) -> Any:
        try:
            return await self._get_last_attack(alias=alias, limit=60)
        except RelayError:
            return None

    async def _chat_rows(self) -> list[dict[str, Any]]:
        try:
            rows = await self._fga("GET", "/api/v1/chat", {"limit": 40})
        except RelayError:
            return []
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _new_attack_roll(rows: list[dict[str, Any]], since_id: str | None) -> bool:
        """True when chat holds an attack roll posted after the message with since_id."""
        ids = [r.get("id") for r in rows]
        fresh = rows[ids.index(since_id) + 1:] if since_id in ids else rows
        return any(r.get("rolls") and "attack" in str(r.get("flavor") or "").lower() for r in fresh)

    async def _attack_once(self, b: dict[str, Any]) -> Any:
        """Use a weapon or spell, wait for the damage roll, and apply it when this kind of attacker is switched on."""
        actor_uuid = b["actorUuid"]
        actor = await self._actor_data(actor_uuid)
        item_uuid, item = self._find_item(actor_uuid, actor, b)
        alias = str(actor.get("name") or "")
        kind = "player" if actor.get("type") == "character" else "npc"
        apply_it = bool(b.get("applyPlayers") if kind == "player" else b.get("applyNpcs"))
        rows = await self._chat_rows()
        since_id = rows[-1].get("id") if rows else None
        used = await self._use_item({**b, "abilityUuid": item_uuid})
        targets = used.get("targets") if isinstance(used, dict) else None
        target = targets[0] if targets else None
        result: dict[str, Any] = {"attacker": alias, "kind": kind, "item": (used.get("used") or {}).get("name") if isinstance(used, dict) else None, "applied": False}
        seen: Any = None
        for _ in range(int(b.get("waitSeconds") or 15)):
            await asyncio.sleep(1.0)
            if not self._new_attack_roll(await self._chat_rows(), since_id):
                seen = None
                continue
            seen = await self._latest_attack(alias)
            if not seen or not seen.get("attack"):
                continue
            if not seen.get("outcome"):
                continue  # the roll is in chat, but hit or miss is not worked out yet
            if seen.get("outcome") in ("hit", "critical hit") and seen.get("pending"):
                continue
            break
        if not seen or not seen.get("attack"):
            result["note"] = "No new attack roll showed up in chat. Nothing was applied."
            return result
        outcome = str(seen.get("outcome") or "")
        if not outcome:
            result["attackTotal"] = (seen.get("attack") or {}).get("total")
            result["note"] = "The attack rolled, but Foundry gave no hit or miss. Is a target set? Nothing was applied."
            return result
        result.update({"target": seen.get("target"), "outcome": outcome, "attackTotal": (seen.get("attack") or {}).get("total"), "ac": seen.get("ac")})
        if outcome not in ("hit", "critical hit"):
            result["note"] = "The attack missed. No damage."
            return result
        damage = seen.get("damage")
        if seen.get("pending") or not damage:
            result["note"] = "It hit, but no damage was rolled yet. Nothing was applied."
            return result
        total = damage.get("total")
        types = (((item.get("system") or {}).get("damage") or {}).get("base") or {}).get("types") or []
        damage_type = types[0] if types else None
        result.update({"damage": total, "damageType": damage_type})
        if not apply_it:
            result["note"] = f"Damage was not applied, because automatic damage is off for {kind}s. Use foundry_apply_damage."
            return result
        if not target:
            result["note"] = "There was no target to apply the damage to."
            return result
        hit = await self._fga("POST", "/api/v1/damage", body={"uuid": target, "amount": total, "mode": "damage", "type": damage_type})
        result["applied"] = True
        if isinstance(hit, dict):
            result["hp"] = {"before": (hit.get("before") or {}).get("value"), "after": (hit.get("after") or {}).get("value"), "max": (hit.get("after") or {}).get("max")}
        return result


    # ----- the board: distance, movement, status, watching the table -----

    async def _scene(self, scene_id: str | None = None) -> tuple[str, dict[str, Any]]:
        scene = await self._fga("GET", "/api/v1/scene", {"id": scene_id or None})
        return str(scene["id"]), scene["data"]

    @staticmethod
    def _pick_token(tokens: list[dict[str, Any]], name: str = "", uuid: str = "", what: str = "token") -> dict[str, Any]:
        """One token on the scene, by name or by uuid. An actor uuid works when only one token uses that actor."""
        if bool(name) == bool(uuid):
            raise RelayError(f"Give exactly one of a name or a uuid for the {what}.")
        if uuid:
            last = str(uuid).rsplit(".", 1)[-1]
            hits = [t for t in tokens if t.get("_id") == last] or (
                [t for t in tokens if t.get("actorId") == last] if str(uuid).startswith("Actor.") else [])
        else:
            hits = [t for t in tokens if t.get("name") == name]
        if not hits:
            raise RelayError(f"No {what} '{name or uuid}' on the scene.")
        if len(hits) > 1:
            raise RelayError(f"{len(hits)} tokens match '{name or uuid}'. Use a token uuid.")
        return hits[0]

    async def _get_distance(self, fromName: str = "", fromUuid: str = "", toName: str = "", toUuid: str = "", sceneId: str = "") -> Any:
        sid, data = await self._scene(sceneId)
        tokens = data.get("tokens", [])
        a = self._pick_token(tokens, fromName, fromUuid, "first token")
        b = self._pick_token(tokens, toName, toUuid, "second token")
        size, unit = tactics.grid_of(data)
        feet = tactics.distance_feet(a, b, data)
        gap = tactics.gap_squares(a, b, size)
        return {"from": a.get("name"), "to": b.get("name"), "feet": feet, "squaresBetween": gap, "adjacent": gap == 0,
                "gridFeetPerSquare": unit}

    async def _move_to_square(self, token: dict[str, Any], sid: str, spot: tuple[float, float]) -> Any:
        return await self._fga("POST", "/api/v1/tokens/move", body={"uuid": f"Scene.{sid}.Token.{token['_id']}", "x": spot[0], "y": spot[1]}, retry=True)

    async def _move_adjacent(self, b: dict[str, Any]) -> Any:
        sid, data = await self._scene(b.get("sceneId"))
        tokens = data.get("tokens", [])
        mover = self._pick_token(tokens, b.get("moverName", ""), b.get("moverUuid", ""), "mover")
        target = self._pick_token(tokens, b.get("targetName", ""), b.get("targetUuid", ""), "target")
        size, unit = tactics.grid_of(data)
        if tactics.gap_squares(mover, target, size) == 0:
            return {"moved": False, "note": f"{mover.get('name')} is already next to {target.get('name')}.", "feet": 0}
        others = [t for t in tokens if t.get("_id") not in (mover.get("_id"), target.get("_id"))]
        spot = tactics.square_next_to(mover, target, others, data)
        if spot is None:
            raise RelayError(f"No free square next to {target.get('name')}. Nothing was moved.")
        feet = tactics.squares_moved((float(mover.get("x") or 0), float(mover.get("y") or 0)), spot, size) * unit
        limit = float(b.get("maxFeet") or 0)
        if limit and feet > limit:
            raise RelayError(f"{mover.get('name')} would need to move {feet:g} ft, but the limit is {limit:g} ft. Nothing was moved.")
        await self._move_to_square(mover, sid, spot)
        return {"moved": True, "token": mover.get("name"), "to": {"x": spot[0], "y": spot[1]}, "feet": feet, "nextTo": target.get("name")}

    async def _move_away(self, b: dict[str, Any]) -> Any:
        sid, data = await self._scene(b.get("sceneId"))
        tokens = data.get("tokens", [])
        mover = self._pick_token(tokens, b.get("moverName", ""), b.get("moverUuid", ""), "mover")
        origin = self._pick_token(tokens, b.get("fromName", ""), b.get("fromUuid", ""), "token to move away from")
        size, unit = tactics.grid_of(data)
        others = [t for t in tokens if t.get("_id") != mover.get("_id")]
        spot = tactics.square_away(mover, origin, float(b["feet"]), others, data)
        if spot is None:
            raise RelayError(f"{mover.get('name')} has no free square to step back to. Nothing was moved.")
        feet = tactics.squares_moved((float(mover.get("x") or 0), float(mover.get("y") or 0)), spot, size) * unit
        await self._move_to_square(mover, sid, spot)
        moved = {"moved": True, "token": mover.get("name"), "to": {"x": spot[0], "y": spot[1]}, "feet": feet}
        moved["feetFrom"] = tactics.distance_feet({**mover, "x": spot[0], "y": spot[1]}, origin, data)
        return moved

    async def _hp_of(self, token: dict[str, Any], sid: str) -> dict[str, Any]:
        """Hit points for one token. An unlinked token keeps its own current value on the token."""
        actor_id = token.get("actorId")
        if not actor_id:
            return tactics.hp_line(str(token.get("name")), None, None)
        try:
            base = await self._actor_data(f"Actor.{actor_id}")
        except RelayError:
            base = {}
        hp = ((base.get("system") or {}).get("attributes") or {}).get("hp") or {}
        maximum = (hp.get("max") if hp.get("max") is not None else hp.get("value"))
        value = hp.get("value")
        if not token.get("actorLink"):
            own = ((((token.get("delta") or {}).get("system") or {}).get("attributes") or {}).get("hp") or {})
            if own.get("value") is not None:
                value = own["value"]
            if own.get("max") is not None:
                maximum = own["max"]
        out = tactics.hp_line(str(token.get("name")), value, maximum, hp.get("temp"))
        out["uuid"] = f"Scene.{sid}.Token.{token.get('_id')}"
        out["kind"] = base.get("type")
        return out

    async def _get_status(self, sceneId: str = "") -> Any:
        sid, data = await self._scene(sceneId)
        tokens = [t for t in data.get("tokens", []) if t.get("actorId")]
        lines = await asyncio.gather(*[self._hp_of(t, sid) for t in tokens])
        size, unit = tactics.grid_of(data)
        for line, tok in zip(lines, tokens):
            line["x"], line["y"] = tok.get("x"), tok.get("y")
        try:
            combats = await self._get_encounters()
        except RelayError:
            combats = []
        fights = [{"id": c.get("id"), "round": c.get("round"), "active": c.get("active"), "started": c.get("started"),
                   "sceneId": c.get("sceneId"), "up": tactics.current_combatant(c)} for c in combats or []]
        rows = await self._chat_rows()
        return {"scene": data.get("name"), "gridFeetPerSquare": unit, "tokens": lines, "combats": fights,
                "chatLatestId": rows[-1].get("id") if rows else None}

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    async def _wait_for_player(self, alias: str, seconds: int, since_id: str | None, settle: int, watch_turn: bool) -> Any:
        """Watch chat until the player is done: a done message, a turn change, or quiet after their last roll."""
        start = self._now()
        rows = await self._chat_rows()
        since = since_id or (rows[-1].get("id") if rows else None)
        marks = tactics.combat_marks(await self._get_encounters()) if watch_turn else []
        who = alias.lower()
        seen, last_roll, reason = 0, start, "timeout"
        while self._now() - start < seconds:
            await asyncio.sleep(3.0)
            rows = await self._chat_rows() or rows
            new = tactics.fresh_rows(rows, since)
            if any(tactics.is_done_message(r) for r in new):
                reason = "done"
                break
            mine = [r for r in new if r.get("rolls") and who in str(r.get("alias") or "").lower()]
            if len(mine) > seen:
                seen, last_roll = len(mine), self._now()
            if watch_turn:
                try:
                    if tactics.combat_marks(await self._get_encounters()) != marks:
                        reason = "turn_changed"
                        break
                except RelayError:
                    pass
            if seen and self._now() - last_roll >= settle:
                reason = "settled"
                break
        new = tactics.fresh_rows(rows, since)
        return {"reason": reason, "waited": round(self._now() - start), "latestId": rows[-1].get("id") if rows else since,
                "hits": tactics.read_hits(new, alias)}

    async def _get_wait_for_player(self, alias: str, seconds: int = 30, sinceId: str = "", settle: int = 8, watchTurn: bool = True) -> Any:
        return await self._wait_for_player(alias, min(max(int(seconds), 3), 90), sinceId or None, min(max(int(settle), 3), 30), bool(watchTurn))

    async def _apply_hits(self, b: dict[str, Any]) -> Any:
        """Take the damage of every unapplied hit by this attacker off its target. Each damage roll is applied once."""
        alias = str(b["alias"])
        sid, data = await self._scene(b.get("sceneId"))
        tokens = data.get("tokens", [])
        rows = tactics.fresh_rows(await self._fga("GET", "/api/v1/chat", {"limit": 200}), b.get("sinceId") or None)
        hits = tactics.read_hits(rows, alias)
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        mine = [t for t in tokens if str(t.get("name", "")).lower() == alias.lower()]
        actor: dict[str, Any] = {}
        if len(mine) == 1 and mine[0].get("actorId"):
            try:
                actor = await self._actor_data(f"Actor.{mine[0]['actorId']}")
            except RelayError:
                actor = {}
        for hit in hits:
            if hit["outcome"] not in ("hit", "critical hit") or hit["damage"] is None:
                continue
            if hit["damageId"] in self._applied:
                skipped.append({"weapon": hit["weapon"], "damage": hit["damage"], "why": "already applied"})
                continue
            try:
                target = self._pick_token(tokens, hit["target"], "", "target")
            except RelayError as exc:
                skipped.append({"weapon": hit["weapon"], "damage": hit["damage"], "why": str(exc)})
                continue
            item = next((i for i in actor.get("items", []) if str(i.get("name", "")).lower() == str(hit["weapon"] or "").lower()), {})
            types = (((item.get("system") or {}).get("damage") or {}).get("base") or {}).get("types") or []
            result = await self._fga("POST", "/api/v1/damage", body={"uuid": f"Scene.{sid}.Token.{target['_id']}", "amount": hit["damage"], "mode": "damage", "type": types[0] if types else None})
            self._applied.add(hit["damageId"])
            row = {"weapon": hit["weapon"], "target": target.get("name"), "damage": hit["damage"], "critical": hit["outcome"] == "critical hit"}
            if isinstance(result, dict):
                row["hp"] = {"before": (result.get("before") or {}).get("value"), "after": (result.get("after") or {}).get("value"), "max": (result.get("after") or {}).get("max")}
            applied.append(row)
        return {"attacker": alias, "applied": applied, "skipped": skipped, "total": sum(a["damage"] for a in applied),
                "note": None if hits else f"No attacks by {alias} found in recent chat."}

    async def _rest_all(self, b: dict[str, Any]) -> Any:
        sid, data = await self._scene(b.get("sceneId"))
        kind = b.get("type") or "long"
        names = {str(n).lower() for n in b.get("names") or []}
        seen: set[str] = set()
        done: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for tok in data.get("tokens", []):
            if not tok.get("actorId") or (names and str(tok.get("name", "")).lower() not in names):
                continue
            uuid = f"Actor.{tok['actorId']}" if tok.get("actorLink") else f"Scene.{sid}.Token.{tok['_id']}"
            if uuid in seen:
                continue
            seen.add(uuid)
            try:
                res = await self._fga("POST", "/api/v1/rest", body={"uuid": uuid, "type": kind}, retry=True)
                done.append({"name": tok.get("name"), "before": (res.get("before") or {}).get("value"), "after": (res.get("after") or {}).get("value"), "max": (res.get("after") or {}).get("max")})
            except RelayError as exc:
                failed.append({"name": tok.get("name"), "error": str(exc)})
        return {"rest": kind, "rested": done, "failed": failed}

    async def _end_all_combats(self) -> Any:
        ended: list[Any] = []
        for combat in await self._get_encounters() or []:
            await self._fga("POST", "/api/v1/combat/control", body={"action": "end", "combatId": combat.get("id"), "confirm": True})
            ended.append(combat.get("id"))
        return {"ended": ended}

    async def _attack(self, b: dict[str, Any]) -> Any:
        """Attack once or several times. It checks reach and range first, and sets advantage or disadvantage."""
        count = max(1, min(int(b.get("attacks") or 1), 6))
        adv, dis = bool(b.get("advantage")), bool(b.get("disadvantage"))
        info: dict[str, Any] = {}
        if not b.get("ignoreDistance") and (b.get("targetUuid") or b.get("targetName")):
            try:
                actor = await self._actor_data(b["actorUuid"])
                _uuid, item = self._find_item(b["actorUuid"], actor, b)
                sid, data = await self._scene()
                tokens = data.get("tokens", [])
                actor_id = str(b["actorUuid"]).rsplit(".", 1)[-1] if str(b["actorUuid"]).startswith("Actor.") else str(actor.get("_id") or "")
                mine = [t for t in tokens if t.get("actorId") == actor_id]
                target = self._pick_token(tokens, b.get("targetName", ""), b.get("targetUuid", ""), "target")
                if len(mine) == 1:
                    _size, unit = tactics.grid_of(data)
                    feet = tactics.distance_feet(mine[0], target, data)
                    check = tactics.check_attack(item, feet, unit, b.get("autoDisadvantage", True) is not False, str(target.get("name")))
                    info = {k: v for k, v in check.items() if k in ("feet", "kind", "reach", "range", "note")}
                    if not check["ok"]:
                        return {"attacker": actor.get("name"), "item": item.get("name"), "applied": False, "distance": info,
                                "note": f"{check['note']} Nothing was rolled."}
                    dis = dis or check["disadvantage"]
            except RelayError:
                info = {}
        if adv and dis:
            adv = dis = False
            info["note"] = ((info.get("note") or "") + " Advantage and disadvantage cancel out.").strip()
        results: list[dict[str, Any]] = []
        for _ in range(count):
            result = await self._attack_once({**b, "advantage": adv, "disadvantage": dis})
            if info:
                result["distance"] = info
            if adv or dis:
                result["rollMode"] = "advantage" if adv else "disadvantage"
            results.append(result)
            hp = result.get("hp") or {}
            if hp.get("after") is not None and hp["after"] <= 0:
                break
        if count == 1:
            return results[0]
        return {"attacker": results[0].get("attacker"), "attacks": results,
                "totalDamage": sum(r.get("damage") or 0 for r in results if r.get("applied"))}

    async def _use_item(self, b: dict[str, Any]) -> Any:
        actor_uuid = b["actorUuid"]
        item_uuid = b.get("abilityUuid")
        if not item_uuid:
            actor = await self._actor_data(actor_uuid)
            item_uuid, _item = self._find_item(actor_uuid, actor, b)
        target = b.get("targetUuid")
        if not target and b.get("targetName"):
            target = await self._token_uuid(b["targetName"], None)
        return await self._fga("POST", "/api/v1/items/use", body={"uuid": item_uuid, "targets": [target] if target else None, "clearArea": bool(b.get("clearArea")), "template": bool(b.get("template")),
            "advantage": bool(b.get("advantage")) or None, "disadvantage": bool(b.get("disadvantage")) or None})
