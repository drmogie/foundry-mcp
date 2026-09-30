# Foundry MCP server

Version: 2026.09.29.13

Lets Claude read a Foundry VTT world.
It talks to the Foundry VTT MCP & Rest Relay add-on.
By default it is read-only. Nothing changes your world.
Write tools exist, but they are off until you turn them on. See "Write tools" below.

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
- foundry_read_file: read one text file, such as a mod's module.json
- foundry_get_conditions: conditions on an actor or token
- foundry_get_resources: spell slots, item charges, consumable counts
- foundry_last_attack: the latest attack in one answer (roll, hit or miss, target, damage)
- foundry_list_packs: compendiums
- foundry_search_pack: find entries in one compendium
- foundry_activity_log: what each API token changed lately

## Settings

Set these as environment variables.

- FOUNDRY_API_KEY (required): a token from the relay page. It starts with `fgat_`.
- FOUNDRY_RELAY_URL: the relay address. Default is `https://rest-relay.mogie.io` (home network only).
- FOUNDRY_CLIENT_ID: which world to use. Leave it empty when only one world is online.

- FOUNDRY_DOWNLOAD_DIR (optional): turns on one extra tool, described below.

Tip: make a scoped key on the relay dashboard with read scopes only.

## The relay

This server only talks to the Foundry VTT MCP & Rest Relay (add-on repository: https://github.com/drmogie/ha-foundry-vtt-addon). ThreeHats is gone.

- Make a token on the relay web page. It starts with `fgat_`.
- Set FOUNDRY_API_KEY to that token.
- Set FOUNDRY_RELAY_URL only if the relay is not at `https://rest-relay.mogie.io`.
- Writes use the same switch and world limit as before.
- The relay also limits writes. Use a write token.

## Write tools (optional, off by default)

Set `FOUNDRY_ALLOW_WRITES` to `true` to turn them on. Twenty-two tools appear:

- foundry_send_chat: post a chat message
- foundry_roll: roll dice
- foundry_create: create an actor, item, scene, journal, and so on
- foundry_update: change fields on one document
- foundry_delete: delete one document. Needs `confirm=true`
- foundry_switch_scene: make a scene active
- foundry_use_item: D&D 5e, make an actor use an item (good for testing mods)
- foundry_attack: D&D 5e, attack in one step. It rolls the attack, waits for the damage roll and takes the hit points off the target. Players and non-players have separate switches:
  - `apply_for_players` (default off) for a player character sheet.
  - `apply_for_npcs` (default on) for an NPC sheet.
  - Set the defaults once with the environment variables `FOUNDRY_MCP_APPLY_PLAYER_HITS` and `FOUNDRY_MCP_APPLY_NPC_HITS` (true or false).
  - It stops and says so on a miss, when no damage was rolled, or when there is no target.
- foundry_move_token: move a token
- foundry_start_combat: make a combat, add tokens, roll initiative, start
- foundry_combat_turn: start, next turn, next round, roll initiative, or end. End needs `confirm=true`
- foundry_rest: long or short rest with D&D 5e rules. A short rest can spend hit dice (`hit_dice`)
- foundry_apply_damage: damage, heal or temporary hit points with D&D 5e rules
- foundry_condition: add, remove or toggle a condition
- foundry_death_save: roll a death save
- foundry_check: roll a saving throw, ability check or skill check, with advantage and a DC
- foundry_spend_resource: spend, restore or set a spell slot, item charges or a quantity
- foundry_target: set or clear the GM's targets
- foundry_add_token: put an actor on a scene
- foundry_set_token: show, hide, rotate or move a token
- foundry_create_journal: make a journal or add pages
- foundry_roll_table: roll on a rollable table
- foundry_import_from_pack: copy a compendium entry into the world, and place it. With actor_uuid it adds spells, features or gear from an Item compendium onto that actor instead (ids takes up to 30)

Safety rules:

- Writes only work on worlds listed in `FOUNDRY_WRITE_WORLDS`. The default is `mcp-test`.
- If the connected world is anything else, nothing is sent. This is checked on every write.
- If two worlds are online and you did not pick one, nothing is sent.
- Every write is logged to the Claude Desktop MCP log, with the world name.
- There is no tool that runs JavaScript in Foundry. That is on purpose.
- Deleting cannot be undone. Back up first.

## Copy a mod folder to your computer (optional)

Set FOUNDRY_DOWNLOAD_DIR to a folder on your computer.
Example: `C:\Users\YOU\Downloads`.
That turns on `foundry_download_folder`.

- It copies a folder from the Foundry server, like `modules/fga-mount-action`.
- It only writes inside FOUNDRY_DOWNLOAD_DIR. It refuses any path that tries to leave it.
- It skips `.git` and `node_modules`.
- It stops at 300 files or 50 MB.
- Leave FOUNDRY_DOWNLOAD_DIR unset and the tool does not exist.

It does not change Foundry. It only copies files out.

## Add it to Claude Code

```
claude mcp add foundry \
  --env FOUNDRY_API_KEY=YOUR_KEY \
  --env FOUNDRY_RELAY_URL=https://rest-relay.mogie.io \
  -- uvx --from "https://github.com/drmogie/foundry-mcp/archive/77b29bbf812b6a8035f53969e504774972c0880e.zip#subdirectory=mcp-server" foundry-mcp
```

## Add it to Claude Desktop

Open the config file and add this under `mcpServers`:

```json
"foundry": {
  "command": "uvx",
  "args": ["--from", "https://github.com/drmogie/foundry-mcp/archive/77b29bbf812b6a8035f53969e504774972c0880e.zip#subdirectory=mcp-server", "foundry-mcp"],
  "env": {
    "FOUNDRY_API_KEY": "YOUR_KEY",
    "FOUNDRY_RELAY_URL": "https://rest-relay.mogie.io"
  }
}
```

This needs `uv` installed on the computer.
It does not need Git. The link downloads a zip file.
The long code in the link pins one exact version. That is on purpose.
A link that always means "latest" gets cached, and you can be stuck on an old copy.
To update, swap in the new code from the changelog, then restart Claude Desktop.

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

- Combat tools: start and end an encounter, next turn.
- A tool to run your mod checks.
- The relay itself runs as a Home Assistant add-on. It lives in the ha-foundry-vtt-addon repository.
