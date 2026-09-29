"""The REST API. Each route asks the connected Foundry client to do one thing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .activity import ActivityLog
from .hub import Client, FoundryError, Hub, HubError
from .settings import Settings
from .tokens import Token


COMBAT_ACTIONS = ("start", "nextTurn", "previousTurn", "nextRound", "previousRound", "rollAll", "rollNpc", "end")
DAMAGE_MODES = ("damage", "heal", "temp")
REST_TYPES = ("long", "short")


class UpdateBody(BaseModel):
    uuid: str
    data: dict[str, Any]
    options: dict[str, Any] | None = None


class CreateBody(BaseModel):
    data: dict[str, Any]
    parentUuid: str | None = None
    options: dict[str, Any] | None = None


class ChatBody(BaseModel):
    content: str
    flavor: str | None = None
    actorId: str | None = None
    alias: str | None = None
    whisper: list[str] | None = None


class RollBody(BaseModel):
    formula: str
    flavor: str | None = None
    chat: bool = True
    whisper: list[str] | None = None


class UseItemBody(BaseModel):
    uuid: str
    targets: list[str] | None = None
    activityId: str | None = None


class MoveBody(BaseModel):
    uuid: str
    x: float
    y: float


class CombatCreateBody(BaseModel):
    sceneId: str | None = None
    tokenUuids: list[str] | None = None
    rollInitiative: bool = False
    start: bool = False


class CombatControlBody(BaseModel):
    action: str
    combatId: str | None = None
    confirm: bool = False


class DamageBody(BaseModel):
    uuid: str
    amount: float
    mode: str = "damage"
    type: str | None = None
    multiplier: float | None = None


class RestBody(BaseModel):
    uuid: str
    type: str = "long"
    hitDice: int | None = None


class SceneSwitchBody(BaseModel):
    id: str | None = None
    name: str | None = None
    activate: bool = False


def register_v1(
    app: FastAPI,
    hub: Hub,
    settings: Settings,
    api_token: Callable[[Request, str], Token],
    pick_client: Callable[[Token | None, str | None], Client],
    activity: ActivityLog,
) -> None:
    async def run(
        request: Request,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        write: bool = False,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        rec = api_token(request, "write" if write else "read")
        clean = {k: v for k, v in (data or {}).items() if v is not None}
        world_id: str | None = None

        def note(ok: bool, error: str | None = None) -> None:
            if write:
                activity.add(token_id=rec.id, token_name=rec.name, world_id=world_id, kind=kind,
                             data=clean, ok=ok, error=error)

        try:
            client = pick_client(rec, client_id)
            world_id = client.info.get("worldId")
            if write and not settings.world_may_write(world_id):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Writes are not allowed in world {world_id}. "
                        f"Allowed worlds: {settings.write_worlds}. Change write_worlds in the add-on options."
                    ),
                )
            result = await hub.request(client, kind, clean)
        except FoundryError as exc:
            note(False, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HubError as exc:
            note(False, str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HTTPException as exc:
            note(False, str(exc.detail))
            raise
        note(True)
        return {"ok": True, "clientId": client.client_id, "data": result}

    # ----- read -----

    @app.get("/api/v1/world")
    async def world(request: Request, client_id: str | None = None):
        return await run(request, "world", client_id=client_id)

    @app.get("/api/v1/documents/{document_type}")
    async def list_documents(document_type: str, request: Request, q: str | None = None,
                             limit: int | None = None, client_id: str | None = None):
        return await run(request, "list", {"documentType": document_type, "q": q, "limit": limit}, client_id=client_id)

    @app.get("/api/v1/document")
    async def get_document(request: Request, uuid: str, source: bool = False, client_id: str | None = None):
        return await run(request, "get", {"uuid": uuid, "source": source}, client_id=client_id)

    @app.get("/api/v1/chat")
    async def get_chat(request: Request, limit: int | None = None, client_id: str | None = None):
        return await run(request, "chat", {"limit": limit}, client_id=client_id)

    @app.get("/api/v1/encounters")
    async def encounters(request: Request, client_id: str | None = None):
        return await run(request, "encounters", client_id=client_id)

    @app.get("/api/v1/effects")
    async def effects(request: Request, uuid: str, client_id: str | None = None):
        return await run(request, "effects", {"uuid": uuid}, client_id=client_id)

    @app.get("/api/v1/scene")
    async def scene(request: Request, id: str | None = None, name: str | None = None,
                    viewed: bool = False, client_id: str | None = None):
        return await run(request, "scene", {"id": id, "name": name, "viewed": viewed or None}, client_id=client_id)

    @app.get("/api/v1/users")
    async def users(request: Request, client_id: str | None = None):
        return await run(request, "users", client_id=client_id)

    @app.get("/api/v1/activity")
    async def get_activity(request: Request, limit: int = 50, token: str | None = None, kind: str | None = None):
        api_token(request, "read")
        return {"ok": True, "data": activity.recent(limit, token, kind)}

    @app.get("/api/v1/files")
    async def list_files(request: Request, path: str = "", source: str = "data", client_id: str | None = None):
        return await run(request, "listFiles", {"path": path, "source": source}, client_id=client_id)

    @app.get("/api/v1/file")
    async def read_file(request: Request, path: str, source: str = "data", client_id: str | None = None):
        return await run(request, "readFile", {"path": path, "source": source}, client_id=client_id)

    # ----- write -----

    @app.patch("/api/v1/document")
    async def update_document(body: UpdateBody, request: Request, client_id: str | None = None):
        return await run(request, "update", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/documents/{document_type}")
    async def create_document(document_type: str, body: CreateBody, request: Request, client_id: str | None = None):
        payload = {"documentType": document_type, **body.model_dump()}
        return await run(request, "create", payload, write=True, client_id=client_id)

    @app.delete("/api/v1/document")
    async def delete_document(request: Request, uuid: str, confirm: bool = False, client_id: str | None = None):
        api_token(request, "write")  # 401 and 403 first, then the confirm reminder
        if not confirm:
            raise HTTPException(status_code=400, detail="Deleting cannot be undone. Add confirm=true to really delete.")
        return await run(request, "delete", {"uuid": uuid}, write=True, client_id=client_id)

    @app.post("/api/v1/chat")
    async def send_chat(body: ChatBody, request: Request, client_id: str | None = None):
        return await run(request, "sendChat", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/rolls")
    async def roll(body: RollBody, request: Request, client_id: str | None = None):
        # A roll that posts to chat is a write. A quiet roll only reads dice.
        return await run(request, "roll", body.model_dump(), write=body.chat, client_id=client_id)

    @app.post("/api/v1/items/use")
    async def use_item(body: UseItemBody, request: Request, client_id: str | None = None):
        return await run(request, "useItem", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/tokens/move")
    async def move_token(body: MoveBody, request: Request, client_id: str | None = None):
        return await run(request, "moveToken", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/scene/switch")
    async def switch_scene(body: SceneSwitchBody, request: Request, client_id: str | None = None):
        return await run(request, "switchScene", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/combat")
    async def create_combat(body: CombatCreateBody, request: Request, client_id: str | None = None):
        return await run(request, "combatCreate", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/combat/control")
    async def control_combat(body: CombatControlBody, request: Request, client_id: str | None = None):
        api_token(request, "write")  # 401 and 403 first, then the reminders
        if body.action not in COMBAT_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown combat action {body.action}. Use one of: {', '.join(COMBAT_ACTIONS)}.",
            )
        if body.action == "end" and not body.confirm:
            raise HTTPException(status_code=400, detail="Ending combat removes it. Add confirm=true to really end it.")
        payload = {"action": body.action, "combatId": body.combatId}
        return await run(request, "combatControl", payload, write=True, client_id=client_id)

    @app.post("/api/v1/damage")
    async def apply_damage(body: DamageBody, request: Request, client_id: str | None = None):
        api_token(request, "write")
        if body.mode not in DAMAGE_MODES:
            raise HTTPException(status_code=400, detail=f"Unknown mode {body.mode}. Use one of: {', '.join(DAMAGE_MODES)}.")
        if body.amount < 0:
            raise HTTPException(status_code=400, detail="Amount cannot be negative. Use mode heal to add hit points.")
        return await run(request, "applyDamage", body.model_dump(), write=True, client_id=client_id)

    @app.post("/api/v1/rest")
    async def rest(body: RestBody, request: Request, client_id: str | None = None):
        api_token(request, "write")
        if body.type not in REST_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown rest type {body.type}. Use one of: {', '.join(REST_TYPES)}.")
        if body.hitDice is not None:
            if not 0 <= body.hitDice <= 20:
                raise HTTPException(status_code=400, detail="hitDice must be a whole number from 0 to 20.")
            if body.hitDice > 0 and body.type != "short":
                raise HTTPException(status_code=400, detail="Hit dice are only spent on a short rest.")
        return await run(request, "rest", body.model_dump(exclude_none=True), write=True, client_id=client_id)
