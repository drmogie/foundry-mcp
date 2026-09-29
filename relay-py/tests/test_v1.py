"""The REST routes, tested against a real relay with a pretend Foundry client on the socket."""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
import websockets

from app.main import create_app
from app.settings import Settings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp_path, write_worlds="mcp-test"):
    settings = Settings(data_dir=tmp_path, admin_username="mogie", admin_password="secret", write_worlds=write_worlds)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return f"127.0.0.1:{port}", server, thread


@pytest.fixture()
def relay(tmp_path):
    host, server, thread = start(tmp_path)
    yield host
    server.should_exit = True
    thread.join(5)


@pytest.fixture()
def locked_relay(tmp_path):
    host, server, thread = start(tmp_path, write_worlds="some-other-world")
    yield host
    server.should_exit = True
    thread.join(5)


def hello(world="mcp-test"):
    return {"type": "hello", "clientId": f"{world}:1", "worldId": world, "worldTitle": world}


class Foundry:
    """A pretend Foundry client. Records every command and answers it."""

    def __init__(self, host, key, world="mcp-test", errors=None):
        self.host, self.key, self.world = host, key, world
        self.errors = errors or {}
        self.seen = []
        self._ws = None
        self._task = None

    async def __aenter__(self):
        self._ws = await websockets.connect(f"ws://{self.host}/ws/module?key={self.key}")
        await self._ws.send(json.dumps(hello(self.world)))
        await self._ws.recv()
        self._task = asyncio.create_task(self._loop())
        return self

    async def _loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" not in msg:
                    continue
                self.seen.append((msg["type"], msg["data"]))
                if msg["type"] in self.errors:
                    reply = {"id": msg["id"], "ok": False, "error": self.errors[msg["type"]]}
                else:
                    reply = {"id": msg["id"], "ok": True, "data": {"echo": msg["type"], "got": msg["data"]}}
                await self._ws.send(json.dumps(reply))
        except websockets.ConnectionClosed:
            pass

    async def __aexit__(self, *exc):
        self._task.cancel()
        await self._ws.close()


async def setup(host, **token_body):
    web = httpx.AsyncClient(base_url=f"http://{host}")
    assert (await web.post("/api/login", json={"username": "mogie", "password": "secret"})).status_code == 200
    key = (await web.get("/api/connect")).json()["key"]
    api = None
    if token_body:
        token = (await web.post("/api/tokens", json=token_body)).json()["token"]
        api = httpx.AsyncClient(base_url=f"http://{host}", headers={"x-api-key": token})
    return web, key, api


# ----- reading -----

@pytest.mark.asyncio
async def test_read_routes_send_the_right_command(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        assert (await api.get("/api/v1/world")).status_code == 200
        r = await api.get("/api/v1/documents/Actor", params={"q": "bob", "limit": 5})
        assert r.status_code == 200 and r.json()["data"]["echo"] == "list"
        await api.get("/api/v1/document", params={"uuid": "Actor.a1", "source": "true"})
        await api.get("/api/v1/chat", params={"limit": 3})
        await api.get("/api/v1/encounters")
        await api.get("/api/v1/effects", params={"uuid": "Actor.a1"})
        await api.get("/api/v1/scene", params={"name": "Tavern"})
        await api.get("/api/v1/users")
        assert f.seen == [
            ("world", {}),
            ("list", {"documentType": "Actor", "q": "bob", "limit": 5}),
            ("get", {"uuid": "Actor.a1", "source": True}),
            ("chat", {"limit": 3}),
            ("encounters", {}),
            ("effects", {"uuid": "Actor.a1"}),
            ("scene", {"name": "Tavern"}),
            ("users", {}),
        ]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_empty_options_are_not_sent(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        await api.get("/api/v1/documents/Item")
        assert f.seen == [("list", {"documentType": "Item"})]
    await api.aclose(); await web.aclose()


# ----- scopes -----

@pytest.mark.asyncio
async def test_read_token_cannot_write(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        calls = [
            api.patch("/api/v1/document", json={"uuid": "Actor.a1", "data": {"name": "x"}}),
            api.post("/api/v1/documents/Item", json={"data": {"name": "x"}}),
            api.delete("/api/v1/document", params={"uuid": "Actor.a1", "confirm": "true"}),
            api.post("/api/v1/chat", json={"content": "hi"}),
            api.post("/api/v1/rolls", json={"formula": "1d20"}),
            api.post("/api/v1/items/use", json={"uuid": "Item.i1"}),
            api.post("/api/v1/tokens/move", json={"uuid": "Token.t1", "x": 1, "y": 2}),
            api.post("/api/v1/scene/switch", json={"name": "Cave"}),
        ]
        for coro in calls:
            r = await coro
            assert r.status_code == 403, r.text
            assert "read only" in r.json()["detail"]
        assert f.seen == []
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_quiet_roll_is_allowed_for_read_tokens(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        r = await api.post("/api/v1/rolls", json={"formula": "2d6", "chat": False})
        assert r.status_code == 200
        assert f.seen == [("roll", {"formula": "2d6", "chat": False})]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_write_token_can_write_everything(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    async with Foundry(relay, key) as f:
        assert (await api.patch("/api/v1/document", json={"uuid": "Actor.a1", "data": {"name": "x"}})).status_code == 200
        assert (await api.post("/api/v1/documents/Item", json={"data": {"name": "Arrows"}, "parentUuid": "Actor.a1"})).status_code == 200
        assert (await api.delete("/api/v1/document", params={"uuid": "Item.i1", "confirm": "true"})).status_code == 200
        assert (await api.post("/api/v1/chat", json={"content": "hi", "alias": "GM"})).status_code == 200
        assert (await api.post("/api/v1/rolls", json={"formula": "1d20", "flavor": "Check"})).status_code == 200
        assert (await api.post("/api/v1/items/use", json={"uuid": "Item.i1", "targets": ["Token.t1"]})).status_code == 200
        assert (await api.post("/api/v1/tokens/move", json={"uuid": "Token.t1", "x": 100, "y": 200})).status_code == 200
        assert (await api.post("/api/v1/scene/switch", json={"name": "Cave", "activate": True})).status_code == 200
        kinds = [k for k, _ in f.seen]
        assert kinds == ["update", "create", "delete", "sendChat", "roll", "useItem", "moveToken", "switchScene"]
        create = f.seen[1][1]
        assert create == {"documentType": "Item", "data": {"name": "Arrows"}, "parentUuid": "Actor.a1"}
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_delete_needs_confirm(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    async with Foundry(relay, key) as f:
        r = await api.delete("/api/v1/document", params={"uuid": "Actor.a1"})
        assert r.status_code == 400 and "confirm=true" in r.json()["detail"]
        assert f.seen == []
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_no_token_means_401_everywhere(relay):
    anon = httpx.AsyncClient(base_url=f"http://{relay}")
    for method, path in [("GET", "/api/v1/world"), ("GET", "/api/v1/documents/Actor"), ("GET", "/api/v1/chat"),
                         ("PATCH", "/api/v1/document"), ("POST", "/api/v1/chat"), ("DELETE", "/api/v1/document")]:
        r = await anon.request(method, path, json={} if method in ("PATCH", "POST") else None)
        assert r.status_code in (401, 422), (method, path, r.status_code)
    r = await anon.get("/api/v1/world")
    assert r.status_code == 401
    await anon.aclose()


# ----- the world guard -----

@pytest.mark.asyncio
async def test_writes_blocked_outside_allowed_worlds(locked_relay):
    web, key, api = await setup(locked_relay, name="w", scope="write")
    async with Foundry(locked_relay, key, world="mcp-test") as f:
        r = await api.post("/api/v1/chat", json={"content": "hi"})
        assert r.status_code == 403
        assert "write_worlds" in r.json()["detail"] and "mcp-test" in r.json()["detail"]
        assert (await api.get("/api/v1/world")).status_code == 200   # reading is fine
        assert [k for k, _ in f.seen] == ["world"]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_star_allows_every_world(tmp_path):
    host, server, thread = start(tmp_path, write_worlds="*")
    try:
        web, key, api = await setup(host, name="w", scope="write")
        async with Foundry(host, key, world="the-real-campaign"):
            assert (await api.post("/api/v1/chat", json={"content": "hi"})).status_code == 200
        await api.aclose(); await web.aclose()
    finally:
        server.should_exit = True
        thread.join(5)


# ----- errors -----

@pytest.mark.asyncio
async def test_foundry_errors_come_back_as_400(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key, errors={"get": "Nothing found for Actor.nope"}):
        r = await api.get("/api/v1/document", params={"uuid": "Actor.nope"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Nothing found for Actor.nope"
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_no_foundry_client_is_502_with_plain_words(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    r = await api.get("/api/v1/world")
    assert r.status_code == 502
    assert "No Foundry client" in r.json()["detail"]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_world_limited_token_uses_only_its_world(relay):
    web, key, api = await setup(relay, name="r", scope="read", worldId="some-other-world")
    async with Foundry(relay, key, world="mcp-test") as f:
        r = await api.get("/api/v1/world")
        assert r.status_code == 502 and "some-other-world" in r.json()["detail"]
        assert f.seen == []
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_two_clients_need_a_client_id(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key, world="mcp-test") as a:
        async with Foundry(relay, key, world="second-world") as b:
            r = await api.get("/api/v1/world")
            assert r.status_code == 502 and "client_id" in r.json()["detail"]
            r = await api.get("/api/v1/world", params={"client_id": "second-world:1"})
            assert r.status_code == 200 and r.json()["clientId"] == "second-world:1"
            assert [k for k, _ in b.seen] == ["world"] and a.seen == []
    await api.aclose(); await web.aclose()


# ----- files, flavor, and friendly errors -----

@pytest.mark.asyncio
async def test_file_routes_send_the_right_command(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        assert (await api.get("/api/v1/files", params={"path": "modules/fga"})).status_code == 200
        assert (await api.get("/api/v1/file", params={"path": "modules/fga/module.json"})).status_code == 200
        assert f.seen == [
            ("listFiles", {"path": "modules/fga", "source": "data"}),
            ("readFile", {"path": "modules/fga/module.json", "source": "data"}),
        ]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_chat_flavor_is_passed(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    async with Foundry(relay, key) as f:
        await api.post("/api/v1/chat", json={"content": "hi", "flavor": "Test"})
        assert f.seen == [("sendChat", {"content": "hi", "flavor": "Test"})]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_bad_body_gets_plain_words(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    r = await api.post("/api/v1/chat", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str) and detail.startswith("Bad request.") and "quote marks" in detail
    r = await api.post("/api/v1/chat", json={"alias": "x"})
    assert r.status_code == 422 and "content" in r.json()["detail"]
    await api.aclose(); await web.aclose()


# ----- stage 4: combat, damage, activity -----

@pytest.mark.asyncio
async def test_combat_and_damage_routes_send_the_right_command(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    async with Foundry(relay, key) as f:
        r = await api.post("/api/v1/combat", json={"tokenUuids": ["Scene.s.Token.t1"], "rollInitiative": True, "start": True})
        assert r.status_code == 200
        for action in ("nextTurn", "rollAll"):
            assert (await api.post("/api/v1/combat/control", json={"action": action})).status_code == 200
        assert (await api.post("/api/v1/combat/control", json={"action": "end", "confirm": True, "combatId": "c1"})).status_code == 200
        assert (await api.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": 7, "type": "fire"})).status_code == 200
        assert (await api.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": 3, "mode": "heal"})).status_code == 200
        assert f.seen == [
            ("combatCreate", {"tokenUuids": ["Scene.s.Token.t1"], "rollInitiative": True, "start": True}),
            ("combatControl", {"action": "nextTurn"}),
            ("combatControl", {"action": "rollAll"}),
            ("combatControl", {"action": "end", "combatId": "c1"}),
            ("applyDamage", {"uuid": "Actor.a1", "amount": 7.0, "mode": "damage", "type": "fire"}),
            ("applyDamage", {"uuid": "Actor.a1", "amount": 3.0, "mode": "heal"}),
        ]
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_combat_mistakes_get_plain_words(relay):
    web, key, api = await setup(relay, name="w", scope="write")
    async with Foundry(relay, key) as f:
        r = await api.post("/api/v1/combat/control", json={"action": "end"})
        assert r.status_code == 400 and "confirm=true" in r.json()["detail"]
        r = await api.post("/api/v1/combat/control", json={"action": "dance"})
        assert r.status_code == 400 and "nextTurn" in r.json()["detail"]
        r = await api.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": -2})
        assert r.status_code == 400 and "heal" in r.json()["detail"]
        r = await api.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": 2, "mode": "zap"})
        assert r.status_code == 400
        assert f.seen == []
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_read_token_cannot_fight(relay):
    web, key, api = await setup(relay, name="r", scope="read")
    async with Foundry(relay, key) as f:
        assert (await api.post("/api/v1/combat", json={})).status_code == 403
        assert (await api.post("/api/v1/combat/control", json={"action": "nextTurn"})).status_code == 403
        assert (await api.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": 1})).status_code == 403
        assert f.seen == []
    await api.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_activity_log_records_writes_by_token(relay):
    web, key, wapi = await setup(relay, name="writer", scope="write")
    token = (await web.post("/api/tokens", json={"name": "reader", "scope": "read"})).json()["token"]
    rapi = httpx.AsyncClient(base_url=f"http://{relay}", headers={"x-api-key": token})
    async with Foundry(relay, key, errors={"applyDamage": "No hit points here."}) as f:
        await rapi.get("/api/v1/world")  # reads are not logged
        await wapi.post("/api/v1/chat", json={"content": "hi"})
        await wapi.post("/api/v1/damage", json={"uuid": "Actor.a1", "amount": 4})
        rows = (await rapi.get("/api/v1/activity")).json()["data"]
        assert [r["kind"] for r in rows] == ["applyDamage", "sendChat"]  # newest first
        assert rows[0]["ok"] is False and rows[0]["error"] == "No hit points here."
        assert rows[1]["ok"] is True and rows[1]["token"] == "writer" and rows[1]["worldId"] == "mcp-test"
        assert "content=hi" in rows[1]["summary"]
        only = (await rapi.get("/api/v1/activity", params={"kind": "sendChat"})).json()["data"]
        assert len(only) == 1
        none = (await rapi.get("/api/v1/activity", params={"token": "reader"})).json()["data"]
        assert none == []
    await rapi.aclose(); await wapi.aclose(); await web.aclose()


@pytest.mark.asyncio
async def test_activity_needs_a_token_and_logs_blocked_writes(locked_relay):
    web, key, api = await setup(locked_relay, name="w", scope="write")
    anon = httpx.AsyncClient(base_url=f"http://{locked_relay}")
    assert (await anon.get("/api/v1/activity")).status_code == 401
    async with Foundry(locked_relay, key):
        assert (await api.post("/api/v1/chat", json={"content": "hi"})).status_code == 403
        rows = (await api.get("/api/v1/activity")).json()["data"]
        assert rows[0]["ok"] is False and "not allowed" in rows[0]["error"]
    await anon.aclose(); await api.aclose(); await web.aclose()
