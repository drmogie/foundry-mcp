"""Foundry MCP server. Tools for a Foundry VTT world via our own FGA relay."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .client import RelayClient, RelayError, to_text
from .fga import FgaClient

INSTRUCTIONS = (
    "Access to a Foundry VTT world through a self-hosted relay. Read-only unless writes were turned on. "
    "Start with foundry_world_info or foundry_search. "
    "Foundry ids are UUIDs like Actor.abc123 or Scene.xyz789. "
    "Write tools, when present, only work on the allowed test world."
)

mcp = FastMCP("foundry-mcp", instructions=INSTRUCTIONS)

_client: RelayClient | None = None


def make_client() -> RelayClient:
    """Always our own FGA relay."""
    return FgaClient()


def client() -> RelayClient:
    global _client
    if _client is None:
        _client = make_client()
    return _client


async def _run(endpoint: str, **params) -> str:
    try:
        return to_text(await client().get(endpoint, **params))
    except RelayError as exc:
        return f"Error: {exc}"


@mcp.tool()
async def foundry_list_worlds() -> str:
    """List the Foundry worlds connected to the relay, with their client ids."""
    try:
        return to_text(await client().list_clients())
    except RelayError as exc:
        return f"Error: {exc}"


@mcp.tool()
async def foundry_world_info() -> str:
    """World name, Foundry version, game system, and active modules."""
    return await _run("/world-info")


@mcp.tool()
async def foundry_structure(
    path: Annotated[str, Field(description="Folder path to read. Empty means the root.")] = "",
    types: Annotated[
        str,
        Field(description="Comma list of: Scene, Actor, Item, JournalEntry, RollTable, Cards, Macro, Playlist."),
    ] = "",
    recursive: bool = True,
    include_entity_data: Annotated[bool, Field(description="Full data. Big. Leave off unless needed.")] = False,
) -> str:
    """Folders and documents in the world, by name and uuid."""
    return await _run(
        "/structure",
        path=path,
        types=types,
        recursive=recursive,
        includeEntityData=include_entity_data,
    )


@mcp.tool()
async def foundry_search(
    query: Annotated[str, Field(description="Text to look for. Empty lists everything the filter matches.")] = "",
    filter: Annotated[
        str,
        Field(description='Simple: "Actor". Or compound: "documentType:Item,subType:weapon".'),
    ] = "",
    limit: Annotated[int, Field(ge=1, le=500)] = 50,
    minified: Annotated[bool, Field(description="Only uuid, name, type, image.")] = True,
    exclude_compendiums: bool = False,
) -> str:
    """Search actors, items, scenes, journals and compendiums."""
    return await _run(
        "/search",
        query=query,
        filter=filter,
        limit=limit,
        minified=minified,
        excludeCompendiums=exclude_compendiums,
    )


@mcp.tool()
async def foundry_get(uuid: Annotated[str, Field(description="For example Actor.abc123")]) -> str:
    """Full data for one document by uuid."""
    return await _run("/get", uuid=uuid)


@mcp.tool()
async def foundry_actor_details(
    actor_uuid: str,
    details: Annotated[
        list[str],
        Field(description='Any of: "resources", "items", "spells", "features". D&D 5e only.'),
    ] = ["resources", "items", "spells", "features"],  # noqa: B006
) -> str:
    """D&D 5e detail for one actor: resources, items, spells, features."""
    return await _run("/dnd5e/get-actor-details", actorUuid=actor_uuid, details=list(details))


@mcp.tool()
async def foundry_get_scene(
    scene_id: str = "",
    name: str = "",
    active: bool = False,
    viewed: bool = False,
    all: bool = False,
) -> str:
    """Get a scene by id or name, the active or viewed scene, or all scenes."""
    picked = [bool(scene_id), bool(name), active, viewed, all]
    if sum(picked) != 1:
        return "Error: give exactly one of scene_id, name, active, viewed, or all."
    return await _run(
        "/scene",
        sceneId=scene_id,
        name=name,
        active=active or None,
        viewed=viewed or None,
        all=all or None,
    )


@mcp.tool()
async def foundry_list_users() -> str:
    """Foundry users (GM and players) in the world."""
    return await _run("/users")


@mcp.tool()
async def foundry_get_chat(
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    offset: Annotated[int, Field(ge=0)] = 0,
    chat_type: Annotated[int | None, Field(description="0 OOC, 1 IC, 2 emote, 3 whisper, 4 roll.")] = None,
    speaker: Annotated[str, Field(description="Speaker name or actor id.")] = "",
) -> str:
    """Recent chat messages. Use this to check what a mod posted."""
    return await _run("/chat", limit=limit, offset=offset, chatType=chat_type, speaker=speaker)


@mcp.tool()
async def foundry_get_rolls(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> str:
    """Recent dice rolls."""
    return await _run("/rolls", limit=limit)


@mcp.tool()
async def foundry_get_encounters() -> str:
    """Active combat encounters."""
    return await _run("/encounters")


@mcp.tool()
async def foundry_list_macros() -> str:
    """All macros in the world."""
    return await _run("/macros")


@mcp.tool()
async def foundry_get_effects(uuid: Annotated[str, Field(description="Actor or token uuid.")]) -> str:
    """Active effects on an actor or token."""
    return await _run("/effects", uuid=uuid)


@mcp.tool()
async def foundry_list_files(
    path: str = "",
    source: Annotated[str, Field(description="data, systems, modules, and so on.")] = "data",
    recursive: bool = False,
) -> str:
    """List files in Foundry's file system. Use it to check a mod's files are installed."""
    return await _run("/file-system", path=path, source=source, recursive=recursive)


@mcp.tool()
async def foundry_read_file(
    path: Annotated[str, Field(description="For example modules/fga-mount-action/module.json")],
    max_chars: Annotated[int, Field(ge=100, le=200_000)] = 20_000,
) -> str:
    """Read one text file from Foundry (a mod's module.json, a script, a style sheet)."""
    try:
        raw, mime = await client().download(path)
    except RelayError as exc:
        return f"Error: {exc}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"This looks like a binary file ({mime}, {len(raw)} bytes). It cannot be shown as text."
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... cut off at {max_chars} of {len(text)} characters."
    return text


SKIP_DIRS = {".git", "node_modules", "__pycache__"}
MAX_FILES = 300
MAX_BYTES = 50 * 1024 * 1024


def _safe_join(base: Path, *parts: str) -> Path:
    """Join parts under base. Refuse anything that would land outside base."""
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise RelayError(f"Refusing to write outside the download folder: {'/'.join(parts)}")
    return target


async def foundry_download_folder(
    path: Annotated[str, Field(description="Folder on the Foundry server, for example modules/fga-mount-action")],
    dest: Annotated[str, Field(description="Sub-folder name inside the download folder. Default: the folder's own name.")] = "",
) -> str:
    """Copy a folder from the Foundry server to this computer, into the download folder only."""
    base = Path(os.environ["FOUNDRY_DOWNLOAD_DIR"]).expanduser().resolve()
    root = path.strip("/")
    if not root:
        return "Error: give a folder path, for example modules/fga-mount-action."
    try:
        target_root = _safe_join(base, dest or root.rsplit("/", 1)[-1])
        saved: list[str] = []
        total = 0
        stack = [root]
        while stack:
            folder = stack.pop()
            for item in await client().list_dir(folder):
                name = str(item.get("name", ""))
                item_path = str(item.get("path") or f"{folder}/{name}").strip("/")
                if not name:
                    continue
                if item.get("type") == "directory":
                    if name not in SKIP_DIRS:
                        stack.append(item_path)
                    continue
                if len(saved) >= MAX_FILES:
                    return _download_report(target_root, saved, total, f"Stopped at {MAX_FILES} files.")
                raw, _mime = await client().download(item_path)
                total += len(raw)
                if total > MAX_BYTES:
                    return _download_report(target_root, saved, total, "Stopped: over the 50 MB limit.")
                # Foundry lists paths URL-encoded (a%20b). Ask with the encoded path, save with the real name.
                rel = unquote(item_path[len(root):]).lstrip("/")
                out = _safe_join(target_root, *rel.split("/"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
                saved.append(rel)
    except RelayError as exc:
        return f"Error: {exc}"
    return _download_report(target_root, saved, total, "")


def _download_report(target: Path, saved: list[str], total: int, note: str) -> str:
    lines = [f"Saved {len(saved)} files ({total} bytes) to {target}"]
    if note:
        lines.append(note)
    lines.extend(saved[:40])
    if len(saved) > 40:
        lines.append(f"... and {len(saved) - 40} more")
    return "\n".join(lines)


def register_download_tool(target: FastMCP | None = None) -> None:
    """Opt-in. Only offered when FOUNDRY_DOWNLOAD_DIR is set, and it can only write inside it."""
    (target or mcp).tool()(foundry_download_folder)


if os.environ.get("FOUNDRY_DOWNLOAD_DIR"):
    register_download_tool()


# ---- write tools (opt-in) ---------------------------------------------------
# Off unless FOUNDRY_ALLOW_WRITES is set. Even then, they only touch worlds listed in
# FOUNDRY_WRITE_WORLDS (default: mcp-test). Every write is logged to stderr.


async def _write(method: str, endpoint: str, *, params: dict | None = None, body: dict | None = None) -> str:
    try:
        return to_text(await client().write(method, endpoint, params=params, body=body))
    except RelayError as exc:
        return f"Error: {exc}"


async def foundry_send_chat(
    content: Annotated[str, Field(description="Message text. HTML is allowed.")],
    flavor: str = "",
    alias: Annotated[str, Field(description="Speaker name to show.")] = "",
    speaker: Annotated[str, Field(description="Actor id to speak as.")] = "",
    whisper: Annotated[list[str] | None, Field(description="User ids to whisper to.")] = None,
) -> str:
    """Post a chat message in the world."""
    return await _write(
        "POST", "/chat", body={"content": content, "flavor": flavor, "alias": alias, "speaker": speaker, "whisper": whisper}
    )


async def foundry_roll(
    formula: Annotated[str, Field(description='For example "1d20 + 5".')],
    flavor: str = "",
    create_chat_message: bool = True,
    whisper: Annotated[list[str] | None, Field(description="User ids to whisper the result to.")] = None,
) -> str:
    """Roll dice in the world."""
    return await _write(
        "POST",
        "/roll",
        body={"formula": formula, "flavor": flavor, "createChatMessage": create_chat_message, "whisper": whisper},
    )


async def foundry_create(
    entity_type: Annotated[str, Field(description="Scene, Actor, Item, JournalEntry, RollTable, Cards, Macro or Playlist.")],
    data: Annotated[dict, Field(description="The new document's fields, for example name and type.")],
    folder: Annotated[str, Field(description="Optional folder uuid.")] = "",
) -> str:
    """Create a new document (actor, item, scene, journal, ...)."""
    return await _write("POST", "/create", body={"entityType": entity_type, "data": data, "folder": folder})


async def foundry_update(
    uuid: Annotated[str, Field(description="For example Actor.abc123")],
    data: Annotated[dict, Field(description='Fields to change, for example {"name": "New name"}.')],
) -> str:
    """Change fields on one existing document."""
    return await _write("PUT", "/update", params={"uuid": uuid}, body={"data": data})


async def foundry_delete(
    uuid: Annotated[str, Field(description="For example Actor.abc123")],
    confirm: Annotated[bool, Field(description="Must be true. Deleting cannot be undone.")] = False,
) -> str:
    """Delete one document. Needs confirm=true."""
    if not confirm:
        return f"Nothing deleted. Deleting {uuid} cannot be undone. Call again with confirm=true if you are sure."
    return await _write("DELETE", "/delete", params={"uuid": uuid})


async def foundry_switch_scene(
    scene_id: str = "",
    name: str = "",
) -> str:
    """Make a scene the active scene. Give a scene id or a name."""
    if bool(scene_id) == bool(name):
        return "Error: give exactly one of scene_id or name."
    return await _write("POST", "/switch-scene", body={"sceneId": scene_id, "name": name})


async def foundry_use_item(
    actor_uuid: str,
    ability_name: Annotated[str, Field(description="Item name, if you have no uuid.")] = "",
    ability_uuid: str = "",
    target_uuid: str = "",
    target_name: str = "",
) -> str:
    """D&D 5e: make an actor use an item, like firing a bow. Good for testing mods."""
    if bool(ability_name) == bool(ability_uuid):
        return "Error: give exactly one of ability_name or ability_uuid."
    return await _write(
        "POST",
        "/dnd5e/use-item",
        body={
            "actorUuid": actor_uuid,
            "abilityName": ability_name,
            "abilityUuid": ability_uuid,
            "targetUuid": target_uuid,
            "targetName": target_name,
        },
    )


async def foundry_move_token(
    x: float,
    y: float,
    uuid: str = "",
    name: str = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene.")] = "",
    animate: bool = True,
) -> str:
    """Move a token to x and y on a scene. Give a token uuid or name."""
    if bool(uuid) == bool(name):
        return "Error: give exactly one of uuid or name."
    return await _write(
        "POST", "/move-token", body={"x": x, "y": y, "uuid": uuid, "name": name, "sceneId": scene_id, "animate": animate}
    )


def _needs_fga() -> str | None:
    if isinstance(client(), FgaClient):
        return None
    return "Error: this needs our own FGA relay. Use an fgat_ token. Nothing was changed."


async def foundry_start_combat(
    token_names: Annotated[list[str] | None, Field(description="Names of tokens on the scene to add.")] = None,
    token_uuids: Annotated[list[str] | None, Field(description="Token uuids to add.")] = None,
    all_tokens: Annotated[bool, Field(description="Add every token on the scene.")] = False,
    roll_initiative: bool = True,
    start: bool = True,
    scene_id: Annotated[str, Field(description="Defaults to the scene that is showing.")] = "",
) -> str:
    """Make a combat on the scene (or reuse the one there), add tokens, roll initiative and start it. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _write(
        "POST",
        "/combat/create",
        body={"tokenNames": token_names, "tokenUuids": token_uuids, "allTokens": all_tokens or None,
              "rollInitiative": roll_initiative, "start": start, "sceneId": scene_id},
    )


async def foundry_combat_turn(
    action: Annotated[
        str,
        Field(description="One of: start, nextTurn, previousTurn, nextRound, previousRound, rollAll, rollNpc, end."),
    ],
    combat_id: Annotated[str, Field(description="Defaults to the active combat.")] = "",
    confirm: Annotated[bool, Field(description="Must be true for end. Ending removes the combat.")] = False,
) -> str:
    """Run the combat: start it, move the turn or round, roll initiative, or end it. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if action == "end" and not confirm:
        return "Error: Ending combat removes it. Nothing ended. Call again with confirm=true to end it."
    return await _write("POST", "/combat/control", body={"action": action, "combatId": combat_id, "confirm": confirm or None})


async def foundry_apply_damage(
    amount: float,
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    mode: Annotated[str, Field(description="damage, heal or temp (temporary hit points).")] = "damage",
    damage_type: Annotated[str, Field(description='For example "fire". Resistances then apply.')] = "",
    multiplier: Annotated[float | None, Field(description="0.5 for half damage, 2 for double.")] = None,
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Change hit points the way D&D 5e does, with temporary hit points and resistances. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if bool(uuid) == bool(name):
        return "Error: give exactly one of uuid or name."
    return await _write(
        "POST",
        "/damage",
        body={"uuid": uuid, "name": name, "amount": amount, "mode": mode, "damageType": damage_type,
              "multiplier": multiplier, "sceneId": scene_id},
    )


async def foundry_rest(
    rest_type: Annotated[str, Field(description="long or short.")] = "long",
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
    hit_dice: Annotated[int, Field(ge=0, le=20, description="Short rest only: how many hit dice to spend. Stops at full hit points.")] = 0,
) -> str:
    """D&D 5e: make an actor take a long or short rest, with the system's own rules. A short rest can spend hit dice. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if bool(uuid) == bool(name):
        return "Error: give exactly one of uuid or name."
    return await _write("POST", "/rest", body={"uuid": uuid, "name": name, "type": rest_type, "sceneId": scene_id, "hitDice": hit_dice})


@mcp.tool()
async def foundry_get_conditions(
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Conditions on an actor or token, like prone or poisoned. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/conditions", uuid=uuid, name=name, sceneId=scene_id)


@mcp.tool()
async def foundry_get_resources(
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Spell slots, items with limited uses, and consumable counts (like arrows). Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/resources", uuid=uuid, name=name, sceneId=scene_id)


@mcp.tool()
async def foundry_last_attack(
    alias: Annotated[str, Field(description="Only attacks by this speaker, like Bob.")] = "",
    limit: Annotated[int, Field(ge=10, le=200, description="How many recent chat messages to look through.")] = 60,
) -> str:
    """The latest attack in chat in one answer: attacker, weapon, roll, hit or miss, target, armor class and the damage roll.
    If pending is true, the attack hit but the damage has not been rolled yet, so ask again in a few seconds. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/last-attack", alias=alias, limit=limit)


@mcp.tool()
async def foundry_list_packs(
    type: Annotated[str, Field(description="Actor, Item, JournalEntry, RollTable, Scene and so on. Empty for all.")] = "",
    q: Annotated[str, Field(description="Part of the compendium name.")] = "",
) -> str:
    """Compendiums (packs) in the world. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/packs", type=type, q=q)


@mcp.tool()
async def foundry_search_pack(
    pack: Annotated[str, Field(description='Compendium id from foundry_list_packs, like "dnd5e.monsters".')],
    q: Annotated[str, Field(description="Part of the name.")] = "",
    limit: Annotated[int, Field(ge=1, le=200)] = 25,
) -> str:
    """Find entries in one compendium. Each result has an id for foundry_import_from_pack. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/pack-index", pack=pack, q=q, limit=limit)


@mcp.tool()
async def foundry_activity_log(
    limit: Annotated[int, Field(ge=1, le=500)] = 20,
    token: Annotated[str, Field(description="Only this API token's name.")] = "",
    kind: Annotated[str, Field(description='Only this kind, like "sendChat" or "applyDamage".')] = "",
) -> str:
    """What each API token changed lately, newest first. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _run("/activity", limit=limit, token=token, kind=kind)


_WHO = "Give exactly one of uuid or name."


def _one_of(uuid: str, name: str) -> str | None:
    return None if bool(uuid) != bool(name) else f"Error: {_WHO}"


async def foundry_condition(
    condition: Annotated[str, Field(description='A condition id or name, like "prone" or "Poisoned".')],
    state: Annotated[str, Field(description="add, remove or toggle.")] = "add",
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Add, remove or toggle a condition on an actor or token. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if (bad := _one_of(uuid, name)) is not None:
        return bad
    return await _write("POST", "/conditions", body={"uuid": uuid, "name": name, "sceneId": scene_id, "condition": condition, "state": state})


async def foundry_death_save(
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Roll a death saving throw with D&D 5e rules. Posts to chat and updates the successes and failures. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if (bad := _one_of(uuid, name)) is not None:
        return bad
    return await _write("POST", "/death-save", body={"uuid": uuid, "name": name, "sceneId": scene_id})


async def foundry_check(
    key: Annotated[str, Field(description='Ability like "dex" or "Dexterity", or skill like "ath" or "Athletics".')],
    kind: Annotated[str, Field(description="save, ability or skill.")] = "ability",
    uuid: Annotated[str, Field(description="Actor or token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
    dc: Annotated[float | None, Field(description="Difficulty. The answer then says success or not.")] = None,
    advantage: bool = False,
    disadvantage: bool = False,
) -> str:
    """Roll a saving throw, ability check or skill check with the actor's real bonuses. Posts to chat. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if (bad := _one_of(uuid, name)) is not None:
        return bad
    return await _write("POST", "/check", body={
        "uuid": uuid, "name": name, "sceneId": scene_id, "kind": kind, "key": key, "dc": dc,
        "advantage": advantage or None, "disadvantage": disadvantage or None})


async def foundry_spend_resource(
    target: Annotated[str, Field(description="slot (spell slot), uses (item charges) or quantity (like arrows).")] = "slot",
    level: Annotated[str, Field(description='For slots: 1 to 9, or "pact".')] = "",
    item_uuid: Annotated[str, Field(description="For uses and quantity: the item uuid.")] = "",
    mode: Annotated[str, Field(description="spend, restore or set.")] = "spend",
    amount: Annotated[int, Field(ge=0, le=1000)] = 1,
    uuid: Annotated[str, Field(description="For slots: actor or token uuid.")] = "",
    name: Annotated[str, Field(description="For slots: token name on the scene.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
) -> str:
    """Spend, restore or set a spell slot, an item's charges, or an item's quantity. Refuses to go below zero. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if target == "slot" and (bad := _one_of(uuid, name)) is not None:
        return bad
    return await _write("POST", "/resources", body={
        "uuid": uuid, "name": name, "sceneId": scene_id, "target": target, "level": level or None,
        "itemUuid": item_uuid, "mode": mode, "amount": amount})


async def foundry_target(
    names: Annotated[list[str] | None, Field(description="Token names on the scene to target.")] = None,
    uuids: Annotated[list[str] | None, Field(description="Token uuids to target.")] = None,
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with names.")] = "",
) -> str:
    """Set the GM's targets on the canvas. Give nothing to clear all targets. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _write("POST", "/target", body={"names": names, "uuids": uuids, "sceneId": scene_id})


async def foundry_add_token(
    actor_uuid: Annotated[str, Field(description="Actor uuid to make a token from.")],
    scene_id: Annotated[str, Field(description="Defaults to the scene that is showing.")] = "",
    x: Annotated[float | None, Field(description="Position in pixels.")] = None,
    y: Annotated[float | None, Field(description="Position in pixels.")] = None,
    hidden: bool = False,
    token_name: Annotated[str, Field(description="Give the token a different name.")] = "",
) -> str:
    """Put an actor on a scene as a token. Needs the FGA relay. To remove a token, use foundry_delete."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _write("POST", "/tokens/create", body={
        "actorUuid": actor_uuid, "sceneId": scene_id, "x": x, "y": y, "hidden": hidden or None, "tokenName": token_name})


async def foundry_set_token(
    uuid: Annotated[str, Field(description="Token uuid.")] = "",
    name: Annotated[str, Field(description="Token name on the scene, if you have no uuid.")] = "",
    scene_id: Annotated[str, Field(description="Defaults to the active scene. Used with name.")] = "",
    hidden: Annotated[bool | None, Field(description="true hides it from players. false shows it.")] = None,
    rotation: float | None = None,
    elevation: float | None = None,
    x: float | None = None,
    y: float | None = None,
) -> str:
    """Show or hide a token, or change its rotation, elevation or position. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if (bad := _one_of(uuid, name)) is not None:
        return bad
    return await _write("PATCH", "/tokens/set", body={
        "uuid": uuid, "name": name, "sceneId": scene_id, "hidden": hidden, "rotation": rotation,
        "elevation": elevation, "x": x, "y": y})


async def foundry_create_journal(
    name: Annotated[str, Field(description="Journal name. With uuid, the name of the new page.")] = "",
    content: Annotated[str, Field(description="Page text. HTML is allowed.")] = "",
    pages: Annotated[list[dict] | None, Field(description='Several pages: [{"name": "...", "text": "..."}].')] = None,
    folder: Annotated[str, Field(description="Folder id.")] = "",
    uuid: Annotated[str, Field(description="Add pages to this existing journal instead of making a new one.")] = "",
) -> str:
    """Make a journal entry with text pages, or add pages to one. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _write("POST", "/journals", body={"uuid": uuid, "name": name, "content": content, "pages": pages, "folder": folder})


async def foundry_roll_table(
    name: Annotated[str, Field(description="Table name.")] = "",
    uuid: Annotated[str, Field(description="Table uuid, if you have it.")] = "",
    post_to_chat: bool = True,
) -> str:
    """Roll on a rollable table. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    if not (uuid or name):
        return "Error: give the table name or uuid."
    return await _write("POST", "/tables/roll", body={"uuid": uuid, "name": name, "chat": post_to_chat})


async def foundry_import_from_pack(
    pack: Annotated[str, Field(description='Compendium id, like "dnd5e.monsters".')],
    id: Annotated[str, Field(description="Entry id from foundry_search_pack.")],
    name: Annotated[str, Field(description="Rename the copy.")] = "",
    folder: Annotated[str, Field(description="Folder id for the copy.")] = "",
    place: Annotated[bool, Field(description="Actors only: also put a token on the scene.")] = False,
    scene_id: Annotated[str, Field(description="Defaults to the scene that is showing.")] = "",
    x: float | None = None,
    y: float | None = None,
    hidden: bool = False,
) -> str:
    """Copy a compendium entry into the world, like a monster. Can place its token. Needs the FGA relay."""
    if (problem := _needs_fga()) is not None:
        return problem
    return await _write("POST", "/compendium/import", body={
        "pack": pack, "id": id, "name": name, "folder": folder, "place": place or None,
        "sceneId": scene_id, "x": x, "y": y, "hidden": hidden or None})


WRITE_TOOLS = (
    foundry_send_chat,
    foundry_roll,
    foundry_create,
    foundry_update,
    foundry_delete,
    foundry_switch_scene,
    foundry_use_item,
    foundry_move_token,
    foundry_start_combat,
    foundry_combat_turn,
    foundry_apply_damage,
    foundry_rest,
    foundry_condition,
    foundry_death_save,
    foundry_check,
    foundry_spend_resource,
    foundry_target,
    foundry_add_token,
    foundry_set_token,
    foundry_create_journal,
    foundry_roll_table,
    foundry_import_from_pack,
)


def writes_enabled() -> bool:
    return os.environ.get("FOUNDRY_ALLOW_WRITES", "").strip().lower() in {"1", "true", "yes", "on"}


def register_write_tools(target: FastMCP | None = None) -> None:
    """Opt-in. Only offered when FOUNDRY_ALLOW_WRITES is set."""
    for tool in WRITE_TOOLS:
        (target or mcp).tool()(tool)


if writes_enabled():
    register_write_tools()


def main() -> None:
    import sys

    if "--version" in sys.argv:
        print(__version__)
        return
    mcp.run()


if __name__ == "__main__":
    main()
