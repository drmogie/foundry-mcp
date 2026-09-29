# Foundry MCP

Lets Claude work with a Foundry VTT test world.

Version: 2026.09.29.7

## What is in here

- `foundry-module/fga-relay-connect/` is the Foundry module that links a world to the relay.
- `mcp-server/` is the Python MCP server. It talks to the relay. See its README.
- The relay is now the **Foundry VTT MCP & Rest Relay**, a Home Assistant add-on. It lives in the tabletop add-ons repository: https://github.com/drmogie/ha-foundry-vtt-addon (folder `foundry_mcp_rest_relay`). It was called FGA Relay.

The old ThreeHats relay add-on was removed on 2026-09-29.

## Set up

1. In Home Assistant add the repository https://github.com/drmogie/ha-foundry-vtt-addon (Settings, Add-ons, Add-on Store, Repositories). Install **Foundry VTT MCP & Rest Relay**.
2. Set the login in the add-on options. Start it.
3. In Nginx Proxy Manager, add a proxy host for the relay. Point it at port 3011. Turn on Websockets and SSL. Keep it on the home network only.
4. Install the fga-relay-connect module in the Foundry world and follow the steps on the relay page.
5. Make a token on the relay page and put it in the MCP server settings.
