import test from "node:test";
import assert from "node:assert/strict";
import { makeCommands } from "../scripts/commands.mjs";

/** A small pretend Foundry for the newer commands. */
function world() {
  const docs = new Map();
  const log = [];
  const doc = (documentName, id, extra = {}) => {
    const d = {
      documentName, id, uuid: `${documentName}.${id}`, name: extra.name ?? id,
      async update(data) { log.push(["update", d.uuid, data]); for (const [k, v] of Object.entries(data)) set(d, k, v); },
      ...extra
    };
    docs.set(d.uuid, d);
    return d;
  };
  const set = (obj, path, value) => {
    const keys = path.split(".");
    let cur = obj;
    for (const k of keys.slice(0, -1)) cur = cur[k] ??= {};
    cur[keys.at(-1)] = value;
  };
  const rolls = [];
  class Roll {
    constructor(formula) { this.formula = formula; }
    async evaluate() { this.total = 12; this.dice = [{ faces: 20, results: [{ result: 10 }] }]; return this; }
    async toMessage() {}
  }
  const bob = doc("Actor", "a1", {
    name: "Bob", type: "character",
    statuses: new Set(),
    system: {
      abilities: { con: { mod: 2 } },
      attributes: { hp: { value: 10, max: 40, temp: 0 }, death: { success: 1, failure: 2 } },
      spells: { spell1: { value: 2, max: 4 }, spell2: { value: 0, max: 2 }, spell3: { value: 0, max: 0 }, pact: { value: 1, max: 1, level: 3 } }
    },
    items: [],
    async toggleStatusEffect(id, { active }) { if (active) bob.statuses.add(id); else bob.statuses.delete(id); return active; },
    async rollDeathSave(cfg, dialog, message) { rolls.push(["death", cfg, dialog, message]); return [{ formula: "1d20", total: 14, dice: [{ faces: 20, results: [{ result: 14 }] }] }]; },
    async rollSavingThrow(cfg) { rolls.push(["save", cfg]); return [{ formula: "1d20 + 9", total: 19, dice: [{ faces: 20, results: [{ result: 10 }] }] }]; },
    async rollAbilityCheck(cfg) { rolls.push(["ability", cfg]); return [{ formula: "1d20 + 5", total: 15, dice: [] }]; },
    async rollSkill(cfg) { rolls.push(["skill", cfg]); return [{ formula: "1d20 + 4", total: 7, dice: [] }]; },
    async getTokenDocument(data) { return { toObject: () => ({ name: data.name ?? "Bob", ...data }) }; }
  });
  const arrows = doc("Item", "i1", { name: "Arrows", type: "consumable", system: { quantity: 25 } });
  const wand = doc("Item", "i2", { name: "Wand", type: "equipment", system: { uses: { spent: 1, max: 3 } } });
  bob.items = [arrows, wand];
  const scene = doc("Scene", "s1", { name: "Tavern", async createEmbeddedDocuments(type, rows) { log.push(["embed", type, rows]); return rows.map((r, i) => doc("Token", `t${i}`, { name: r.name })); } });
  const messages = [];
  const targeted = [];
  const token = doc("Token", "t9", { name: "Foreman", object: { setTarget(on) { on ? targeted.push("Foreman") : targeted.splice(0); } } });
  const table = doc("RollTable", "r1", { name: "Loot", async draw(opts) { log.push(["draw", opts]); return { roll: { formula: "1d6", total: 4, dice: [] }, results: [{ description: "A gem", documentUuid: null, range: [4, 4] }] }; } });
  const journalCls = { async create(data) { log.push(["journal", data]); return doc("JournalEntry", "j1", { name: data.name }); } };
  const packDocs = [{ _id: "m1", name: "Goblin", type: "npc" }, { _id: "m2", name: "Owlbear", type: "npc" }];
  const pack = {
    collection: "dnd5e.monsters", title: "Monsters", documentName: "Actor", metadata: { packageName: "dnd5e" }, index: { size: 2 },
    async getIndex() { return packDocs; }
  };
  const actorsCollection = {
    async importFromCompendium(p, id, update) { log.push(["import", p.collection, id, update]); return doc("Actor", `imp-${id}`, { name: update.name ?? "Goblin", async getTokenDocument(d) { return { toObject: () => ({ name: d.name ?? "Goblin", ...d }) }; } }); }
  };
  const game = {
    user: { targets: new Set() },
    scenes: { viewed: scene, active: scene, get: (id) => (id === "s1" ? scene : undefined) },
    messages: { contents: messages },
    collections: new Map([["RollTable", { contents: [table] }], ["Actor", actorsCollection]]),
    packs: { contents: [pack], get: (id) => (id === "dnd5e.monsters" ? pack : undefined) },
    i18n: { localize: (s) => s }
  };
  const CONFIG = {
    statusEffects: [{ id: "prone", name: "Prone" }, { id: "poisoned", name: "Poisoned" }],
    DND5E: { abilities: { str: { label: "Strength" }, dex: { label: "Dexterity" } }, skills: { ath: { label: "Athletics" }, slt: { label: "Sleight of Hand" } } },
    JournalEntry: { documentClass: journalCls }
  };
  const ctx = { game, fromUuid: async (u) => docs.get(u) ?? null, Roll, ChatMessage: {}, CONFIG, getDocumentClass: (t) => CONFIG[t]?.documentClass };
  return { ctx, c: makeCommands(ctx), bob, docs, log, rolls, messages, targeted, scene, token };
}

const msg = (alias, flavor, content, rolls = []) => ({ speaker: { alias }, flavor, content, rolls });

test("conditions: add, remove, toggle, by name, and unknown ones explain", async () => {
  const { c } = world();
  let r = await c.condition({ uuid: "Actor.a1", condition: "Prone" });
  assert.deepEqual(r.conditions, ["prone"]);
  assert.equal(r.active, true);
  r = await c.condition({ uuid: "Actor.a1", condition: "prone", state: "toggle" });
  assert.equal(r.active, false);
  await c.condition({ uuid: "Actor.a1", condition: "poisoned" });
  r = await c.condition({ uuid: "Actor.a1", condition: "poisoned", state: "remove" });
  assert.deepEqual(r.conditions, []);
  assert.deepEqual((await c.conditions({ uuid: "Actor.a1" })).conditions, []);
  await assert.rejects(c.condition({ uuid: "Actor.a1", condition: "sleepy" }), /Unknown condition sleepy. Use one of: prone, poisoned/);
  await assert.rejects(c.condition({ uuid: "Actor.a1", condition: "prone", state: "maybe" }), /Unknown state/);
  await assert.rejects(c.condition({ uuid: "Actor.a1" }), /condition is required/);
});

test("death save rolls without a dialog and reports the tally", async () => {
  const { c, rolls } = world();
  const r = await c.deathSave({ uuid: "Actor.a1" });
  assert.equal(r.roll.total, 14);
  assert.equal(r.successes, 1);
  assert.equal(r.failures, 2);
  assert.deepEqual(rolls[0].slice(1), [{}, { configure: false }, { create: true }]);
});

test("checks: saves, abilities and skills, names or short keys, advantage and DC", async () => {
  const { c, rolls } = world();
  let r = await c.check({ uuid: "Actor.a1", kind: "save", key: "Dexterity", dc: 15, advantage: true });
  assert.equal(r.roll.total, 19);
  assert.equal(r.success, true);
  assert.deepEqual(rolls[0], ["save", { ability: "dex", advantage: true }]);
  r = await c.check({ uuid: "Actor.a1", kind: "skill", key: "Sleight of Hand", dc: 10 });
  assert.equal(r.success, false);
  assert.deepEqual(rolls[1], ["skill", { skill: "slt" }]);
  r = await c.check({ uuid: "Actor.a1", key: "str" });
  assert.equal(r.kind, "ability");
  assert.equal(r.dc, undefined);
  await assert.rejects(c.check({ uuid: "Actor.a1", kind: "skill", key: "juggling" }), /Unknown skill juggling. Use one of: ath, slt/);
  await assert.rejects(c.check({ uuid: "Actor.a1", kind: "nap", key: "str" }), /Unknown kind/);
  await assert.rejects(c.check({ uuid: "Actor.a1", key: "str", advantage: true, disadvantage: true }), /not both/);
  await assert.rejects(c.check({ uuid: "Actor.a1" }), /key is required/);
});

test("resources list slots, limited uses and consumables", async () => {
  const { c } = world();
  const r = await c.resources({ uuid: "Actor.a1" });
  assert.deepEqual(r.slots.map((s) => [s.key, s.value, s.max]), [["spell1", 2, 4], ["spell2", 0, 2], ["pact", 1, 1]]);
  assert.deepEqual(r.uses.map((u) => [u.name, u.left, u.max]), [["Wand", 2, 3]]);
  assert.deepEqual(r.quantities.map((q) => [q.name, q.quantity]), [["Arrows", 25]]);
});

test("resource: spend, restore and set for slots, uses and quantity, with limits", async () => {
  const { c, bob, docs } = world();
  let r = await c.resource({ uuid: "Actor.a1", target: "slot", level: 1 });
  assert.deepEqual([r.before, r.after], [2, 1]);
  r = await c.resource({ uuid: "Actor.a1", target: "slot", level: 1, mode: "restore", amount: 9 });
  assert.equal(r.after, 4);
  r = await c.resource({ uuid: "Actor.a1", target: "slot", level: "pact", mode: "set", amount: 0 });
  assert.equal(r.after, 0);
  await assert.rejects(c.resource({ uuid: "Actor.a1", target: "slot", level: 2 }), /only 0 level 2 slots left/);
  await assert.rejects(c.resource({ uuid: "Actor.a1", target: "slot", level: 3 }), /no level 3 spell slots/);
  r = await c.resource({ target: "uses", itemUuid: "Item.i2" });
  assert.deepEqual([r.before, r.after], [2, 1]);
  assert.equal(docs.get("Item.i2").system.uses.spent, 2);
  await c.resource({ target: "uses", itemUuid: "Item.i2", amount: 1 });
  await assert.rejects(c.resource({ target: "uses", itemUuid: "Item.i2" }), /only 0 uses left/);
  r = await c.resource({ target: "quantity", itemUuid: "Item.i1", amount: 5 });
  assert.deepEqual([r.before, r.after], [25, 20]);
  await assert.rejects(c.resource({ target: "quantity", itemUuid: "Item.i1", amount: 99 }), /only 20 of Arrows/);
  await assert.rejects(c.resource({ uuid: "Actor.a1", target: "gold" }), /Unknown target/);
  await assert.rejects(c.resource({ uuid: "Actor.a1", mode: "steal", level: 1 }), /Unknown mode/);
  await assert.rejects(c.resource({ uuid: "Actor.a1", level: 1, amount: -2 }), /whole number/);
  assert.equal(bob.system.spells.spell1.value, 4);
});

test("lastAttack ties the attack, the hit or miss, and the damage together", async () => {
  const { c, messages } = world();
  const dmg = { formula: "1d8 + 4", total: 9, dice: [{ faces: 8, results: [{ result: 5 }] }] };
  messages.push(
    msg("Foreman", "Longsword - Attack Roll", "", [{ formula: "1d20 + 8", total: 13, dice: [] }]),
    msg("Foreman", "", "<p><em>Foreman: miss on Bob (13 vs AC 15). No damage rolled.</em></p>"),
    msg("Bob", "Shortbow - Attack Roll", "", [{ formula: "1d20 + 9", total: 18, dice: [{ faces: 20, results: [{ result: 9 }] }] }]),
    msg("Bob", "", "<p><em>Bob: hit on Foreman (18 vs AC 18). Rolling damage.</em></p>"),
    msg("Bob", "Shortbow - Damage Roll", "", [dmg])
  );
  let r = await c.lastAttack({});
  assert.equal(r.attacker, "Bob");
  assert.equal(r.weapon, "Shortbow");
  assert.equal(r.outcome, "hit");
  assert.equal(r.target, "Foreman");
  assert.equal(r.ac, 18);
  assert.equal(r.attack.total, 18);
  assert.equal(r.damage.total, 9);
  assert.equal(r.pending, false);
  r = await c.lastAttack({ alias: "foreman" });
  assert.equal(r.outcome, "miss");
  assert.equal(r.damage, null);
  assert.equal(r.pending, false);
  await assert.rejects(c.lastAttack({ alias: "Nobody" }), /No recent attack roll from Nobody/);
});

test("lastAttack says damage is still pending after a hit with no damage roll yet", async () => {
  const { c, messages } = world();
  messages.push(
    msg("Bob", "Shortbow - Attack Roll", "", [{ formula: "1d20", total: 20, dice: [] }]),
    msg("Bob", "", "<p><em>Bob: critical hit on Foreman (20 vs AC 18). Rolling damage.</em></p>")
  );
  const r = await c.lastAttack({});
  assert.equal(r.outcome, "critical hit");
  assert.equal(r.pending, true);
  await assert.rejects(world().c.lastAttack({}), /No recent attack roll in chat/);
});

test("target sets and clears targets", async () => {
  const { c, targeted } = world();
  assert.deepEqual((await c.target({ uuids: ["Token.t9"] })).targets, ["Token.t9"]);
  assert.deepEqual(targeted, ["Foreman"]);
  await c.target({});
  await assert.rejects(c.target({ uuids: ["Token.nope"] }), /Nothing found/);
});

test("tokens: create from an actor, and change hidden or position", async () => {
  const { c, log } = world();
  const r = await c.tokenCreate({ actorUuid: "Actor.a1", x: 200, y: 300, hidden: true });
  assert.equal(r.scene.name, "Tavern");
  assert.equal(r.tokens.length, 1);
  assert.deepEqual(log.find((l) => l[0] === "embed")[2][0], { name: "Bob", x: 200, y: 300, hidden: true });
  const s = await c.tokenSet({ uuid: "Token.t9", hidden: true, rotation: 90 });
  assert.deepEqual(s.updated, { hidden: true, rotation: 90 });
  await assert.rejects(c.tokenSet({ uuid: "Token.t9" }), /Nothing to change/);
  await assert.rejects(c.tokenSet({ uuid: "Actor.a1", hidden: true }), /not a token/);
  await assert.rejects(c.tokenCreate({ actorUuid: "Scene.s1" }), /not an actor/);
  await assert.rejects(c.tokenCreate({ actorUuid: "Actor.a1", sceneId: "nope" }), /No scene with id nope/);
});

test("journals: make one with pages, or add pages to an existing one", async () => {
  const { c, log, docs } = world();
  const r = await c.journal({ name: "Session 1", content: "<p>Hello</p>" });
  assert.equal(r.created.name, "Session 1");
  const data = log.find((l) => l[0] === "journal")[1];
  assert.deepEqual(data.pages, [{ name: "Session 1", type: "text", text: { content: "<p>Hello</p>", format: 1 } }]);
  const multi = await c.journal({ name: "Town", pages: [{ name: "Inn", text: "a" }, { name: "Smith", text: "b" }], folder: "f1" });
  assert.equal(multi.pages, 2);
  assert.equal(log.filter((l) => l[0] === "journal")[1][1].folder, "f1");
  const entry = docs.get("JournalEntry.j1");
  entry.createEmbeddedDocuments = async (type, rows) => rows.map((x, i) => ({ id: `p${i}`, uuid: `p${i}`, name: x.name, documentName: type }));
  const added = await c.journal({ uuid: "JournalEntry.j1", name: "More", content: "x" });
  assert.equal(added.addedPages[0].name, "More");
  await assert.rejects(c.journal({ uuid: "Actor.a1", name: "x" }), /not a journal entry/);
  await assert.rejects(c.journal({}), /page name is required/);
});

test("tables: roll by uuid or name, quiet on request", async () => {
  const { c, log } = world();
  const r = await c.tableRoll({ name: "Loot" });
  assert.equal(r.roll.total, 4);
  assert.equal(r.results[0].text, "A gem");
  await c.tableRoll({ uuid: "RollTable.r1", chat: false });
  assert.deepEqual(log.filter((l) => l[0] === "draw").map((l) => l[1]), [{ displayChat: true }, { displayChat: false }]);
  await assert.rejects(c.tableRoll({ name: "Nope" }), /No rollable table called Nope/);
  await assert.rejects(c.tableRoll({ uuid: "Actor.a1" }), /not a rollable table/);
});

test("compendiums: list packs, search one, import an actor and place it", async () => {
  const { c, log } = world();
  const packs = await c.packs({ type: "Actor", q: "monst" });
  assert.deepEqual(packs.map((p) => p.id), ["dnd5e.monsters"]);
  assert.deepEqual(await c.packs({ type: "Item" }), []);
  const idx = await c.packIndex({ pack: "dnd5e.monsters", q: "owl" });
  assert.equal(idx.total, 1);
  assert.equal(idx.results[0].uuid, "Compendium.dnd5e.monsters.Actor.m2");
  await assert.rejects(c.packIndex({ pack: "nope" }), /No compendium called nope/);
  const r = await c.importFromPack({ pack: "dnd5e.monsters", id: "m1", name: "Gob", place: true, x: 100, y: 100 });
  assert.equal(r.imported.name, "Gob");
  assert.equal(r.tokens.length, 1);
  assert.deepEqual(log.find((l) => l[0] === "import").slice(1), ["dnd5e.monsters", "m1", { name: "Gob" }]);
  const plain = await c.importFromPack({ pack: "dnd5e.monsters", id: "m2" });
  assert.equal(plain.tokens, undefined);
  await assert.rejects(c.importFromPack({ pack: "dnd5e.monsters" }), /id is required/);
  await assert.rejects(c.importFromPack({ pack: "nope", id: "x" }), /No compendium called nope/);
});
