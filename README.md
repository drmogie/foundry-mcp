# Foundry MCP

Lets Claude work with a Foundry VTT test world.

Version: 2026.09.28.04

## What is in here

- `foundry-relay/` is a Home Assistant add-on. It runs the ThreeHats Foundry REST API Relay.
- `mcp-server/` is the Python MCP server. Read-only for now. See its README.

## Why build from source

The official relay Docker image only runs on Intel chips.
ha-pi4 and ha-blue are ARM.
This add-on builds the relay from source, so it works on both.
GitHub Actions does the building, not your Pi.
It publishes the ready image to ghcr.io.
Home Assistant just downloads it.

After the first build, open the package pages on GitHub and set them to Public.
There is one for `aarch64-addon-foundry-relay` and one for `amd64-addon-foundry-relay`.

## Phase 1. Test world (on vtt.mogie.io)

1. Back up your worlds first.
2. Make a new world. Call it "MCP Test". Use D&D 5e.
3. Install the ThreeHats module. Use this manifest URL:
   `https://github.com/ThreeHats/foundryvtt-rest-api/releases/latest/download/module.json`
4. Copy the mods from your "D&D mods" folder into the Foundry data folder if you want them in the test.
5. Launch the world. Enable the ThreeHats module.

## Phase 2. Relay add-on (on ha-pi4)

1. In Home Assistant, open Settings, then Add-ons, then Add-on Store.
2. Open the three dots menu. Pick Repositories.
3. Add this repository. Then reload the store.
4. Install "Foundry REST API Relay".
5. Start it. Turn on "Start on boot".
6. Open `http://ha-pi4:3010` in a browser.
7. Make an account. Copy the API key from the dashboard.
8. After you have your account, you can turn on "disable_registration".

## Make it secure for the browser

Foundry runs on https. Browsers block plain ws links from https pages.
So the relay needs its own https name.

1. In Nginx Proxy Manager, add a proxy host. Example name: `relay.mogie.io`.
2. Point it to ha-pi4 on port 3010.
3. Turn on Websockets Support.
4. Turn on SSL.
5. Do not open it to the internet. Keep it on your home network.

## Connect Foundry to the relay

1. In the MCP Test world, open Module Settings.
2. Open the ThreeHats module Connection menu.
3. Set the relay URL to `wss://relay.mogie.io/`.
4. Add your API key. Follow the pairing steps on screen.

## Test it

Run this from any computer on your network:

```
curl -H "x-api-key: YOUR_KEY" http://ha-pi4:3010/clients
```

You should see your test world in the list.

## Add-on options

- log_level: debug, info, warn, or error.
- admin_email and admin_password: makes an admin account on start.
- disable_registration: stops new sign-ups.
- per_minute_request_limit: 0 means no limit.

Your data is saved in the add-on's own data folder.
Back up the add-on to keep your accounts and keys.

## Notes

- Relay version: 3.4.1. To change it, edit `RELAY_REF` in the Dockerfile.
- This is an add-on repository, so it does not use HACS.
