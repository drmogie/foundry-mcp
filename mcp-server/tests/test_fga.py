"""The FGA client, against a pretend FGA relay."""

import base64
import json

import httpx
import pytest

from foundry_mcp import server
from foundry_mcp.client import RelayClient, RelayError
from foundry_mcp.fga import FgaClient

CLIENTS = {"clients": [{"clientId": "mcp-test:1", "worldId": "mcp-test", "worldTitle": "MCP Test"}]}

BOB = {
    "name": "Bob", "type": "character",
    "system": {"attributes": {"hp": {"value": 87}}, "abilities": {"dex": {"value": 20}}, "resources": {}, "currency": {}, "details": {}},
    "items": [
        {"_id": "i1", "name": "Shortbow", "type": "weapon", "system": {"quantity": 1, "equipped": True}},
        {"_id": "i2", "name": "Fire Bolt", "type": "spell", "system": {"level": 0}},
        {"_id": "i3", "name": "Sneak Attack", "type": "feat", "system": {}},
    ],
}
SCENE = {"id": "s1", "name": "Tavern", "data": {"name": "Tavern", "tokens": [
    {"_id": "t1", "name": "Bob"}, {"_id": "t2", "name": "Foreman"}, {"_id": "t3", "name": "Guard"}, {"_id": "t4", "name": "Guard"}]}}


class Relay:
    def __init__(self):
        self.calls = []
        self.chat = [
            {"id": "m1", "timestamp": 1, "author": "GM", "alias": "Bob", "content": "hi", "whisper": [], "rolls": []},
            {"id": "m2", "timestamp": 2, "author": "GM", "alias": "Foreman", "content": "roll", "whisper": [], "rolls": [{"formula": "1d20", "total": 9}]},
            {"id": "m3", "timestamp": 3, "author": "GM", "alias": "Bob", "content": "psst", "whisper": ["u1"], "rolls": []},
        ]
        self.fail = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, dict(request.url.params), body))
        assert request.headers["x-api-key"] == "fgat_test"
        if self.fail:
            return httpx.Response(self.fail[0], json={"detail": self.fail[1]})
        path, method = request.url.path, request.method
        q = request.url.params

        def ok(data):
            return httpx.Response(200, json={"ok": True, "clientId": "mcp-test:1", "data": data})

        if path == "/api/v1/clients":
            return httpx.Response(200, json=CLIENTS)
        if path == "/api/v1/world":
            return ok({"id": "mcp-test", "title": "MCP Test"})
        if path.startswith("/api/v1/documents/") and method == "GET":
            t = path.rsplit("/", 1)[1]
            rows = {"Actor": [{"uuid": "Actor.a1", "name": "Bob", "type": "character"}, {"uuid": "Actor.a2", "name": "Foreman", "type": "npc"}],
                    "Item": [{"uuid": "Item.i1", "name": "Shortbow", "type": "weapon"}, {"uuid": "Item.i2", "name": "Longsword", "type": "weapon"},
                             {"uuid": "Item.i3", "name": "Rope", "type": "loot"}]}.get(t, [])
            needle = q.get("q", "").lower()
            rows = [r for r in rows if needle in r["name"].lower()]
            return ok({"total": len(rows), "returned": len(rows), "results": rows})
        if path == "/api/v1/document" and method == "GET":
            return ok({"uuid": q["uuid"], "name": "Bob", "data": BOB})
        if path == "/api/v1/scene":
            return ok(SCENE)
        if path == "/api/v1/users":
            return ok([{"id": "u1", "name": "GM"}])
        if path == "/api/v1/chat" and method == "GET":
            return ok(self.chat[-int(q.get("limit", 20)):])
        if path == "/api/v1/activity":
            return ok([{"id": 2, "token": "writer", "kind": "sendChat", "summary": "sendChat content=hi", "ok": True}])
        if path == "/api/v1/encounters":
            return ok([])
        if path == "/api/v1/effects":
            return ok({"effects": []})
        if path == "/api/v1/files":
            here = q.get("path", "")
            if here.endswith("/scripts"):
                return ok({"path": here, "dirs": [], "files": [f"{here}/main.mjs"]})
            return ok({"path": here, "dirs": [f"{here}/scripts"], "files": [f"{here}/module.json"]})
        if path == "/api/v1/file":
            return ok({"path": q["path"], "size": 5, "mimeType": "application/json", "base64": base64.b64encode(b'{"a":1}').decode()})
        return ok({"echo": path, "method": method})


@pytest.fixture
def relay(monkeypatch):
    r = Relay()
    monkeypatch.setattr(server, "_client", FgaClient(base_url="http://relay", api_key="fgat_test", transport=httpx.MockTransport(r)))
    return r


def last(relay):
    return relay.calls[-1]


# ----- which client is used -----

def test_make_client_is_always_the_fga_client(monkeypatch):
    for key in ("fgat_abc", "abc123", ""):
        monkeypatch.setenv("FOUNDRY_API_KEY", key)
        assert isinstance(server.make_client(), FgaClient)


def test_default_address_is_the_lan_relay(monkeypatch):
    monkeypatch.delenv("FOUNDRY_RELAY_URL", raising=False)
    assert FgaClient(api_key="fgat_x").base_url == "https://rest-relay.mogie.io"


# ----- reading -----

async def test_list_worlds_and_world_info(relay):
    out = json.loads(await server.foundry_list_worlds())
    assert out["clients"][0]["isOnline"] is True and out["total"] == 1
    assert json.loads(await server.foundry_world_info())["id"] == "mcp-test"


async def test_search_across_types_and_with_filters(relay):
    out = json.loads(await server.foundry_search(query="bow"))
    assert [r["name"] for r in out["results"]] == ["Shortbow"]
    out = json.loads(await server.foundry_search(query="", filter="documentType:Item,subType:weapon"))
    assert [r["name"] for r in out["results"]] == ["Shortbow", "Longsword"]
    out = json.loads(await server.foundry_search(query="", filter="Actor", limit=1))
    assert len(out["results"]) == 1
    assert last(relay)[1] == "/api/v1/documents/Actor"


async def test_structure_lists_types(relay):
    out = json.loads(await server.foundry_structure(types="Actor,Item"))
    assert set(out["types"]) == {"Actor", "Item"}


async def test_get_and_actor_details(relay):
    assert json.loads(await server.foundry_get("Actor.a1"))["name"] == "Bob"
    out = json.loads(await server.foundry_actor_details("Actor.a1"))
    assert [i["name"] for i in out["items"]] == ["Shortbow"]
    assert [i["name"] for i in out["spells"]] == ["Fire Bolt"]
    assert [i["name"] for i in out["features"]] == ["Sneak Attack"]
    assert out["resources"]["attributes"]["hp"]["value"] == 87
    only = json.loads(await server.foundry_actor_details("Actor.a1", details=["spells"]))
    assert "items" not in only and "spells" in only


async def test_scene_users_encounters_effects_macros(relay):
    assert json.loads(await server.foundry_get_scene(active=True))["name"] == "Tavern"
    assert json.loads(await server.foundry_get_scene(all=True)) == []
    assert json.loads(await server.foundry_list_users())[0]["name"] == "GM"
    assert json.loads(await server.foundry_get_encounters()) == []
    assert json.loads(await server.foundry_get_effects("Actor.a1")) == {"effects": []}
    assert json.loads(await server.foundry_list_macros()) == []


async def test_chat_filters(relay):
    all3 = json.loads(await server.foundry_get_chat(limit=10))
    assert [m["id"] for m in all3] == ["m1", "m2", "m3"]
    assert [m["id"] for m in json.loads(await server.foundry_get_chat(limit=10, speaker="foreman"))] == ["m2"]
    assert [m["id"] for m in json.loads(await server.foundry_get_chat(limit=10, chat_type=4))] == ["m2"]
    assert [m["id"] for m in json.loads(await server.foundry_get_chat(limit=10, chat_type=3))] == ["m3"]
    assert [m["id"] for m in json.loads(await server.foundry_get_chat(limit=1, offset=1))] == ["m2"]


async def test_rolls(relay):
    out = json.loads(await server.foundry_get_rolls())
    assert [r["id"] for r in out] == ["m2"] and out[0]["rolls"][0]["total"] == 9


async def test_files(relay):
    out = json.loads(await server.foundry_list_files(path="modules/fga"))
    assert {i["name"] for i in out["results"]} == {"scripts", "module.json"}
    text = await server.foundry_read_file("modules/fga/module.json")
    assert text == '{"a":1}'
    rec = json.loads(await server.foundry_list_files(path="modules/fga", recursive=True))
    assert {i["name"] for i in rec["results"]} == {"scripts", "module.json", "main.mjs"}


# ----- writing -----

async def test_write_guard_blocks_other_worlds(relay, monkeypatch):
    monkeypatch.setenv("FOUNDRY_WRITE_WORLDS", "some-other-world")
    out = await server.foundry_send_chat("hi")
    assert "Writes are blocked for world 'mcp-test'" in out
    assert all(c[0] == "GET" for c in relay.calls)


async def test_send_chat_and_roll(relay):
    await server.foundry_send_chat("Hello", flavor="F", alias="Narrator", speaker="a1")
    m, path, _q, body = last(relay)
    assert (m, path) == ("POST", "/api/v1/chat")
    assert body == {"content": "Hello", "flavor": "F", "alias": "Narrator", "actorId": "a1"}
    await server.foundry_roll("1d20+5", flavor="Check", create_chat_message=False)
    assert last(relay)[1] == "/api/v1/rolls"
    assert last(relay)[3] == {"formula": "1d20+5", "flavor": "Check", "chat": False}


async def test_create_uses_the_type_in_the_path(relay):
    await server.foundry_create("Actor", {"name": "Guard"}, folder="Folder.f1")
    m, path, _q, body = last(relay)
    assert (m, path) == ("POST", "/api/v1/documents/Actor")
    assert body == {"data": {"name": "Guard", "folder": "Folder.f1"}}


async def test_plain_update_is_a_patch(relay):
    await server.foundry_update("Actor.a1", {"name": "Bobby"})
    m, path, _q, body = last(relay)
    assert (m, path) == ("PATCH", "/api/v1/document")
    assert body == {"uuid": "Actor.a1", "data": {"name": "Bobby"}}


async def test_update_with_items_becomes_creates_on_the_parent(relay):
    item = {"name": "Longbow", "type": "weapon"}
    await server.foundry_update("Actor.a1", {"items": [item], "system": {"attributes": {"hp": {"value": 5}}}})
    writes = [c for c in relay.calls if c[0] in ("POST", "PATCH")]
    assert writes[0][1] == "/api/v1/documents/Item"
    assert writes[0][3] == {"data": [item], "parentUuid": "Actor.a1"}
    assert writes[1][1] == "/api/v1/document" and writes[1][3]["data"] == {"system": {"attributes": {"hp": {"value": 5}}}}


async def test_update_with_only_items_makes_no_patch(relay):
    await server.foundry_update("Actor.a1", {"items": [{"name": "Arrows", "type": "consumable"}]})
    assert [c[0] for c in relay.calls if c[0] in ("POST", "PATCH")] == ["POST"]


async def test_effects_are_created_as_active_effects(relay):
    await server.foundry_update("Actor.a1", {"effects": [{"name": "Bless"}]})
    assert last(relay)[1] == "/api/v1/documents/ActiveEffect"


async def test_delete_needs_confirm_then_sends_it(relay):
    assert "Nothing deleted" in await server.foundry_delete("Actor.a1")
    assert not any(c[0] == "DELETE" for c in relay.calls)
    await server.foundry_delete("Actor.a1", confirm=True)
    m, path, q, _b = last(relay)
    assert (m, path, q) == ("DELETE", "/api/v1/document", {"uuid": "Actor.a1", "confirm": "true"})


async def test_switch_scene_activates(relay):
    await server.foundry_switch_scene(name="Tavern")
    assert last(relay)[3] == {"name": "Tavern", "activate": True}


async def test_use_item_by_name_with_target_by_name(relay):
    await server.foundry_use_item("Actor.a1", ability_name="shortbow", target_name="Foreman")
    m, path, _q, body = last(relay)
    assert (m, path) == ("POST", "/api/v1/items/use")
    assert body == {"uuid": "Actor.a1.Item.i1", "targets": ["Scene.s1.Token.t2"]}


async def test_use_item_by_uuid_without_target(relay):
    await server.foundry_use_item("Actor.a1", ability_uuid="Actor.a1.Item.i1")
    assert last(relay)[3] == {"uuid": "Actor.a1.Item.i1"}


async def test_use_item_unknown_item_lists_what_exists(relay):
    out = await server.foundry_use_item("Actor.a1", ability_name="Banana")
    assert "no item called Banana" in out and "Shortbow" in out
    assert not any(c[1] == "/api/v1/items/use" for c in relay.calls)


async def test_move_token_by_name_and_ambiguous_name(relay):
    await server.foundry_move_token(100, 200, name="Bob")
    assert last(relay)[3] == {"uuid": "Scene.s1.Token.t1", "x": 100, "y": 200}
    out = await server.foundry_move_token(1, 2, name="Guard")
    assert "2 tokens are called Guard" in out
    out = await server.foundry_move_token(1, 2, name="Nobody")
    assert "No token called Nobody" in out


# ----- errors -----

async def test_relay_words_come_through(relay):
    relay.fail = (403, "This token is read only. Make a token with write access.")
    out = await server.foundry_get("Actor.a1")
    assert out == "Error: This token is read only. Make a token with write access."


async def test_missing_token_message(monkeypatch):
    monkeypatch.setattr(server, "_client", FgaClient(base_url="http://relay", api_key=""))
    out = await server.foundry_world_info()
    assert "fgat_" in out


async def test_unreachable_relay(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(server, "_client", FgaClient(base_url="http://relay", api_key="fgat_test", transport=httpx.MockTransport(boom)))
    out = await server.foundry_world_info()
    assert out.startswith("Error: Cannot reach the relay")


async def test_two_clients_need_an_id(monkeypatch):
    two = {"clients": [{"clientId": "a", "worldId": "mcp-test"}, {"clientId": "b", "worldId": "other"}]}
    monkeypatch.setattr(server, "_client", FgaClient(base_url="http://relay", api_key="fgat_test",
                                                     transport=httpx.MockTransport(lambda r: httpx.Response(200, json=two))))
    out = await server.foundry_send_chat("hi")
    assert "More than one Foundry client" in out


# ----- stage 4 -----

async def test_activity_log_passes_filters(relay):
    out = json.loads(await server.foundry_activity_log(limit=5, token="writer", kind="sendChat"))
    assert out[0]["kind"] == "sendChat"
    m, path, q, _b = last(relay)
    assert (m, path) == ("GET", "/api/v1/activity")
    assert q == {"limit": "5", "token": "writer", "kind": "sendChat"}


async def test_start_combat_by_names(relay):
    await server.foundry_start_combat(token_names=["bob", "Guard"])
    m, path, _q, body = last(relay)
    assert (m, path) == ("POST", "/api/v1/combat")
    assert body == {"tokenUuids": ["Scene.s1.Token.t1", "Scene.s1.Token.t3", "Scene.s1.Token.t4"],
                    "rollInitiative": True, "start": True}


async def test_start_combat_all_tokens_and_plain_start(relay):
    await server.foundry_start_combat(all_tokens=True, roll_initiative=False, start=False)
    assert last(relay)[3]["tokenUuids"] == [f"Scene.s1.Token.t{i}" for i in (1, 2, 3, 4)]
    assert last(relay)[3]["rollInitiative"] is False
    await server.foundry_start_combat()
    assert last(relay)[3] == {"rollInitiative": True, "start": True}


async def test_start_combat_unknown_name_changes_nothing(relay):
    out = await server.foundry_start_combat(token_names=["Nobody"])
    assert "No token called nobody" in out and "Nothing was changed" in out
    assert not any(c[0] == "POST" for c in relay.calls)


async def test_combat_turn(relay):
    await server.foundry_combat_turn("nextTurn")
    m, path, _q, body = last(relay)
    assert (m, path, body) == ("POST", "/api/v1/combat/control", {"action": "nextTurn", "confirm": False})


async def test_ending_combat_needs_confirm(relay):
    out = await server.foundry_combat_turn("end")
    assert "confirm=true" in out
    assert not any(c[0] == "POST" for c in relay.calls)
    await server.foundry_combat_turn("end", combat_id="c1", confirm=True)
    assert last(relay)[3] == {"action": "end", "combatId": "c1", "confirm": True}


async def test_apply_damage_by_uuid_and_by_name(relay):
    await server.foundry_apply_damage(7, uuid="Actor.a1", damage_type="fire", multiplier=0.5)
    m, path, _q, body = last(relay)
    assert (m, path) == ("POST", "/api/v1/damage")
    assert body == {"uuid": "Actor.a1", "amount": 7, "mode": "damage", "type": "fire", "multiplier": 0.5}
    await server.foundry_apply_damage(3, name="Foreman", mode="heal")
    assert last(relay)[3] == {"uuid": "Scene.s1.Token.t2", "amount": 3, "mode": "heal"}
    assert "exactly one" in await server.foundry_apply_damage(1)


async def test_stage_4_tools_explain_when_not_on_our_relay(monkeypatch):
    monkeypatch.setattr(server, "_client", RelayClient(base_url="http://relay", api_key="k"))
    for out in (
        await server.foundry_start_combat(),
        await server.foundry_combat_turn("nextTurn"),
        await server.foundry_apply_damage(1, uuid="Actor.a1"),
        await server.foundry_activity_log(),
    ):
        assert "FGA relay" in out and "fgat_" in out


async def test_rest_by_uuid_and_by_name(relay):
    await server.foundry_rest(uuid="Actor.a1")
    m, path, _q, body = last(relay)
    assert (m, path, body) == ("POST", "/api/v1/rest", {"uuid": "Actor.a1", "type": "long"})
    await server.foundry_rest(rest_type="short", name="Foreman")
    assert last(relay)[3] == {"uuid": "Scene.s1.Token.t2", "type": "short"}
    assert "exactly one" in await server.foundry_rest()
    await server.foundry_rest(rest_type="short", uuid="Actor.a1", hit_dice=3)
    assert last(relay)[3] == {"uuid": "Actor.a1", "type": "short", "hitDice": 3}


async def test_rest_explains_when_not_on_our_relay(monkeypatch):
    monkeypatch.setattr(server, "_client", RelayClient(base_url="http://relay", api_key="k"))
    assert "FGA relay" in await server.foundry_rest(uuid="Actor.a1")
