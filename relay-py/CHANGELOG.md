# Changelog

## 2026.09.29.6
- New route POST /api/v1/rest. Long or short rest for an actor or token. Uses the D&D 5e rules.
- Needs FGA Relay Connect 2026.09.29.5 in Foundry.
- Tests: 58 relay tests.

## 2026.09.29.5
- Combat: make a combat, add tokens, roll initiative, start, next or previous turn and round, end.
- Apply damage, healing or temporary hit points. Uses the D&D 5e rules.
- Activity log: every write is recorded with the token name, world, result and any error. Read it at /api/v1/activity.
- Blocked writes are logged too.
- Needs FGA Relay Connect 2026.09.29.4 in Foundry.
- Tests: 57 relay tests.

## 2026.09.29.4
- Files: list folders and read files through Foundry (routes /files and /file).
- Plain-words messages when a request has a mistake (422).
- Works with the MCP server. Same tool names as before.
- Needs FGA Relay Connect 2026.09.29.3 in Foundry.
- Tests: 52 relay tests.

## 2026.09.29.3
- The real REST routes. Read: world, documents list, one document, chat, encounters, effects, scene, users.
- Write: update, create, delete (needs confirm=true), chat, rolls, use item, move token, switch scene.
- Read tokens cannot write. A quiet roll (`chat: false`) is allowed for read tokens.
- New add-on option write_worlds. Writes only work in those worlds. Default mcp-test.
- Foundry errors return 400 with plain words. A missing Foundry client returns 502.
- User and Setting documents are blocked in the module.
- Needs FGA Relay Connect 2026.09.29.2 in Foundry.
- Tests: 49 relay tests.

## 2026.09.29.2
- API tokens. Make, list and revoke them on the web page.
- Access: read only, or read and write.
- Optional world limit and expiry date.
- Shows last used time.
- Only a hash is stored, so a token shows once.
- New token routes: /api/v1/whoami, /api/v1/clients, /api/v1/ping. Header is x-api-key or Bearer.
- Tests: 36 relay tests.

## 2026.09.29.1
- First version of our own relay.
- One login page. Username and password come from the add-on options. No sign-up.
- Status lights for relay, Foundry client and world.
- Copy boxes for the relay address and connect key. The address matches how you opened the page, so https becomes wss.
- Make a new key at any time.
- Test the link button. It sends a ping to Foundry and shows the round trip time.
- Foundry side is the FGA Relay Connect module. It reconnects on its own.
- REST routes for actors, items and the rest come in a later version.
