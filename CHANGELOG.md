# Changelog

## 2026.09.29.8
- Add spells, features and gear from a compendium straight onto an actor: `foundry_import_from_pack` now takes `actor_uuid` and `ids` (up to 30 at a time).
- `foundry_create` can make a document inside a parent, like an item on an actor (`parent_uuid`).
- Relay 2026.09.29.10, module 2026.09.29.9, mcp-server 2026.09.29.8. Update all three.

## 2026.09.29.7
- The relay moved to the ha-foundry-vtt-addon repository and is now called Foundry VTT MCP & Rest Relay. The `relay-py` folder and its build are gone from this repository.
- Module 2026.09.29.8 and mcp-server 2026.09.29.7 only change wording.

## 2026.09.29.6
- New abilities: conditions, death saves, saves and checks, spell slots and item uses, last attack, targets, tokens, journals, tables, compendium import, and a Recent changes list on the relay page.
- Relay 2026.09.29.8, module 2026.09.29.7, mcp-server 2026.09.29.6. Update all three.

## 2026.09.29.5
- Short rest can spend hit dice. Relay 2026.09.29.7, module 2026.09.29.6, mcp-server 2026.09.29.5. Update all three.

## 2026.09.29.4
- Removed ThreeHats. The `foundry-relay` add-on folder and its build workflow are gone.
- The MCP server now always uses our own FGA relay. `FOUNDRY_RELAY_KIND` no longer does anything.
- Default relay address is `https://rest-relay.mogie.io`.

## 2026.09.28.10
- Zip code for the install link: `77b29bbf812b6a8035f53969e504774972c0880e`
- New: 8 write tools, off unless `FOUNDRY_ALLOW_WRITES` is set.
- Writes only reach worlds in `FOUNDRY_WRITE_WORLDS` (default `mcp-test`). Checked on every write. Each write is logged.
- `foundry_delete` needs `confirm=true`. No JavaScript tool.
- 44 tests pass.

## 2026.09.28.09
- Zip code for the install link: `e933d874ae67714b6dee84d2c9a4e44b02a4f1f8`
- Fix: `foundry_download_folder` saved files with `%20` in their names. It now saves the real name (spaces).
- 26 tests pass.

## Install link for 2026.09.28.08
- Zip code: `eb6b9bc51499462b7f485b7ac618309af25550e3`
- Use it in the link: `https://github.com/drmogie/foundry-mcp/archive/<code>.zip#subdirectory=mcp-server`

## 2026.09.28.08
- Fix: an old `build/` folder was committed by mistake. Installs from a zip or Git picked up stale code (version .05) and had no new tools.
- Removed `build/`, and ignore `build/` and `dist/` from now on.

## 2026.09.28.07
- New tool: `foundry_read_file` (read a text file from Foundry).
- New opt-in tool: `foundry_download_folder`. Only exists when `FOUNDRY_DOWNLOAD_DIR` is set. Writes only inside that folder.
- 25 tests pass.

## 2026.09.28.06
- Install docs now use a zip link, so Git is not needed on the computer.

## 2026.09.28.05
- Fix: the MCP server failed to start on a fresh install.
- A new MCP library (2.x) renamed a part we use. We now pin `mcp<2`.

## 2026.09.28.04
- New: `mcp-server/`, a read-only Python MCP server with 14 tools.
- The add-on is unchanged.

## 2026.09.28.03
- The image is now built by GitHub Actions and published to ghcr.io.
- Home Assistant pulls the ready image. The Pi no longer compiles the relay.

## 2026.09.28.02
- First release.
- Add-on repository with the Foundry REST API Relay add-on.
- The MCP server is planned for a later release.
