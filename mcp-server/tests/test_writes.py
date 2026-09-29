import json

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from foundry_mcp import server
from foundry_mcp.client import RelayClient

TEST_WORLD = {"clientId": "t1", "worldId": "mcp-test", "worldTitle": "MCP Test", "isOnline": True}
PROD_WORLD = {"clientId": "p1", "worldId": "the-real-campaign", "worldTitle": "Real", "isOnline": True}


def install(monkeypatch, clients, client_id="", status=200, reply=None):
    """Pretend relay. Returns the list of non-/clients requests it received."""
    writes = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/clients":
            return httpx.Response(200, json={"total": len(clients), "clients": clients})
        writes.append(request)
        return httpx.Response(status, json=reply if reply is not None else {"ok": True})

    monkeypatch.setattr(
        server,
        "_client",
        RelayClient(base_url="http://relay", api_key="k", client_id=client_id, transport=httpx.MockTransport(handler)),
    )
    return writes


def body(req: httpx.Request):
    return json.loads(req.content) if req.content else None


# ---- registration -----------------------------------------------------------


async def test_write_tools_register_only_when_asked():
    temp = FastMCP("temp")
    assert await temp.list_tools() == []
    server.register_write_tools(temp)
    names = {t.name for t in await temp.list_tools()}
    assert names == {
        "foundry_send_chat",
        "foundry_roll",
        "foundry_create",
        "foundry_update",
        "foundry_delete",
        "foundry_switch_scene",
        "foundry_use_item",
        "foundry_move_token",
        "foundry_start_combat",
        "foundry_combat_turn",
        "foundry_apply_damage",
    }


def test_writes_flag(monkeypatch):
    monkeypatch.delenv("FOUNDRY_ALLOW_WRITES", raising=False)
    assert server.writes_enabled() is False
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("FOUNDRY_ALLOW_WRITES", value)
        assert server.writes_enabled() is True
    monkeypatch.setenv("FOUNDRY_ALLOW_WRITES", "no")
    assert server.writes_enabled() is False


# ---- the world guard --------------------------------------------------------


async def test_write_goes_to_the_test_world(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    out = await server.foundry_send_chat("hello", flavor="test")
    assert "Error" not in out
    (req,) = sent
    assert req.method == "POST" and req.url.path == "/chat"
    assert req.url.params["clientId"] == "t1"
    assert body(req) == {"content": "hello", "flavor": "test"}  # empty fields are dropped


async def test_write_blocked_on_other_worlds(monkeypatch):
    sent = install(monkeypatch, [PROD_WORLD])
    out = await server.foundry_send_chat("hello")
    assert "Writes are blocked for world 'the-real-campaign'" in out
    assert "Nothing was changed" in out
    assert sent == []  # nothing left the building


async def test_configured_client_id_cannot_dodge_the_guard(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD, PROD_WORLD], client_id="p1")
    out = await server.foundry_roll("1d20")
    assert "blocked" in out
    assert sent == []


async def test_two_worlds_online_needs_a_choice_and_sends_nothing(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD, PROD_WORLD])
    out = await server.foundry_roll("1d20")
    assert "More than one world" in out
    assert sent == []


async def test_allowlist_can_be_widened(monkeypatch):
    monkeypatch.setenv("FOUNDRY_WRITE_WORLDS", "mcp-test, the-real-campaign")
    sent = install(monkeypatch, [PROD_WORLD])
    await server.foundry_roll("1d20")
    assert len(sent) == 1


async def test_offline_world_is_refused(monkeypatch):
    sent = install(monkeypatch, [{**TEST_WORLD, "isOnline": False}], client_id="t1")
    out = await server.foundry_roll("1d20")
    assert "not online" in out
    assert sent == []


async def test_every_write_is_logged(monkeypatch, capsys):
    install(monkeypatch, [TEST_WORLD])
    await server.foundry_roll("2d6")
    err = capsys.readouterr().err
    assert "WRITE POST /roll world=mcp-test" in err


async def test_relay_errors_are_explained(monkeypatch):
    install(monkeypatch, [TEST_WORLD], status=400, reply={"error": "bad formula"})
    out = await server.foundry_roll("banana")
    assert "Relay error 400" in out and "bad formula" in out


# ---- each tool --------------------------------------------------------------


async def test_roll(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    await server.foundry_roll("1d20 + 5", flavor="Attack", create_chat_message=False)
    assert body(sent[0]) == {"formula": "1d20 + 5", "flavor": "Attack", "createChatMessage": False}


async def test_create(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    await server.foundry_create("Actor", {"name": "Goblin", "type": "npc"})
    assert sent[0].method == "POST" and sent[0].url.path == "/create"
    assert body(sent[0]) == {"entityType": "Actor", "data": {"name": "Goblin", "type": "npc"}}


async def test_update(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    await server.foundry_update("Actor.abc", {"name": "Renamed"})
    assert sent[0].method == "PUT" and sent[0].url.path == "/update"
    assert sent[0].url.params["uuid"] == "Actor.abc"
    assert body(sent[0]) == {"data": {"name": "Renamed"}}


async def test_delete_needs_confirm(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    out = await server.foundry_delete("Actor.abc")
    assert "Nothing deleted" in out and "confirm=true" in out
    assert sent == []
    await server.foundry_delete("Actor.abc", confirm=True)
    assert sent[0].method == "DELETE" and sent[0].url.params["uuid"] == "Actor.abc"


async def test_switch_scene_needs_exactly_one(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    assert "exactly one" in await server.foundry_switch_scene()
    assert "exactly one" in await server.foundry_switch_scene(scene_id="a", name="b")
    assert sent == []
    await server.foundry_switch_scene(name="Chess Arena")
    assert body(sent[0]) == {"name": "Chess Arena"}


async def test_use_item(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    assert "exactly one" in await server.foundry_use_item("Actor.a")
    await server.foundry_use_item("Actor.a", ability_name="Longbow", target_name="Goblin")
    assert sent[0].url.path == "/dnd5e/use-item"
    assert body(sent[0]) == {"actorUuid": "Actor.a", "abilityName": "Longbow", "targetName": "Goblin"}


async def test_move_token(monkeypatch):
    sent = install(monkeypatch, [TEST_WORLD])
    assert "exactly one" in await server.foundry_move_token(1, 2)
    await server.foundry_move_token(100, 250.5, name="Bob")
    assert sent[0].url.path == "/move-token"
    assert body(sent[0]) == {"x": 100, "y": 250.5, "name": "Bob", "animate": True}


async def test_no_execute_js_tool():
    temp = FastMCP("temp")
    server.register_write_tools(temp)
    names = " ".join(t.name for t in await temp.list_tools())
    assert "execute" not in names and "js" not in names
