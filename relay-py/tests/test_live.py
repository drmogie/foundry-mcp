"""Tests against a real running relay, so the socket and the API really talk to each other."""

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


@pytest.fixture()
def relay(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_username="mogie", admin_password="secret")
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def hello(**extra):
    return {"type": "hello", "clientId": "w:1", "worldId": "mcp-test", "worldTitle": "MCP Test",
            "foundryVersion": "14.368", "systemId": "dnd5e", "systemVersion": "6.0.5", **extra}


async def logged_in(host):
    http = httpx.AsyncClient(base_url=f"http://{host}")
    r = await http.post("/api/login", json={"username": "mogie", "password": "secret"})
    assert r.status_code == 200
    key = (await http.get("/api/connect")).json()["key"]
    return http, key


@pytest.mark.asyncio
async def test_client_shows_in_status_and_ping_round_trips(relay):
    http, key = await logged_in(relay)
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as ws:
        await ws.send(json.dumps(hello()))
        assert json.loads(await ws.recv())["type"] == "welcome"

        clients = (await http.get("/api/status")).json()["clients"]
        assert [c["worldId"] for c in clients] == ["mcp-test"]

        async def foundry():
            req = json.loads(await ws.recv())
            assert req["type"] == "ping"
            await ws.send(json.dumps({"id": req["id"], "ok": True, "data": {"pong": True}}))

        task = asyncio.create_task(foundry())
        r = await http.post("/api/ping")
        await task
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["reply"] == {"pong": True} and body["clientId"] == "w:1"
    await asyncio.sleep(0.2)
    assert (await http.get("/api/status")).json()["clients"] == []
    await http.aclose()


@pytest.mark.asyncio
async def test_ping_reports_foundry_errors(relay):
    http, key = await logged_in(relay)
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()

        async def foundry():
            req = json.loads(await ws.recv())
            await ws.send(json.dumps({"id": req["id"], "ok": False, "error": "Unknown command: ping"}))

        task = asyncio.create_task(foundry())
        r = await http.post("/api/ping")
        await task
    assert r.status_code == 502
    assert "Unknown command" in r.json()["detail"]
    await http.aclose()


@pytest.mark.asyncio
async def test_new_key_disconnects_foundry(relay):
    http, key = await logged_in(relay)
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()
        await http.post("/api/connect/regenerate")
        with pytest.raises(websockets.ConnectionClosed) as info:
            await asyncio.wait_for(ws.recv(), 5)
        assert info.value.rcvd.code == 4401
    await http.aclose()


@pytest.mark.asyncio
async def test_second_connection_with_same_id_replaces_first(relay):
    http, key = await logged_in(relay)
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as first:
        await first.send(json.dumps(hello()))
        await first.recv()
        async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as second:
            await second.send(json.dumps(hello()))
            await second.recv()
            with pytest.raises(websockets.ConnectionClosed) as info:
                await asyncio.wait_for(first.recv(), 5)
            assert info.value.rcvd.code == 4409
            clients = (await http.get("/api/status")).json()["clients"]
            assert len(clients) == 1
    await http.aclose()


async def make_token(http, **body):
    r = await http.post("/api/tokens", json=body)
    assert r.status_code == 200
    return r.json()["token"]


@pytest.mark.asyncio
async def test_v1_ping_round_trips_with_token(relay):
    http, key = await logged_in(relay)
    token = await make_token(http, name="Claude")
    api = httpx.AsyncClient(base_url=f"http://{relay}", headers={"x-api-key": token})
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()

        async def foundry():
            req = json.loads(await ws.recv())
            await ws.send(json.dumps({"id": req["id"], "ok": True, "data": {"pong": True}}))

        task = asyncio.create_task(foundry())
        r = await api.post("/api/v1/ping")
        await task
        assert r.status_code == 200 and r.json()["reply"] == {"pong": True}
        assert [c["worldId"] for c in (await api.get("/api/v1/clients")).json()["clients"]] == ["mcp-test"]
    await api.aclose()
    await http.aclose()


@pytest.mark.asyncio
async def test_world_limited_token_only_sees_its_world(relay):
    http, key = await logged_in(relay)
    token = await make_token(http, name="Other world", worldId="some-other-world")
    api = httpx.AsyncClient(base_url=f"http://{relay}", headers={"x-api-key": token})
    async with websockets.connect(f"ws://{relay}/ws/module?key={key}") as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()
        assert (await api.get("/api/v1/clients")).json()["clients"] == []
        r = await api.post("/api/v1/ping")
        assert r.status_code == 502
        assert "some-other-world" in r.json()["detail"]
    await api.aclose()
    await http.aclose()
