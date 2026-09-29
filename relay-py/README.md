# FGA Relay

Version: 2026.09.29.2

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

REST routes for actors, items, rolls and the rest come next.

## API tokens
Make one on the relay page. Send it in the `x-api-key` header, or as `Authorization: Bearer <token>`.

Routes today:
- GET /api/v1/whoami shows which token you are using.
- GET /api/v1/clients lists connected Foundry clients (only the token's world if it is limited).
- POST /api/v1/ping tests the link to Foundry.

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
