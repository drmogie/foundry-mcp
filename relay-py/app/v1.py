"""The REST API. Each route asks the connected Foundry client to do one thing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .hub import Client, FoundryError, Hub, HubError
from .settings import Settings
from .tokens import Token


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
        try:
            client = pick_client(rec, client_id)
            if write and not settings.world_may_write(client.info.get("worldId")):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Writes are not allowed in world {client.info.get('worldId')}. "
                        f"Allowed worlds: {settings.write_worlds}. Change write_worlds in the add-on options."
                    ),
                )
            clean = {k: v for k, v in (data or {}).items() if v is not None}
            result = await hub.request(client, kind, clean)
        except FoundryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HubError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
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
