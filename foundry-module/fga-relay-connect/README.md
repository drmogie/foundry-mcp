# FGA Relay Connect

Version: 2026.09.29.4

Foundry module that links one browser to your own FGA Relay.

## Use
- Copy the `fga-relay-connect` folder into Foundry `Data/modules`.
- Restart Foundry and turn the module on.
- Game Settings, Configure Settings, FGA Relay Connect.
- Paste the relay address and connect key from the relay page.
- Turn on "Connect this browser to the relay".

Settings are per browser. Players leave it off.

## What it does
- Opens one socket to the relay and says hello with the world, system and version.
- Reconnects on its own, waiting longer each time up to 30 seconds.
- Stops and tells you if the key is wrong.
- Answers commands from the relay: ping, world, list, get, chat, encounters, effects, scene, users, roll, sendChat, update, create, delete, useItem, moveToken, switchScene.
- Never touches User or Setting documents.

## Tests
    node --test tests/link.test.mjs tests/commands.test.mjs

## Changelog
### 2026.09.29.4
- Combat: make a combat, add tokens, roll initiative, start, turns and rounds, end.
- Apply damage, healing or temporary hit points.
- 47 tests with a pretend Foundry.

### 2026.09.29.3
- List folders and read files from Foundry data.
- 40 tests with a pretend Foundry.

### 2026.09.29.2
- Commands for reading and changing the world, rolling, chat, items, tokens and scenes.
- 33 tests with a pretend Foundry.

### 2026.09.29.1
- First version.
