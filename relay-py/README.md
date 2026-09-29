# FGA Relay

Version: 2026.09.29.6

Our own relay between Foundry VTT and tools like Claude.
It is the REST API. The MCP server sits on top of it.

## What this version does
- One login page. No sign-up screen.
- Username and password come from the add-on options.
- Status lights: relay, Foundry client, world.
- Copy boxes for the relay address and the connect key.
- A "Test the link" button that shows the round trip time.
- Make a new connect key at any time.
- API tokens: read only or read and write, limited to one world if you like, with an optional expiry. Each token shows once. The page lists them with last used time and a Revoke button.

## API tokens
Make one on the relay page. Send it in the `x-api-key` header, or as `Authorization: Bearer <token>`.

Every route needs a token. Add `?client_id=...` if more than one Foundry client is connected.

Read routes (any token):
- GET /api/v1/world shows the world, system, version and counts.
- GET /api/v1/documents/{type}?q=bob&limit=20 lists Actor, Item, Scene, JournalEntry, Macro, RollTable, Playlist, Folder or Combat.
- GET /api/v1/document?uuid=Actor.abc gives one document. Add `source=true` for raw data instead of prepared data.
- GET /api/v1/chat?limit=20 gives the latest chat messages.
- GET /api/v1/encounters lists combats and combatants.
- GET /api/v1/effects?uuid=Actor.abc lists active effects on an actor or token.
- GET /api/v1/scene gives the active scene. Use `id`, `name` or `viewed=true` to pick another.
- GET /api/v1/users lists users.
- GET /api/v1/clients lists connected Foundry clients.
- POST /api/v1/ping tests the link to Foundry.
- POST /api/v1/rolls with `"chat": false` rolls dice without posting.

Write routes (write token, allowed worlds only):
- PATCH /api/v1/document with `uuid` and `data` changes a document.
- POST /api/v1/documents/{type} with `data` (and optional `parentUuid`) makes one. Use a parent to add an item to an actor.
- DELETE /api/v1/document?uuid=...&confirm=true deletes one. It refuses without confirm.
- POST /api/v1/chat with `content` (and optional `actorId`, `alias`, `whisper`) posts a message.
- POST /api/v1/rolls with `formula` (and optional `flavor`) rolls and posts to chat.
- POST /api/v1/items/use with `uuid` (and optional `targets`, `activityId`) uses an item.
- POST /api/v1/tokens/move with `uuid`, `x`, `y` moves a token.
- POST /api/v1/scene/switch with `id` or `name`, and optional `activate`.
- POST /api/v1/combat makes a combat on the scene, or reuses the one there. Optional `tokenUuids`, `rollInitiative`, `start`.
- POST /api/v1/combat/control with `action`: start, nextTurn, previousTurn, nextRound, previousRound, rollAll, rollNpc or end. End needs `confirm: true`.
- POST /api/v1/damage with `uuid` (actor or token), `amount`, and optional `mode` (damage, heal or temp), `type` and `multiplier`. Uses the D&D 5e rules for resistance and temporary hit points.
- POST /api/v1/rest with `uuid` (actor or token) and `type` (long or short). Runs the D&D 5e rest, with no dialog.

Read route for the log (any token):
- GET /api/v1/activity?limit=50 lists the latest writes, newest first. Filter with `token` (a token name) or `kind`. It shows who, what, when, and any error. Reads are not logged. The log keeps the last 1000 entries in /data/activity.db.

Answers look like `{"ok": true, "clientId": "...", "data": ...}`.
Errors come back as `{"detail": "plain words"}`. A 400 means Foundry said no. A 502 means Foundry could not be reached.

The relay never touches User or Setting documents.

Example:

    curl -H "x-api-key: fgat_..." https://rest-relay.mogie.io/api/v1/whoami

A read token can read. A write token can read and write. A world limited token only sees its own world.
Tokens are stored as a hash in /data/tokens.db, so nobody can read one back, not even from a backup.

## Install (Home Assistant add-on)
- Add this repository to the add-on store: https://github.com/drmogie/foundry-mcp
- Install "FGA Relay".
- Open the Configuration tab. Set a username and a password. Save.
- Start the add-on.
- Open http://ha-pi4:3011 and log in.

Test on ha-pi4 first. It runs on port 3011, so it can sit next to the old relay on 3010.

## Connect Foundry
- Install the module in `foundry-module/fga-relay-connect` (copy the folder into Foundry `Data/modules`).
- Turn the module on in your world.
- Open Game Settings, Configure Settings, FGA Relay Connect.
- Paste the relay address and the connect key from the relay page.
- Turn on "Connect this browser to the relay".
- The status light on the relay page turns green.

If Foundry is on https, the relay address must start with wss://.
That means the relay must be behind Nginx Proxy Manager with https.
A plain ws:// address is blocked by the browser on an https page.

Use one dedicated GM browser tab. Commands only work while that tab is open.

## Settings
- log_level: debug, info, warning or error.
- write_worlds: world ids where write routes are allowed. Default `mcp-test`. Use a comma between several, or `*` for all. Reads work in every world.
- admin_username and admin_password: the web page login.

The connect key and session secret are made on first start and kept in /data.

## Run without Home Assistant
    pip install -r requirements.txt
    DATA_DIR=./data ADMIN_USERNAME=me ADMIN_PASSWORD=pw python -m app

## Tests
    python -m pytest -q tests

The live tests start a real relay and talk to it over a real socket.

## Security notes
- Wrong passwords lock the address out for five minutes after five tries.
- The login cookie is signed, HTTP only, and secure behind https.
- The connect key is checked on every socket.
- Do not open port 3011 to the internet. Put it behind Nginx Proxy Manager.
