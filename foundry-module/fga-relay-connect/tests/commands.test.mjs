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
