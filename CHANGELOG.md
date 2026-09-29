# Changelog

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
