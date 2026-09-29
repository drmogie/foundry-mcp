import base64

import httpx
import pytest

from foundry_mcp import server
from foundry_mcp.client import RelayClient, to_text

CLIENTS = {
    "total": 2,
    "clients": [
        {"clientId": "off1", "worldTitle": "Old", "isOnline": False},
        {"clientId": "on1", "worldTitle": "MCP Test", "isOnline": True},
    ],
}


def make_client(handler, **kw):
    transport = httpx.MockTransport(handler)
    return RelayClient(base_url="http://relay", api_key="k", transport=transport, **kw)


@pytest.fixture
def calls():
    return []


@pytest.fixture
def use_client(calls, monkeypatch):
    def install(extra=None, status=200, **kw):
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            assert request.headers["x-api-key"] == "k"
            if request.url.path == "/clients":
                return httpx.Response(200, json=CLIENTS)
            if extra is not None:
                return httpx.Response(status, json=extra)
            return httpx.Response(200, json={"ok": True, "path": request.url.path})

        monkeypatch.setattr(server, "_client", make_client(handler, **kw))

    return install


async def test_picks_the_online_world(use_client, calls):
    use_client()
    out = await server.foundry_world_info()
    assert '"ok": true' in out
    assert calls[-1].url.params["clientId"] == "on1"


async def test_configured_client_id_skips_lookup(use_client, calls):
    use_client(client_id="fixed")
    await server.foundry_world_info()
    assert [c.url.path for c in calls] == ["/world-info"]
    assert calls[0].url.params["clientId"] == "fixed"


async def test_search_sends_flags_as_text(use_client, calls):
    use_client(client_id="c")
    await server.foundry_search(query="goblin", filter="Actor", limit=5)
    q = calls[-1].url.params
    assert q["query"] == "goblin" and q["minified"] == "true" and q["limit"] == "5"
    assert q["excludeCompendiums"] == "false"


async def test_actor_details_sends_json_array(use_client, calls):
    use_client(client_id="c")
    await server.foundry_actor_details("Actor.a1", ["items", "spells"])
    assert calls[-1].url.params["details"] == '["items", "spells"]'


async def test_scene_needs_exactly_one_choice(use_client):
    use_client(client_id="c")
    assert "exactly one" in await server.foundry_get_scene()
    assert "exactly one" in await server.foundry_get_scene(active=True, all=True)


async def test_scene_active_only_sends_active(use_client, calls):
    use_client(client_id="c")
    await server.foundry_get_scene(active=True)
    q = calls[-1].url.params
    assert q["active"] == "true" and "all" not in q and "sceneId" not in q


async def test_bad_key_is_explained(use_client):
    use_client({"error": "nope"}, status=401, client_id="c")
    assert "rejected the API key" in await server.foundry_get_rolls()


async def test_missing_key(monkeypatch):
    monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
    monkeypatch.setattr(server, "_client", RelayClient(base_url="http://relay", api_key=""))
    assert "No API key" in await server.foundry_list_worlds()


async def test_no_world_online(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"total": 0, "clients": []})

    monkeypatch.setattr(server, "_client", make_client(handler))
    assert "No Foundry world is online" in await server.foundry_world_info()


async def test_two_worlds_online_asks_for_a_choice(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={"clients": [{"clientId": "a", "isOnline": True}, {"clientId": "b", "isOnline": True}]},
        )

    monkeypatch.setattr(server, "_client", make_client(handler))
    assert "FOUNDRY_CLIENT_ID" in await server.foundry_world_info()


async def test_cannot_reach_relay(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(server, "_client", make_client(handler, client_id="c"))
    assert "Cannot reach the relay" in await server.foundry_world_info()


def test_long_replies_are_cut():
    text = to_text({"x": "a" * 100_000})
    assert "cut off" in text and len(text) < 61_000


EXPECTED_TOOLS = {
    "foundry_list_worlds",
    "foundry_world_info",
    "foundry_structure",
    "foundry_search",
    "foundry_get",
    "foundry_actor_details",
    "foundry_get_scene",
    "foundry_list_users",
    "foundry_get_chat",
    "foundry_get_rolls",
    "foundry_get_encounters",
    "foundry_list_macros",
    "foundry_get_effects",
    "foundry_list_files",
    "foundry_read_file",
}


async def test_only_the_expected_read_tools_exist():
    # Adding a tool (especially one that writes) must be a deliberate change to this list.
    names = {t.name for t in await server.mcp.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_every_call_is_a_get(use_client, calls):
    use_client(client_id="c")
    await server.foundry_world_info()
    await server.foundry_get_chat()
    await server.foundry_list_files()
    assert {c.method for c in calls} == {"GET"}


async def test_structure_and_files_pass_a_path_param(use_client, calls):
    use_client(client_id="c")
    await server.foundry_structure(path="Actors/Monsters", types="Actor")
    assert calls[-1].url.path == "/structure"
    assert calls[-1].url.params["path"] == "Actors/Monsters"
    await server.foundry_list_files(path="modules/fga-mount-action", source="data")
    assert calls[-1].url.path == "/file-system"
    assert calls[-1].url.params["path"] == "modules/fga-mount-action"


# ---- file tools -------------------------------------------------------------

TREE = {
    "modules/mymod": [
        {"name": "module.json", "path": "modules/mymod/module.json", "type": "file"},
        {"name": "scripts", "path": "modules/mymod/scripts", "type": "directory"},
        {"name": "node_modules", "path": "modules/mymod/node_modules", "type": "directory"},
        {"name": ".git", "path": "modules/mymod/.git", "type": "directory"},
    ],
    "modules/mymod/scripts": [
        {"name": "main.js", "path": "modules/mymod/scripts/main.js", "type": "file"},
        {"name": "logo.png", "path": "modules/mymod/scripts/logo.png", "type": "file"},
    ],
    "modules/mymod/node_modules": [
        {"name": "skip.js", "path": "modules/mymod/node_modules/skip.js", "type": "file"},
    ],
}
FILES = {
    "modules/mymod/module.json": b'{"id": "mymod", "version": "1"}',
    "modules/mymod/scripts/main.js": b"console.log('hi');",
    "modules/mymod/scripts/logo.png": bytes([0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE, 0x00]),
    "modules/mymod/node_modules/skip.js": b"nope",
}


def file_relay(monkeypatch, tree=TREE, files=FILES):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if request.url.path == "/file-system":
            seen.append(("list", q["path"]))
            return httpx.Response(200, json={"success": True, "results": tree.get(q["path"], [])})
        if request.url.path == "/download":
            seen.append(("get", q["path"]))
            assert q["format"] == "base64"
            body = files.get(q["path"])
            if body is None:
                return httpx.Response(400, json={"error": "Failed to download file: 404 Not Found"})
            b64 = base64.b64encode(body).decode()
            return httpx.Response(
                200,
                json={"success": True, "fileData": f"data:application/octet-stream;base64,{b64}", "mimeType": "text/plain"},
            )
        return httpx.Response(200, json={})

    monkeypatch.setattr(server, "_client", make_client(handler, client_id="c"))
    return seen


async def test_read_file_text(monkeypatch):
    file_relay(monkeypatch)
    out = await server.foundry_read_file("modules/mymod/module.json")
    assert out == '{"id": "mymod", "version": "1"}'


async def test_read_file_binary_is_not_dumped(monkeypatch):
    file_relay(monkeypatch)
    out = await server.foundry_read_file("modules/mymod/scripts/logo.png")
    assert "binary file" in out


async def test_read_file_truncates(monkeypatch):
    file_relay(monkeypatch, files={"modules/big.txt": b"a" * 5000})
    out = await server.foundry_read_file("modules/big.txt", max_chars=1000)
    assert "cut off at 1000 of 5000" in out


async def test_read_file_missing(monkeypatch):
    file_relay(monkeypatch)
    out = await server.foundry_read_file("modules/nope.txt")
    assert out.startswith("Error:") and "404" in out


async def test_download_folder_copies_and_skips(monkeypatch, tmp_path):
    seen = file_relay(monkeypatch)
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(tmp_path))
    out = await server.foundry_download_folder("modules/mymod")
    root = tmp_path / "mymod"
    assert (root / "module.json").read_bytes() == FILES["modules/mymod/module.json"]
    assert (root / "scripts" / "main.js").exists()
    assert (root / "scripts" / "logo.png").read_bytes() == FILES["modules/mymod/scripts/logo.png"]
    assert not (root / "node_modules").exists()
    assert ("get", "modules/mymod/node_modules/skip.js") not in seen
    assert "Saved 3 files" in out


async def test_download_folder_custom_dest(monkeypatch, tmp_path):
    file_relay(monkeypatch)
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(tmp_path))
    await server.foundry_download_folder("modules/mymod", dest="D&D mods/mymod")
    assert (tmp_path / "D&D mods" / "mymod" / "module.json").exists()


async def test_download_folder_refuses_to_escape(monkeypatch, tmp_path):
    file_relay(monkeypatch)
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(tmp_path / "safe"))
    (tmp_path / "safe").mkdir()
    out = await server.foundry_download_folder("modules/mymod", dest="../outside")
    assert "Refusing" in out
    assert not (tmp_path / "outside").exists()


async def test_download_folder_blocks_dotdot_file_names(monkeypatch, tmp_path):
    tree = {"modules/evil": [{"name": "x", "path": "modules/evil/../../x", "type": "file"}]}
    file_relay(monkeypatch, tree=tree, files={"modules/evil/../../x": b"boom"})
    base = tmp_path / "safe"
    base.mkdir()
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(base))
    out = await server.foundry_download_folder("modules/evil")
    assert "Refusing" in out
    assert list(tmp_path.rglob("x")) == []


async def test_download_folder_needs_a_path(monkeypatch, tmp_path):
    file_relay(monkeypatch)
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(tmp_path))
    assert "give a folder path" in await server.foundry_download_folder("/")


async def test_download_tool_is_off_by_default():
    names = {t.name for t in await server.mcp.list_tools()}
    assert "foundry_download_folder" not in names


async def test_download_folder_decodes_percent_names(monkeypatch, tmp_path):
    tree = {"modules/m": [{"name": "A B.webp", "path": "modules/m/A%20B.webp", "type": "file"}]}
    seen = file_relay(monkeypatch, tree=tree, files={"modules/m/A%20B.webp": b"img"})
    monkeypatch.setenv("FOUNDRY_DOWNLOAD_DIR", str(tmp_path))
    await server.foundry_download_folder("modules/m")
    assert ("get", "modules/m/A%20B.webp") in seen  # asked with the encoded path
    assert (tmp_path / "m" / "A B.webp").read_bytes() == b"img"  # saved with the real name
    assert not (tmp_path / "m" / "A%20B.webp").exists()
