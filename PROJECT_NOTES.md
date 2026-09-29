# Foundry MCP - project notes

## 2026-09-28: first publish (2026.09.28.02)

- Goal: let Claude work with a Foundry VTT test world through the ThreeHats
  Foundry REST API and its relay.
- Phase 1: test world "MCP Test" on vtt.mogie.io (D&D 5e, ThreeHats module).
- Phase 2: `foundry-relay` add-on. Builds the ThreeHats relay 3.4.1 from
  source because the official image is Intel-only (ha-pi4 and ha-blue are ARM).
- Phase 3: the MCP server. Not built yet.
- Files came from another chat; this session padded the version to
  `.02` style (zero-padded), added LICENSE, CHANGELOG, these notes, and
  published the repo.
- The add-on is NOT tested end to end. The first build on ARM is slow.
- Repo is an add-on store, so no hacs.json.

## 2026-09-28: prebuilt image (2026.09.28.03)

- The first build on ha-pi4 ran 25+ minutes and choked the Pi (health checks failing, network flapping).
- Fix: GitHub Actions builds the image for aarch64 and amd64 and pushes it to ghcr.io.
- config.yaml now has `image:`, so Home Assistant pulls instead of building.
- One-time step: after the first workflow run, make the ghcr packages public so HA can pull without a login.
- The Dockerfile stays as the source of truth.

## 2026-09-28: Phase 3 started (2026.09.28.04)

- Relay is running on ha-pi4 and the MCP Test world connected.
- `mcp-server/` is a read-only FastMCP server (14 tools) over the relay REST API.
- 15 tests pass against a pretend relay. Not yet run against the live relay.
- Reply shapes come from the relay source: `/clients` returns `clients[]` with `clientId` and `isOnline`.
- Arrays go in the query as JSON text, for example `details`.
- Write tools are not built yet. Test world only, one at a time.

## 2026-09-28: install fix (2026.09.28.05)

- A fresh `uvx` or `pip` install pulled mcp 2.x, which renamed FastMCP to MCPServer. The server crashed on start (Claude showed 'server disconnected').
- Fix: pin `mcp>=1.2,<2` in pyproject. Tested on mcp 1.27.
- Lesson: test the real install path (`uvx --from git+...`), not only the source tree.

## 2026-09-28: no-Git install (2026.09.28.06)

- Claude Desktop log showed `Git executable not found` on the user's Windows PC.
- `uvx --from https://github.com/drmogie/foundry-mcp/archive/refs/heads/main.zip#subdirectory=mcp-server` works without Git. Tested with a stripped PATH.

## 2026-09-28: file tools (2026.09.28.07)

- `/download` needs `format=base64`. The module fetches the path as a Foundry route (`modules/x/file`) and ignores `source`.
- Reply has `fileData` as a data URL, plus `mimeType`.
- `foundry_download_folder` walks one folder level at a time with `/file-system` (recursive reply shape is unverified), then downloads each file.
- Not yet run against the live relay.

## 2026-09-28: stale build folder (2026.09.28.08)

- Symptom: installs from the repo zip reported 2026.09.28.05 and had 14 tools, even from the newest commit.
- Cause: `mcp-server/build/lib/` (made by a local `pip install` in the source tree) was committed. setuptools reuses `build/lib` files when they look newer than the source, and files from a zip all share one timestamp.
- Fix: `git rm` the folder, ignore `build/` and `dist/`.
- Lesson: install into a copy or a venv, never `pip install` in the source tree, and check `git status` for build output before committing.

## 2026-09-28: first live file copies (2026.09.28.09)

- `foundry_read_file` and `foundry_download_folder` work on the live relay.
- Copied Ammo Tracker, Battle Director, Scene Director, and Character Popup from the server into Downloads/D&D mods.
- `/file-system` lists paths URL-encoded (`A%20B.webp`). Ask with the encoded path, save with the decoded name.
- Running several downloads at once timed out. Run them one at a time.

## 2026-09-28: write tools (2026.09.28.10)

- Eight opt-in write tools. Guard: world allowlist checked against `/clients` on every write (relay's `worldId`), default `mcp-test`.
- POST/PUT/DELETE send `clientId` in the query and fields in a JSON body. Empty fields are dropped.
- Not built on purpose: `/execute-js`, user management, file upload.
- Not yet run against the live relay.

## 2026-09-29: our own relay, Stage 1 (2026.09.29.1)

- Why: ThreeHats setup was rough (confusing login page, module pointed at the public server, slow to link with no status).
- Decision: Python. Same language as the MCP server.
- Built `relay-py/` (FastAPI): one login from add-on options, status lights, connect key, "Test the link" ping, live socket to the module. Port 3011.
- Built `foundry-module/fga-relay-connect/`: settings, auto reconnect, hello, ping.
- Tests: 17 relay tests (including live socket tests) and 11 module tests. Also ran the real module code against a running relay: link, ping in 2 ms, wrong key stops retrying.
- Not done yet: Docker image build (no Docker daemon here; GitHub Actions workflow added), install on ha-pi4, real Foundry test.
- Next: Stage 2 tokens, Stage 3 REST routes, then point the MCP server at it.
- Lesson: test the socket with a real server, not a threaded TestClient (it hangs).

## 2026-09-29: Stage 2 tokens (2026.09.29.2)

- Installed Stage 1 on ha-pi4 and linked the MCP Test world. NPM host `rest-relay.mogie.io` -> homeassistant:3011, LAN only (allow 172.16.1.x, 30.x; 403 for the Cloudflare Tunnel header). `relay.mogie.io` stays on ThreeHats (3010).
- Tokens: SQLite in /data/tokens.db, hashed, scope read or write, optional world and expiry, last used. Header `x-api-key` or Bearer.
- Routes: /api/tokens (web login) and /api/v1/whoami, /clients, /ping (token).
- 36 relay tests pass. A real browser test (Chromium) found a duplicate element id that broke the world dropdown. Fixed.
- Lesson: click through the real page, not only the API tests.
- Next: Stage 3 REST routes (actors, items, scenes, chat, rolls) and matching module commands.

## 2026-09-29: Stage 3 REST routes (relay 2026.09.29.3, module 2026.09.29.2)

- Module `commands.mjs`: world, list, get, chat, encounters, effects, scene, users, roll, sendChat, update, create, delete, useItem, moveToken, switchScene. Foundry objects come in through a context, so tests use a pretend Foundry (33 module tests).
- Relay `v1.py`: REST routes over those commands. Read token reads, write token writes. Quiet rolls are reads.
- Write guard: `write_worlds` add-on option, default `mcp-test`. Delete needs `confirm=true`.
- Foundry errors -> 400, no client or lost link -> 502.
- 49 relay tests (a pretend Foundry client on a real socket).
- Not yet run against real Foundry. Needs the new module copied into Foundry, then try the routes from the PC.
- Next: point mcp-server at our relay, compare with ThreeHats, then Stage 4 (combat control, apply damage, activity log).

## 2026-09-29: MCP client for our relay (mcp-server 2026.09.29.1, relay .4, module .3)

- New `foundry_mcp/fga.py`: FgaClient turns the old ThreeHats-style calls into our /api/v1 routes. Tool names do not change.
- Picked by token: a key starting `fgat_` uses FgaClient. `FOUNDRY_RELAY_KIND` forces it.
- Default address `https://rest-relay.mogie.io` (LAN only).
- Update with items or effects becomes creates on the parent, then one patch for the rest.
- Use item and move token can find things by name.
- Relay .4 adds file routes. Module .3 adds file commands.
- 73 mcp-server tests, 52 relay tests, 40 module tests.
- Switch: set FOUNDRY_API_KEY to an fgat_ token. ThreeHats stays as backup.
- Next: try it live on ha-pi4, then Stage 4.

## 2026-09-29: Stage 4 (relay .5, module .4, mcp-server 2026.09.29.2)

- New relay routes: POST /api/v1/combat, POST /api/v1/combat/control, POST /api/v1/damage, GET /api/v1/activity.
- New module commands: combatCreate, combatControl, applyDamage. Damage uses the dnd5e actor.applyDamage when it exists, else plain hit point math.
- Activity log lives in relay-py/app/activity.py (SQLite, last 1000 writes, blocked writes included).
- New MCP tools: foundry_start_combat, foundry_combat_turn, foundry_apply_damage, foundry_activity_log. They only work on our relay.
- Tests: 57 relay, 47 module, 81 mcp-server.
- Not yet run against real Foundry. Try in MCP Test: make a combat, next turn, apply damage to Bob, read the log.
- Next: live test, then maybe show the activity log on the relay web page.
- Live check on ha-pi4 (relay .5, module .4, MCP Test): combat made with Bob and Foreman, initiative rolled, next turn worked, 5 fire damage then 5 healing on Bob (87 to 82 to 87), combat ended, activity log showed all five writes under the ClaudeDesktop token.
