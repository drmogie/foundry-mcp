import test from "node:test";
import assert from "node:assert/strict";
import { makeCommands, ALLOWED } from "../scripts/commands.mjs";

/** A tiny pretend Foundry, just enough for these commands. */
function fakeWorld() {
  const docs = new Map();
  const made = [];
  const log = [];

  function makeDoc(documentName, id, fields = {}) {
    const doc = {
      documentName, id, uuid: `${documentName}.${id}`, name: fields.name ?? id, type: fields.type,
      folder: fields.folder ?? null,
      data: { ...fields },
      async update(data, options) { log.push(["update", doc.uuid, data, options]); Object.assign(doc.data, data); },
      async delete(options) { log.push(["delete", doc.uuid, options]); docs.delete(doc.uuid); },
      toObject(source = true) { return { _id: id, ...doc.data, prepared: !source }; },
      ...fields.extra
    };
    docs.set(doc.uuid, doc);
    return doc;
  }

  const collection = (list) => ({ contents: list, size: list.length });
  const actors = [makeDoc("Actor", "a1", { name: "Bob", type: "character" }), makeDoc("Actor", "a2", { name: "Foreman", type: "npc" }),
                  makeDoc("Actor", "a3", { name: "Bobcat", type: "npc" })];
  actors.get = (id) => actors.find((a) => a.id === id);
  const items = [makeDoc("Item", "i1", { name: "Shortbow", type: "weapon" })];
  const scenes = [makeDoc("Scene", "s1", { name: "Tavern" }), makeDoc("Scene", "s2", { name: "Cave" })];
  scenes.get = (id) => scenes.find((s) => s.id === id);
  scenes.contents = scenes;
  scenes.active = scenes[0];
  scenes.viewed = scenes[1];
  const users = [{ id: "u1", name: "Gamemaster", role: 4, isGM: true, active: true, character: null }];

  const game = {
    world: { id: "mcp-test", title: "MCP Test" },
    version: "14.368",
    system: { id: "dnd5e", version: "6.0.5" },
    userId: "u1",
    user: { name: "Gamemaster", isGM: true, targets: new Set() },
    users: { contents: users },
    actors, scenes,
    collections: new Map([["Actor", collection(actors)], ["Item", collection(items)], ["Scene", collection(scenes)]]),
    messages: { contents: [] },
    combats: { contents: [] }
  };

  class Roll {
    constructor(formula) { this.formula = formula; }
    async evaluate() { this.total = 12; this.dice = [{ faces: 20, results: [{ result: 12 }] }]; return this; }
    async toMessage(data, options) { log.push(["rollMessage", this.formula, options]); }
  }
  const ChatMessage = {
    getSpeaker: ({ actor }) => ({ alias: actor.name, actor: actor.id }),
    async create(data) { log.push(["chat", data]); return { id: "m1" }; }
  };
  const CONFIG = {};
  for (const t of ALLOWED) {
    CONFIG[t] = { documentClass: { async create(data, opts) { made.push([t, data, opts]); return makeDoc(t, `new${made.length}`, data); } } };
  }
  const fromUuid = async (uuid) => docs.get(uuid) ?? null;
  return { game, Roll, ChatMessage, CONFIG, fromUuid, docs, made, log, makeDoc, actors, items };
}

const setup = () => { const w = fakeWorld(); return { w, c: makeCommands(w) }; };

test("ping", async () => { assert.equal((await setup().c.ping()).pong, true); });

test("world summary", async () => {
  const { c } = setup();
  const w = await c.world();
  assert.equal(w.id, "mcp-test");
  assert.equal(w.system.id, "dnd5e");
  assert.deepEqual(w.activeScene, { id: "s1", name: "Tavern" });
  assert.equal(w.counts.Actor, 3);
});

test("list filters by name and limits", async () => {
  const { c } = setup();
  const r = await c.list({ documentType: "Actor", q: "bob" });
  assert.equal(r.total, 2);
  assert.deepEqual(r.results.map((x) => x.name), ["Bob", "Bobcat"]);
  const one = await c.list({ documentType: "Actor", limit: 1 });
  assert.equal(one.returned, 1);
  assert.equal(one.total, 3);
});

test("list refuses types that are not listable", async () => {
  const { c } = setup();
  await assert.rejects(c.list({ documentType: "User" }), /Cannot list User/);
  await assert.rejects(c.list({}), /documentType is required/);
});

test("get returns prepared data by default and source on request", async () => {
  const { c } = setup();
  assert.equal((await c.get({ uuid: "Actor.a1" })).data.prepared, true);
  assert.equal((await c.get({ uuid: "Actor.a1", source: true })).data.prepared, false);
});

test("get gives a plain message when nothing is found", async () => {
  await assert.rejects(setup().c.get({ uuid: "Actor.nope" }), /Nothing found for Actor.nope/);
  await assert.rejects(setup().c.get({}), /uuid is required/);
});

test("User and Setting documents are blocked everywhere", async () => {
  const { w, c } = setup();
  w.makeDoc("User", "u1", { name: "Gamemaster" });
  w.makeDoc("Setting", "st1", { name: "core.x" });
  await assert.rejects(c.get({ uuid: "User.u1" }), /not allowed/);
  await assert.rejects(c.update({ uuid: "User.u1", data: { role: 4 } }), /not allowed/);
  await assert.rejects(c.delete({ uuid: "Setting.st1" }), /not allowed/);
  await assert.rejects(c.create({ documentType: "User", data: { name: "x" } }), /not allowed/);
  await assert.rejects(c.create({ documentType: "Setting", data: {} }), /not allowed/);
});

test("update changes the document", async () => {
  const { w, c } = setup();
  const r = await c.update({ uuid: "Actor.a2", data: { name: "Foreman II" } });
  assert.deepEqual(r.updated, ["name"]);
  assert.equal(w.docs.get("Actor.a2").name, "Foreman");  // fake keeps name field; data changed:
  assert.equal(w.docs.get("Actor.a2").data.name, "Foreman II");
  await assert.rejects(c.update({ uuid: "Actor.a2" }), /data is required/);
});

test("create makes a document and can use a parent", async () => {
  const { w, c } = setup();
  const r = await c.create({ documentType: "Item", data: { name: "Arrows" }, parentUuid: "Actor.a1" });
  assert.equal(r.created.length, 1);
  assert.equal(w.made[0][0], "Item");
  assert.equal(w.made[0][2].parent.uuid, "Actor.a1");
  await assert.rejects(c.create({ documentType: "Item" }), /data is required/);
});

test("delete removes and reports what it removed", async () => {
  const { w, c } = setup();
  const r = await c.delete({ uuid: "Actor.a3" });
  assert.equal(r.deleted.name, "Bobcat");
  assert.equal(w.docs.has("Actor.a3"), false);
});

test("roll evaluates and posts to chat by default", async () => {
  const { w, c } = setup();
  const r = await c.roll({ formula: "1d20+5", flavor: "Check" });
  assert.equal(r.total, 12);
  assert.deepEqual(r.dice, [{ faces: 20, results: [12] }]);
  assert.equal(w.log.some((l) => l[0] === "rollMessage"), true);
  await assert.rejects(c.roll({}), /formula is required/);
});

test("roll can stay out of chat", async () => {
  const { w, c } = setup();
  await c.roll({ formula: "2d6", chat: false });
  assert.equal(w.log.some((l) => l[0] === "rollMessage"), false);
});

test("sendChat as an actor, as an alias, or plain", async () => {
  const { w, c } = setup();
  await c.sendChat({ content: "Hi", actorId: "a1" });
  await c.sendChat({ content: "Hi", alias: "Narrator" });
  const chats = w.log.filter((l) => l[0] === "chat").map((l) => l[1]);
  assert.equal(chats[0].speaker.alias, "Bob");
  assert.equal(chats[1].speaker.alias, "Narrator");
  await assert.rejects(c.sendChat({ content: "Hi", actorId: "zzz" }), /No actor with id zzz/);
  await assert.rejects(c.sendChat({}), /content is required/);
});

test("chat returns the latest messages with a cap", async () => {
  const { w, c } = setup();
  w.game.messages.contents = Array.from({ length: 30 }, (_, i) => ({
    id: `m${i}`, uuid: `ChatMessage.m${i}`, timestamp: i, content: `hi ${i}`, whisper: [], rolls: [{ formula: "1d20", total: i }],
    author: { name: "Gamemaster" }, speaker: { alias: "Bob" }
  }));
  const r = await c.chat({ limit: 5 });
  assert.equal(r.length, 5);
  assert.equal(r.at(-1).id, "m29");
  assert.deepEqual(r.at(-1).rolls, [{ formula: "1d20", total: 29 }]);
  assert.equal((await c.chat({ limit: 9999 })).length, 30);
});

test("encounters list combatants", async () => {
  const { w, c } = setup();
  w.game.combats.contents = [{ id: "c1", uuid: "Combat.c1", round: 2, turn: 1, started: true, active: true, scene: { id: "s1" },
    combatants: { contents: [{ id: "k1", uuid: "Combat.c1.Combatant.k1", name: "Bob", actorId: "a1", tokenId: "t1", initiative: 18 }] } }];
  const r = await c.encounters();
  assert.equal(r[0].round, 2);
  assert.equal(r[0].combatants[0].initiative, 18);
});

test("effects works from an actor or a token", async () => {
  const { w, c } = setup();
  const actor = w.docs.get("Actor.a1");
  actor.effects = { contents: [{ id: "e1", uuid: "e1u", name: "Bloodied", disabled: false, statuses: new Set(["bloodied"]), duration: {} }] };
  const token = w.makeDoc("Token", "t1", { name: "Bob" });
  token.actor = actor;
  assert.equal((await c.effects({ uuid: "Actor.a1" })).effects[0].name, "Bloodied");
  assert.deepEqual((await c.effects({ uuid: "Token.t1" })).effects[0].statuses, ["bloodied"]);
  await assert.rejects(c.effects({ uuid: "Item.i1" }), /not an actor/);
});

test("scene picks by id, name, viewed, or active", async () => {
  const { c } = setup();
  assert.equal((await c.scene({})).name, "Tavern");
  assert.equal((await c.scene({ viewed: true })).name, "Cave");
  assert.equal((await c.scene({ id: "s2" })).name, "Cave");
  assert.equal((await c.scene({ name: "Tavern" })).id, "s1");
  await assert.rejects(c.scene({ id: "zzz" }), /No matching scene/);
});

test("users", async () => {
  const r = await setup().c.users();
  assert.deepEqual(r, [{ id: "u1", name: "Gamemaster", role: 4, isGM: true, active: true, characterId: null }]);
});

test("moveToken changes x and y on tokens only", async () => {
  const { w, c } = setup();
  w.makeDoc("Token", "t2", { name: "Foreman" });
  const r = await c.moveToken({ uuid: "Token.t2", x: 100, y: 200 });
  assert.deepEqual([r.x, r.y], [100, 200]);
  await assert.rejects(c.moveToken({ uuid: "Actor.a1", x: 1, y: 1 }), /not a token/);
  await assert.rejects(c.moveToken({ uuid: "Token.t2", x: 1 }), /y is required/);
});

test("switchScene views or activates", async () => {
  const { w, c } = setup();
  let viewed = 0, activated = 0;
  w.game.scenes[1].view = async () => { viewed++; };
  w.game.scenes[1].activate = async () => { activated++; };
  await c.switchScene({ name: "Cave" });
  await c.switchScene({ id: "s2", activate: true });
  assert.deepEqual([viewed, activated], [1, 1]);
  await assert.rejects(c.switchScene({ name: "Nope" }), /No matching scene/);
});

test("useItem sets targets then uses the item", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  let used = 0;
  item.use = async () => { used++; };
  const set = [];
  const token = w.makeDoc("Token", "t9", { name: "Foreman" });
  token.object = { setTarget: (on) => set.push(on) };
  w.game.user.targets = new Set([{ setTarget: (on) => set.push("clear-" + on) }]);
  const r = await c.useItem({ uuid: "Item.i1", targets: ["Token.t9"] });
  assert.equal(used, 1);
  assert.deepEqual(set, ["clear-false", true]);
  assert.deepEqual(r.targets, ["Token.t9"]);
  await assert.rejects(c.useItem({ uuid: "Actor.a1" }), /not an item/);
});

test("useItem can run one activity, and complains about a missing one", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  let ran = 0;
  item.system = { activities: { get: (id) => (id === "act1" ? { use: async () => { ran++; } } : undefined) } };
  await c.useItem({ uuid: "Item.i1", activityId: "act1" });
  assert.equal(ran, 1);
  await assert.rejects(c.useItem({ uuid: "Item.i1", activityId: "nope" }), /No activity nope/);
});

test("useItem reports a spell area and can clear it", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  const scene = w.game.scenes.viewed;
  scene.regions = { contents: [] };
  item.use = async () => {
    const region = w.makeDoc("Region", "r1", { name: "Fireball" });
    scene.regions.contents.push(region);
  };
  const kept = await c.useItem({ uuid: "Item.i1" });
  assert.equal(kept.areas.length, 1);
  assert.equal(kept.areasCleared, undefined);
  assert.ok(w.docs.has("Region.r1"));
  scene.regions.contents.length = 0;
  w.docs.delete("Region.r1");
  const cleared = await c.useItem({ uuid: "Item.i1", clearArea: true });
  assert.equal(cleared.areasCleared, true);
  assert.ok(!w.docs.has("Region.r1"));
});

test("useItem with no area leaves out the areas note", async () => {
  const { w, c } = setup();
  w.docs.get("Item.i1").use = async () => {};
  w.game.scenes.viewed.regions = { contents: [] };
  const r = await c.useItem({ uuid: "Item.i1", clearArea: true });
  assert.equal(r.areas, undefined);
});

test("a Region can be deleted through the relay", async () => {
  const { w, c } = setup();
  w.makeDoc("Region", "r9", { name: "Old" });
  const r = await c.delete({ uuid: "Region.r9" });
  assert.equal(r.deleted.name, "Old");
});

// ----- files and chat flavor -----

function withFiles(overrides = {}) {
  const w = fakeWorld();
  w.FilePicker = { browse: async (source, path) => ({ target: path, dirs: [`${path}/scripts`], files: [`${path}/module.json`] }) };
  w.fetch = async (url) => ({
    ok: true, status: 200,
    headers: { get: () => "application/json" },
    arrayBuffer: async () => new TextEncoder().encode(`{"url":"${url}"}`).buffer
  });
  w.getRoute = (p) => `/${p}`;
  Object.assign(w, overrides);
  return { w, c: makeCommands(w) };
}

test("listFiles browses a folder", async () => {
  const { c } = withFiles();
  const r = await c.listFiles({ path: "modules/fga" });
  assert.deepEqual(r.dirs, ["modules/fga/scripts"]);
  assert.deepEqual(r.files, ["modules/fga/module.json"]);
  assert.equal((await c.listFiles({})).source, "data");
});

test("listFiles refuses odd sources and paths", async () => {
  const { c } = withFiles();
  await assert.rejects(c.listFiles({ source: "s3-secret" }), /Cannot browse/);
  await assert.rejects(c.listFiles({ path: "../Config" }), /not allowed/);
  await assert.rejects(c.listFiles({ path: "modules/%2e%2e/x".replace("%2e%2e", "..") }), /not allowed/);
});

test("readFile returns base64 with size and type", async () => {
  const { c } = withFiles();
  const r = await c.readFile({ path: "modules/fga/module.json" });
  assert.equal(Buffer.from(r.base64, "base64").toString(), '{"url":"/modules/fga/module.json"}');
  assert.equal(r.mimeType, "application/json");
  assert.equal(r.size, Buffer.from(r.base64, "base64").length);
});

test("readFile refuses climbing out, absolute paths, and other schemes", async () => {
  const { c } = withFiles();
  for (const bad of ["../secret.txt", "modules/../../x", "/etc/passwd", "https://evil.example/x", "file:///x", "modules%2F..%2F..%2Fx"]) {
    await assert.rejects(c.readFile({ path: bad }), /not allowed/, bad);
  }
  await assert.rejects(c.readFile({}), /path is required/);
});

test("readFile reports missing files and size limits", async () => {
  const missing = withFiles({ fetch: async () => ({ ok: false, status: 404 }) });
  await assert.rejects(missing.c.readFile({ path: "modules/x.js" }), /status 404/);
  const big = withFiles({ fetch: async () => ({ ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(9 * 1024 * 1024) }) });
  await assert.rejects(big.c.readFile({ path: "modules/big.bin" }), /limit/);
});

test("readFile handles files larger than one chunk", async () => {
  const bytes = new Uint8Array(100000).map((_, i) => i % 251);
  const { c } = withFiles({ fetch: async () => ({ ok: true, status: 200, headers: { get: () => "image/png" }, arrayBuffer: async () => bytes.buffer }) });
  const r = await c.readFile({ path: "modules/a.png" });
  assert.deepEqual(new Uint8Array(Buffer.from(r.base64, "base64")), bytes);
});

test("sendChat passes flavor through", async () => {
  const { w, c } = setup();
  await c.sendChat({ content: "Hi", flavor: "Test" });
  assert.equal(w.log.find((l) => l[0] === "chat")[1].flavor, "Test");
});

// ----- stage 4: combat and damage -----

function fakeCombat(w, id = "c1", sceneId = "s1") {
  const calls = [];
  const combat = {
    id, uuid: `Combat.${id}`, round: 0, turn: 0, started: false, active: true, scene: { id: sceneId },
    combatants: { contents: [] },
    async createEmbeddedDocuments(type, rows) {
      calls.push(["addCombatants", type, rows]);
      rows.forEach((r, i) => combat.combatants.contents.push({ id: `k${i}`, uuid: `k${i}u`, name: r.tokenId, tokenId: r.tokenId, actorId: r.actorId }));
    },
    async startCombat() { calls.push(["start"]); combat.started = true; combat.round = 1; },
    async nextTurn() { calls.push(["nextTurn"]); combat.turn += 1; },
    async previousTurn() { calls.push(["previousTurn"]); },
    async nextRound() { calls.push(["nextRound"]); combat.round += 1; },
    async previousRound() { calls.push(["previousRound"]); },
    async rollAll() { calls.push(["rollAll"]); },
    async rollNPC() { calls.push(["rollNpc"]); },
    async endCombat() { calls.push(["end"]); w.game.combats.contents = []; }
  };
  w.game.combats.contents.push(combat);
  w.game.combats.get = (x) => w.game.combats.contents.find((k) => k.id === x);
  w.game.combats.active = combat;
  return { combat, calls };
}

test("combatControl runs each action on the active combat", async () => {
  const { w, c } = setup();
  const { calls } = fakeCombat(w);
  const start = await c.combatControl({ action: "start" });
  assert.equal(start.combat.started, true);
  await c.combatControl({ action: "nextTurn" });
  await c.combatControl({ action: "rollNpc" });
  const ended = await c.combatControl({ action: "end", combatId: "c1" });
  assert.deepEqual(ended, { ended: { id: "c1", uuid: "Combat.c1" } });
  assert.deepEqual(calls.map((x) => x[0]), ["start", "nextTurn", "rollNpc", "end"]);
});

test("combatControl explains mistakes", async () => {
  const { w, c } = setup();
  await assert.rejects(c.combatControl({ action: "nextTurn" }), /no combat/i);
  fakeCombat(w);
  await assert.rejects(c.combatControl({ action: "dance" }), /nextTurn/);
  await assert.rejects(c.combatControl({ action: "nextTurn", combatId: "zzz" }), /No combat with id zzz/);
  await assert.rejects(c.combatControl({}), /action is required/);
});

test("combatCreate makes a combat, adds tokens once, rolls and starts", async () => {
  const { w, c } = setup();
  w.makeDoc("Token", "t1", { name: "Bob", extra: { actorId: "a1" } });
  w.makeDoc("Token", "t2", { name: "Foreman", extra: { actorId: "a2" } });
  w.game.scenes.viewed = w.game.scenes[0];
  let combat;
  w.CONFIG.Combat.documentClass.create = async (data) => {
    w.made.push(["Combat", data]);
    ({ combat } = fakeCombat(w, "new1", data.scene));
    return combat;
  };
  const r = await c.combatCreate({ tokenUuids: ["Token.t1", "Token.t2", "Token.t1"], rollInitiative: true, start: true });
  assert.equal(r.created, true);
  assert.equal(r.added, 2);
  assert.deepEqual(w.made[0], ["Combat", { scene: "s1", active: true }]);
  assert.equal(r.combat.started, true);
  // A second call reuses the same combat and adds nobody twice.
  const again = await c.combatCreate({ tokenUuids: ["Token.t1"] });
  assert.equal(again.created, false);
  assert.equal(again.added, 0);
});

test("combatCreate refuses things that are not tokens", async () => {
  const { w, c } = setup();
  w.game.scenes.viewed = w.game.scenes[0];
  fakeCombat(w);
  await assert.rejects(c.combatCreate({ tokenUuids: ["Actor.a1"] }), /not a token/);
});

function withHp(actor, hp) {
  actor.system = { attributes: { hp: { ...hp } } };
  actor.update = async (data) => {
    for (const [k, v] of Object.entries(data)) actor.system.attributes.hp[k.split(".").pop()] = v;
  };
}

test("applyDamage uses the system's own damage rules when it has them", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 30, temp: 0, max: 40 });
  const seen = [];
  bob.applyDamage = async (rows, opts) => { seen.push([rows, opts]); bob.system.attributes.hp.value -= rows[0].value; };
  const r = await c.applyDamage({ uuid: "Actor.a1", amount: 7, type: "fire", multiplier: 0.5 });
  assert.deepEqual(seen[0], [[{ value: 7, type: "fire" }], { multiplier: 0.5 }]);
  assert.equal(r.before.value, 30);
  assert.equal(r.after.value, 23);
  await c.applyDamage({ uuid: "Actor.a1", amount: 3, mode: "heal" });
  assert.deepEqual(seen[1], [[{ value: 3, type: "healing" }], {}]);
});

test("applyDamage falls back to plain hit point math", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 10, temp: 4, max: 12 });
  let r = await c.applyDamage({ uuid: "Actor.a1", amount: 6 });
  assert.deepEqual(r.after, { value: 8, temp: 0, max: 12 });
  r = await c.applyDamage({ uuid: "Actor.a1", amount: 99 });
  assert.equal(r.after.value, 0);
  r = await c.applyDamage({ uuid: "Actor.a1", amount: 50, mode: "heal" });
  assert.equal(r.after.value, 12);
  r = await c.applyDamage({ uuid: "Actor.a1", amount: 5, mode: "temp" });
  assert.equal(r.after.temp, 5);
  r = await c.applyDamage({ uuid: "Actor.a1", amount: 2, mode: "temp" });
  assert.equal(r.after.temp, 5); // temporary hit points do not stack
});

test("applyDamage works from a token and complains clearly", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 10, temp: 0, max: 12 });
  w.makeDoc("Token", "t1", { name: "Bob", extra: { actor: bob } });
  const r = await c.applyDamage({ uuid: "Token.t1", amount: 4 });
  assert.equal(r.after.value, 6);
  await assert.rejects(c.applyDamage({ uuid: "Actor.a1", amount: -1 }), /zero or more/);
  await assert.rejects(c.applyDamage({ uuid: "Actor.a1", amount: 1, mode: "zap" }), /Unknown mode/);
  await assert.rejects(c.applyDamage({ uuid: "Actor.a2", amount: 1 }), /no hit points/);
  await assert.rejects(c.applyDamage({ uuid: "Scene.s1", amount: 1 }), /not an actor/);
});

// ----- rest -----

test("rest runs a long rest and reports hit points before and after", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 20, temp: 0, max: 40 });
  const seen = [];
  bob.longRest = async (opts) => { seen.push(opts); bob.system.attributes.hp.value = 40; return { rested: true }; };
  const r = await c.rest({ uuid: "Actor.a1" });
  assert.deepEqual(seen, [{ dialog: false, chat: true, newDay: true }]);
  assert.equal(r.type, "long");
  assert.equal(r.before.value, 20);
  assert.equal(r.after.value, 40);
});

test("rest can be short, works from a token, and explains problems", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 20, temp: 0, max: 40 });
  const seen = [];
  bob.shortRest = async (opts) => { seen.push(opts); return {}; };
  w.makeDoc("Token", "t1", { name: "Bob", extra: { actor: bob } });
  const r = await c.rest({ uuid: "Token.t1", type: "short" });
  assert.deepEqual(seen, [{ dialog: false, chat: true }]);
  assert.equal(r.type, "short");
  await assert.rejects(c.rest({ uuid: "Actor.a1", type: "nap" }), /Unknown rest type/);
  await assert.rejects(c.rest({}), /uuid is required/);
  await assert.rejects(c.rest({ uuid: "Scene.s1" }), /not an actor/);
  const foreman = w.docs.get("Actor.a2");
  withHp(foreman, { value: 5, temp: 0, max: 9 });
  await assert.rejects(c.rest({ uuid: "Actor.a2" }), /cannot take a long rest/);
  bob.longRest = async () => false;
  await assert.rejects(c.rest({ uuid: "Actor.a1" }), /could not rest/);
});

// ----- rest with hit dice -----

function withClass(actor, { denom = "d8", levels = 3, spent = 0, old = false } = {}) {
  actor.system.abilities = { con: { mod: 2 } };
  const item = {
    type: "class",
    system: old ? { levels, hitDice: denom, hitDiceUsed: spent } : { levels, hd: { denomination: denom, spent } },
    async update(data) {
      const [key, value] = Object.entries(data)[0];
      if (key === "system.hd.spent") item.system.hd.spent = value;
      else if (key === "system.hitDiceUsed") item.system.hitDiceUsed = value;
      else throw new Error(`unexpected update ${key}`);
    }
  };
  actor.items = [item];
  return item;
}

test("short rest can spend hit dice, heal, and stop at full hit points", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 20, temp: 0, max: 40 });
  bob.shortRest = async () => ({});
  const item = withClass(bob);
  // the fake roll is always 12 (before Con), so each die heals 12
  bob.update = async (data) => { bob.system.attributes.hp.value = data["system.attributes.hp.value"]; };
  const r = await c.rest({ uuid: "Actor.a1", type: "short", hitDice: 3 });
  assert.equal(r.hitDice.requested, 3);
  assert.equal(r.hitDice.spent, 2);
  assert.equal(r.hitDice.rolls[0].die, "d8");
  assert.equal(r.hitDice.rolls[1].healed, 8);
  assert.equal(r.hitDice.remaining, 1);
  assert.equal(item.system.hd.spent, 2);
  assert.equal(r.after.value, 40);
});

test("hit dice: older item fields work, the biggest die goes first, and used up dice stop it", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 1, temp: 0, max: 100 });
  bob.shortRest = async () => ({});
  bob.update = async (data) => { bob.system.attributes.hp.value = data["system.attributes.hp.value"]; };
  const small = withClass(bob, { denom: "d8", levels: 1, spent: 0, old: true });
  const big = withClass(bob, { denom: "d10", levels: 1, spent: 0 });
  bob.items = [small, big];
  const r = await c.rest({ uuid: "Actor.a1", type: "short", hitDice: 5 });
  assert.deepEqual(r.hitDice.rolls.map((x) => x.die), ["d10", "d8"]);
  assert.equal(r.hitDice.spent, 2);
  assert.equal(r.hitDice.remaining, 0);
  assert.equal(small.system.hitDiceUsed, 1);
});

test("hit dice: only on a short rest, sane numbers, and needs a class", async () => {
  const { w, c } = setup();
  const bob = w.docs.get("Actor.a1");
  withHp(bob, { value: 20, temp: 0, max: 40 });
  bob.shortRest = async () => ({});
  bob.longRest = async () => ({});
  await assert.rejects(c.rest({ uuid: "Actor.a1", type: "long", hitDice: 1 }), /only spent on a short rest/);
  await assert.rejects(c.rest({ uuid: "Actor.a1", type: "short", hitDice: -1 }), /whole number/);
  await assert.rejects(c.rest({ uuid: "Actor.a1", type: "short", hitDice: 99 }), /whole number/);
  bob.items = [];
  await assert.rejects(c.rest({ uuid: "Actor.a1", type: "short", hitDice: 1 }), /no class with hit dice/);
});

test("useItem does not ask for a template unless told to", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  const seen = [];
  item.use = async (config) => { seen.push(config.create.measuredTemplate); };
  await c.useItem({ uuid: "Item.i1" });
  await c.useItem({ uuid: "Item.i1", template: true });
  assert.deepEqual(seen, [false, true]);
});

test("useItem rolls a lone attack activity itself, with no Attack Roll box", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  const calls = [];
  const activity = {
    type: "attack",
    use: async (config, dialog) => { calls.push(["use", config.subsequentActions, dialog.configure]); return { message: { id: "m1" } }; },
    rollAttack: async (config, dialog, message) => { calls.push(["roll", dialog.configure, message.data.system.origin]); }
  };
  item.system = { activities: { contents: [activity], get: () => activity } };
  item.use = async () => { calls.push(["item.use"]); };
  await c.useItem({ uuid: "Item.i1" });
  assert.deepEqual(calls, [["use", false, false], ["roll", false, "m1"]]);
});

test("useItem leaves non-attack activities to the system", async () => {
  const { w, c } = setup();
  const item = w.docs.get("Item.i1");
  const calls = [];
  const activity = { type: "save", use: async (config) => { calls.push(config.subsequentActions); } };
  item.system = { activities: { contents: [activity], get: () => activity } };
  await c.useItem({ uuid: "Item.i1" });
  assert.deepEqual(calls, [undefined]);
});
