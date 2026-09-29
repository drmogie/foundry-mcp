# Changelog

## 2026.09.29.1
- First version of our own relay.
- One login page. Username and password come from the add-on options. No sign-up.
- Status lights for relay, Foundry client and world.
- Copy boxes for the relay address and connect key. The address matches how you opened the page, so https becomes wss.
- Make a new key at any time.
- Test the link button. It sends a ping to Foundry and shows the round trip time.
- Foundry side is the FGA Relay Connect module. It reconnects on its own.
- REST routes for actors, items and the rest come in a later version.
