# Foundry MCP server

Version: 2026.09.28.04

Lets Claude read a Foundry VTT world.
It talks to the ThreeHats relay add-on.
This first version is read-only. Nothing here changes your world.

## Tools

- foundry_list_worlds: worlds connected to the relay
- foundry_world_info: world, Foundry version, system, modules
- foundry_structure: folders and documents
- foundry_search: find actors, items, scenes, journals
- foundry_get: one document by uuid
- foundry_actor_details: D&D 5e items, spells, features, resources
- foundry_get_scene: one scene, the active scene, or all
- foundry_list_users: GM and players
- foundry_get_chat: recent chat messages
- foundry_get_rolls: recent dice rolls
- foundry_get_encounters: active combats
- foundry_list_macros: macros
- foundry_get_effects: active effects on an actor or token
- foundry_list_files: files in Foundry's data folders

## Settings

Set these as environment variables.

- FOUNDRY_API_KEY (required): the key from the relay dashboard.
- FOUNDRY_RELAY_URL: the relay address. Default is `http://ha-pi4:3010`.
- FOUNDRY_CLIENT_ID: which world to use. Leave it empty when only one world is online.

Tip: make a scoped key on the relay dashboard with read scopes only.

## Add it to Claude Code

```
claude mcp add foundry \
  --env FOUNDRY_API_KEY=YOUR_KEY \
  --env FOUNDRY_RELAY_URL=http://ha-pi4:3010 \
  -- uvx --from "git+https://github.com/drmogie/foundry-mcp#subdirectory=mcp-server" foundry-mcp
```

## Add it to Claude Desktop

Open the config file and add this under `mcpServers`:

```json
"foundry": {
  "command": "uvx",
  "args": ["--from", "git+https://github.com/drmogie/foundry-mcp#subdirectory=mcp-server", "foundry-mcp"],
  "env": {
    "FOUNDRY_API_KEY": "YOUR_KEY",
    "FOUNDRY_RELAY_URL": "http://ha-pi4:3010"
  }
}
```

This needs `uv` installed on the computer.

## Run the tests

```
cd mcp-server
pip install -e ".[dev]"
pytest
```

The tests use a pretend relay. They do not need Foundry.

## What is not tested yet

- It has not run against your live relay yet.
- The relay's reply shapes came from its source code, not from a live call.
- First live check: ask Claude to run foundry_list_worlds, then foundry_world_info.

## Next

- Write tools, one at a time, for the test world only.
- A tool to run your mod checks.
- Run it as a Home Assistant add-on.
