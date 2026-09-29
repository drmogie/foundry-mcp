"""The relay web app: login page, status, connect key, and the Foundry socket."""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__, auth
from .hub import Client, Hub, HubError
from .v1 import register_v1
from .settings import Settings, load_connect_key, new_connect_key, session_secret
from .tokens import Token, TokenError, TokenStore

log = logging.getLogger("fga-relay")
STATIC = Path(__file__).parent / "static"
HELLO_TIMEOUT = 10.0


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


class TokenBody(BaseModel):
    name: str = ""
    scope: str = "read"
    worldId: str | None = None
    expiresDays: int | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="FGA Relay", version=__version__, docs_url=None, redoc_url=None)
    secret = session_secret(settings)
    hub = Hub()
    limiter = auth.LoginLimiter()
    state: dict[str, Any] = {"connect_key": load_connect_key(settings)}

    tokens = TokenStore(settings.data_dir / "tokens.db")

    app.state.settings = settings
    app.state.hub = hub
    app.state.tokens = tokens

    def who(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def current_user(request: Request) -> str | None:
        if not settings.login_configured:
            return None
        return auth.read_session(secret, request.cookies.get(auth.COOKIE))

    def require_user(request: Request) -> str:
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Please log in.")
        return user

    def api_token(request: Request, needed: str = "read") -> Token:
        """Check the x-api-key header (or Authorization: Bearer) for the /api/v1 routes."""
        offered = request.headers.get("x-api-key")
        if not offered:
            bearer = request.headers.get("authorization", "")
            if bearer.lower().startswith("bearer "):
                offered = bearer[7:].strip()
        rec = tokens.verify(offered)
        if rec is None:
            raise HTTPException(
                status_code=401,
                detail="Missing, wrong or expired API token. Send it in the x-api-key header.",
            )
        if not rec.allows(needed):
            raise HTTPException(status_code=403, detail="This token is read only. Make a token with write access.")
        return rec

    def pick_client(rec: Token | None, client_id: str | None) -> Client:
        """Pick the Foundry client, honoring a token's world limit."""
        if rec is not None and rec.world_id:
            matches = [c for c in hub.clients.values() if c.info.get("worldId") == rec.world_id]
            if client_id:
                matches = [c for c in matches if c.client_id == client_id]
            if not matches:
                raise HubError(f"No Foundry client is connected for world {rec.world_id}, which this token is limited to.")
            if len(matches) > 1:
                raise HubError("More than one Foundry client is connected. Say which one with client_id.")
            return matches[0]
        return hub.pick(client_id)

    def ws_url(request: Request) -> str:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
        scheme = "wss" if proto == "https" else "ws"
        return f"{scheme}://{host}/ws/module"

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/session")
    async def session(request: Request) -> dict[str, Any]:
        return {
            "version": __version__,
            "configured": settings.login_configured,
            "loggedIn": current_user(request) is not None,
        }

    @app.post("/api/login")
    async def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        if not settings.login_configured:
            raise HTTPException(
                status_code=403,
                detail="No login is set. Open the add-on Configuration tab and set a username and password.",
            )
        ip = who(request)
        if limiter.locked(ip):
            raise HTTPException(status_code=429, detail="Too many wrong tries. Wait five minutes and try again.")
        if not auth.check_credentials(settings.admin_username, settings.admin_password, body.username, body.password):
            limiter.fail(ip)
            raise HTTPException(status_code=401, detail="Wrong username or password.")
        limiter.clear(ip)
        response.set_cookie(
            auth.COOKIE,
            auth.make_session(secret, body.username),
            max_age=auth.SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        )
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/api/status")
    async def status(request: Request) -> dict[str, Any]:
        require_user(request)
        return {
            "version": __version__,
            "relay": "up",
            "clients": [c.public() for c in hub.clients.values()],
            "now": time.time(),
        }

    @app.get("/api/connect")
    async def connect_info(request: Request) -> dict[str, Any]:
        require_user(request)
        return {"key": state["connect_key"], "url": ws_url(request)}

    @app.post("/api/connect/regenerate")
    async def regenerate(request: Request) -> dict[str, Any]:
        require_user(request)
        state["connect_key"] = new_connect_key(settings)
        await hub.close_all(4401, "The connect key was replaced")
        return {"key": state["connect_key"], "url": ws_url(request)}

    @app.post("/api/ping")
    async def ping(request: Request, client_id: str | None = None) -> dict[str, Any]:
        require_user(request)
        try:
            client = hub.pick(client_id)
            started = time.perf_counter()
            reply = await hub.request(client, "ping")
        except HubError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "ok": True,
            "ms": round((time.perf_counter() - started) * 1000),
            "clientId": client.client_id,
            "reply": reply,
        }

    # ----- token management (web page login) -----

    @app.get("/api/tokens")
    async def list_tokens(request: Request) -> dict[str, Any]:
        require_user(request)
        now = time.time()
        return {"tokens": [t.public(now) for t in tokens.list()]}

    @app.post("/api/tokens")
    async def create_token(body: TokenBody, request: Request) -> dict[str, Any]:
        require_user(request)
        try:
            secret_value, rec = tokens.create(
                body.name, body.scope, body.worldId, body.expiresDays
            )
        except TokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"token": secret_value, "info": rec.public()}

    @app.delete("/api/tokens/{token_id}")
    async def delete_token(token_id: int, request: Request) -> dict[str, Any]:
        require_user(request)
        if not tokens.delete(token_id):
            raise HTTPException(status_code=404, detail="That token is already gone.")
        return {"ok": True}

    # ----- REST API (API token) -----

    register_v1(app, hub, settings, api_token, pick_client)

    @app.get("/api/v1/whoami")
    async def whoami(request: Request) -> dict[str, Any]:
        rec = api_token(request, "read")
        return {"token": rec.public(), "relayVersion": __version__}

    @app.get("/api/v1/clients")
    async def v1_clients(request: Request) -> dict[str, Any]:
        rec = api_token(request, "read")
        clients = [c.public() for c in hub.clients.values() if not rec.world_id or c.info.get("worldId") == rec.world_id]
        return {"clients": clients}

    @app.post("/api/v1/ping")
    async def v1_ping(request: Request, client_id: str | None = None) -> dict[str, Any]:
        rec = api_token(request, "read")
        try:
            client = pick_client(rec, client_id)
            started = time.perf_counter()
            reply = await hub.request(client, "ping")
        except HubError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": True, "ms": round((time.perf_counter() - started) * 1000), "clientId": client.client_id, "reply": reply}

    @app.websocket("/ws/module")
    async def module_socket(ws: WebSocket) -> None:
        offered = ws.query_params.get("key", "")
        if not hmac.compare_digest(offered.encode(), state["connect_key"].encode()):
            await ws.accept()
            await ws.close(code=4401, reason="Wrong connect key. Copy it again from the relay page.")
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT)
        except Exception:
            await ws.close(code=4400, reason="Expected a hello message first")
            return
        if hello.get("type") != "hello" or not hello.get("clientId"):
            await ws.close(code=4400, reason="Expected a hello message with a clientId")
            return
        client = Client(client_id=str(hello["clientId"]), ws=ws, info=hello)
        hub.add(client)
        log.info("Foundry client %s connected (world %s)", client.client_id, hello.get("worldId"))
        await ws.send_json({"type": "welcome", "relayVersion": __version__})
        try:
            while True:
                message = await ws.receive_json()
                client.last_seen = time.time()
                kind = message.get("type")
                if kind == "heartbeat":
                    await ws.send_json({"type": "heartbeat"})
                elif "id" in message:
                    hub.resolve(message)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("Socket for %s ended: %s", client.client_id, exc)
        finally:
            hub.remove(client)
            log.info("Foundry client %s disconnected", client.client_id)

    return app
