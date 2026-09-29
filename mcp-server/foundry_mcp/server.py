"""Foundry MCP server. Read-only tools for a Foundry VTT world via the ThreeHats relay."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .client import RelayClient, RelayError, to_text

INSTRUCTIONS = (
    "Read-only access to a Foundry VTT world through a self-hosted relay. "
    "Start with foundry_world_info or foundry_search. "
    "Foundry ids are UUIDs like Actor.abc123 or Scene.xyz789. "
    "Nothing here changes the world."
)

mcp = FastMCP("foundry-mcp", instructions=INSTRUCTIONS)

_client: RelayClient | None = None


def client() -> RelayClient:
    global _client
    if _client is None:
        _client = RelayClient()
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


def main() -> None:
    import sys

    if "--version" in sys.argv:
        print(__version__)
        return
    mcp.run()


if __name__ == "__main__":
    main()
