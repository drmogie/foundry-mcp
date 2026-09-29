# Foundry MCP

Lets Claude work with a Foundry VTT test world.

Version: 2026.09.29.6

## What is in here

- `relay-py/` is our own relay, a Home Assistant add-on (FGA Relay). It has the REST API and a web page for tokens. See its README.
- `foundry-module/fga-relay-connect/` is the Foundry module that links a world to the relay.
- `mcp-server/` is the Python MCP server. It talks to the relay. See its README.

The old ThreeHats relay add-on was removed on 2026-09-29.

## Set up

1. Install the FGA Relay add-on from this repository (Settings, Add-ons, Add-on Store, Repositories).
2. Set the login in the add-on options. Start it.
3. In Nginx Proxy Manager, add a proxy host for the relay. Point it at port 3011. Turn on Websockets and SSL. Keep it on the home network only.
4. Install the fga-relay-connect module in the Foundry world and follow the steps on the relay page.
5. Make a token on the relay page and put it in the MCP server settings.

## Notes

- This is an add-on repository, so it does not use HACS.
- GitHub Actions builds the relay image for aarch64 and amd64 and publishes it to ghcr.io. After the first build, set the package to Public on GitHub.
