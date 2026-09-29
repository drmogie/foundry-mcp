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
