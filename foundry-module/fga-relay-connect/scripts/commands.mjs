/**
 * What the relay can ask Foundry to do.
 * Everything Foundry-specific comes in through `ctx`, so tests can pass a fake one.
 */

/** Documents we allow the relay to list, read, change, make or delete. Never User or Setting. */
export const ALLOWED = [
  "Actor", "Item", "Scene", "JournalEntry", "Macro", "RollTable", "Playlist", "Folder",
  "Combat", "Combatant", "ActiveEffect", "Token", "ChatMessage"
];

const COLLECTIONS = ["Actor", "Item", "Scene", "JournalEntry", "Macro", "RollTable", "Playlist", "Folder", "Combat"];


const FILE_SOURCES = ["data", "public"];
const MAX_FILE_BYTES = 8 * 1024 * 1024;

/** Refuse paths that climb out of the folder or point somewhere else. */
export function cleanPath(path, allowEmpty = false) {
  const text = String(path ?? "");
  let decoded = text;
  try { decoded = decodeURIComponent(text); } catch { /* keep the raw text */ }
  if (!text && allowEmpty) return text;
  if (!text) throw new Error("path is required");
  if (decoded.split(/[\\/]/).includes("..") || decoded.startsWith("/") || decoded.startsWith("\\") || /^[a-z][a-z0-9+.-]*:/i.test(decoded)) {
    throw new Error("That path is not allowed. Use a path inside the Foundry Data folder, like modules/my-module/module.json.");
  }
  return text;
}

function toBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

const plain = (value) => JSON.parse(JSON.stringify(value ?? null));

function need(value, name) {
  if (value === undefined || value === null || value === "") throw new Error(`${name} is required`);
  return value;
}

function clamp(value, fallback, max) {
  const n = Number.isFinite(Number(value)) ? Math.floor(Number(value)) : fallback;
  return Math.max(1, Math.min(max, n));
}

export function makeCommands(ctx) {
  const { game, fromUuid } = ctx;

  async function find(uuid) {
    need(uuid, "uuid");
    const doc = await fromUuid(uuid);
    if (!doc) throw new Error(`Nothing found for ${uuid}`);
    return doc;
  }

  function allowed(doc) {
    const name = doc.documentName;
    if (!ALLOWED.includes(name)) throw new Error(`${name} documents are not allowed through the relay.`);
    return doc;
  }

  function docClass(type) {
    need(type, "documentType");
    if (!ALLOWED.includes(type)) throw new Error(`${type} documents are not allowed through the relay.`);
    const cls = ctx.getDocumentClass?.(type) ?? ctx.CONFIG?.[type]?.documentClass;
    if (!cls) throw new Error(`Foundry has no document type called ${type}.`);
    return cls;
  }

  const brief = (doc) => ({ id: doc.id, uuid: doc.uuid, name: doc.name, documentName: doc.documentName });

  const combatBrief = (c) => ({
    id: c.id,
    uuid: c.uuid,
    round: c.round,
    turn: c.turn,
    started: !!c.started,
    active: !!c.active,
    sceneId: c.scene?.id ?? c.sceneId ?? null,
    combatants: c.combatants.contents.map((x) => ({
      id: x.id,
      uuid: x.uuid,
      name: x.name,
      actorId: x.actorId ?? null,
      tokenId: x.tokenId ?? null,
      initiative: x.initiative ?? null,
      defeated: !!x.defeated,
      hidden: !!x.hidden
    }))
  });

  function pickCombat(combatId) {
    const combat = combatId
      ? game.combats.get(combatId)
      : (game.combats.active ?? game.combats.contents[0]);
    if (!combat) throw new Error(combatId ? `No combat with id ${combatId}.` : "There is no combat. Start one first.");
    return combat;
  }

  // Spend hit dice like a player would: biggest die first, roll it, add Con, heal. Stops at full hit points.
  const spendHitDice = async (actor, count) => {
    const conMod = actor.system?.abilities?.con?.mod ?? 0;
    const classes = [...(actor.items ?? [])]
      .filter((i) => i.type === "class")
      .map((item) => {
        const newStyle = item.system?.hd !== undefined && item.system.hd !== null;
        return {
          item,
          denom: newStyle ? item.system.hd.denomination : item.system?.hitDice,
          spent: newStyle ? (item.system.hd.spent ?? 0) : (item.system?.hitDiceUsed ?? 0),
          levels: item.system?.levels ?? 0,
          path: newStyle ? "system.hd.spent" : "system.hitDiceUsed"
        };
      })
      .filter((c) => /^d\d+$/.test(String(c.denom ?? "")))
      .sort((a, b) => Number(b.denom.slice(1)) - Number(a.denom.slice(1)));
    if (!classes.length) throw new Error(`${actor.name} has no class with hit dice.`);
    const rolls = [];
    for (let n = 0; n < count; n++) {
      const now = hpOf(actor);
      if (now.max && now.value >= now.max) break;
      const pick = classes.find((c) => c.spent < c.levels);
      if (!pick) break;
      const roll = new ctx.Roll(`1${pick.denom} + ${conMod}`);
      await roll.evaluate();
      if (ctx.ChatMessage?.getSpeaker) await roll.toMessage({ speaker: ctx.ChatMessage.getSpeaker({ actor }) }, { flavor: `${actor.name} spends a ${pick.denom} Hit Die` });
      const gain = Math.max(0, roll.total);
      await actor.update({ "system.attributes.hp.value": Math.min(now.max || Infinity, now.value + gain) });
      pick.spent += 1;
      await pick.item.update({ [pick.path]: pick.spent });
      rolls.push({ die: pick.denom, total: roll.total, healed: Math.min(gain, (now.max || Infinity) - now.value) });
    }
    const left = classes.reduce((sum, c) => sum + Math.max(0, c.levels - c.spent), 0);
    return { requested: count, spent: rolls.length, rolls, remaining: left };
  };

  const hpOf = (actor) => {
    const hp = actor.system?.attributes?.hp;
    if (!hp) throw new Error(`${actor.name} has no hit points to change.`);
    return { value: Number(hp.value ?? 0), temp: Number(hp.temp ?? 0), max: Number(hp.effectiveMax ?? hp.max ?? 0) };
  };

  const commands = {
    async ping() {
      return { pong: true, time: Date.now() };
    },

    async world() {
      const scene = game.scenes?.active;
      return {
        id: game.world.id,
        title: game.world.title,
        foundryVersion: game.version,
        system: { id: game.system.id, version: game.system.version },
        user: { id: game.userId, name: game.user?.name, isGM: !!game.user?.isGM },
        activeScene: scene ? { id: scene.id, name: scene.name } : null,
        counts: Object.fromEntries(COLLECTIONS.map((t) => [t, game.collections?.get(t)?.size ?? 0]))
      };
    },

    async list({ documentType, q, limit } = {}) {
      need(documentType, "documentType");
      if (!COLLECTIONS.includes(documentType)) {
        throw new Error(`Cannot list ${documentType}. Try one of: ${COLLECTIONS.join(", ")}.`);
      }
      const collection = game.collections.get(documentType);
      if (!collection) throw new Error(`Foundry has no collection for ${documentType}.`);
      const needle = String(q ?? "").trim().toLowerCase();
      const all = collection.contents.filter((d) => !needle || String(d.name ?? "").toLowerCase().includes(needle));
      const max = clamp(limit, 50, 500);
      return {
        total: all.length,
        returned: Math.min(all.length, max),
        results: all.slice(0, max).map((d) => ({ ...brief(d), type: d.type ?? null, folder: d.folder?.name ?? null }))
      };
    },

    async get({ uuid, source } = {}) {
      const doc = allowed(await find(uuid));
      // source=false gives the prepared data, with armor class and other derived values.
      return { ...brief(doc), data: plain(doc.toObject(source === true)) };
    },

    async chat({ limit } = {}) {
      const max = clamp(limit, 20, 200);
      const messages = game.messages.contents.slice(-max);
      return messages.map((m) => ({
        id: m.id,
        uuid: m.uuid,
        timestamp: m.timestamp,
        author: m.author?.name ?? null,
        alias: m.speaker?.alias ?? null,
        whisper: m.whisper ?? [],
        content: m.content,
        rolls: (m.rolls ?? []).map((r) => ({ formula: r.formula, total: r.total })),
        flavor: m.flavor ?? null
      }));
    },

    async encounters() {
      return game.combats.contents.map(combatBrief);
    },

    async effects({ uuid } = {}) {
      const doc = await find(uuid);
      const actor = doc.documentName === "Actor" ? doc : doc.actor;
      if (!actor) throw new Error(`${uuid} is not an actor or a token with an actor.`);
      return {
        actor: brief(actor),
        effects: actor.effects.contents.map((e) => ({
          id: e.id,
          uuid: e.uuid,
          name: e.name,
          disabled: !!e.disabled,
          statuses: [...(e.statuses ?? [])],
          duration: plain(e.duration ?? null)
        }))
      };
    },

    async scene({ id, name, active, viewed } = {}) {
      let scene = null;
      if (id) scene = game.scenes.get(id);
      else if (name) scene = game.scenes.contents.find((s) => s.name === name);
      else if (viewed) scene = game.scenes.viewed;
      else scene = game.scenes.active;
      if (!scene) throw new Error("No matching scene.");
      return { ...brief(scene), data: plain(scene.toObject()) };
    },

    async users() {
      return game.users.contents.map((u) => ({
        id: u.id,
        name: u.name,
        role: u.role,
        isGM: !!u.isGM,
        active: !!u.active,
        characterId: u.character?.id ?? null
      }));
    },

    async roll({ formula, flavor, chat = true, whisper } = {}) {
      need(formula, "formula");
      const roll = new ctx.Roll(String(formula));
      await roll.evaluate();
      if (chat) {
        const options = { flavor };
        if (Array.isArray(whisper) && whisper.length) options.rollMode = "gmroll";
        await roll.toMessage({}, options);
      }
      return {
        formula: roll.formula,
        total: roll.total,
        dice: (roll.dice ?? []).map((d) => ({ faces: d.faces, results: d.results.map((r) => r.result) }))
      };
    },

    async sendChat({ content, actorId, alias, whisper, flavor } = {}) {
      need(content, "content");
      const data = { content: String(content) };
      if (flavor) data.flavor = String(flavor);
      if (actorId) {
        const actor = game.actors.get(actorId);
        if (!actor) throw new Error(`No actor with id ${actorId}`);
        data.speaker = ctx.ChatMessage.getSpeaker({ actor });
      } else if (alias) {
        data.speaker = { alias: String(alias) };
      }
      if (Array.isArray(whisper) && whisper.length) data.whisper = whisper;
      const message = await ctx.ChatMessage.create(data);
      return { id: message?.id ?? null };
    },

    async update({ uuid, data, options } = {}) {
      need(data, "data");
      const doc = allowed(await find(uuid));
      await doc.update(data, options ?? {});
      return { ...brief(doc), updated: Object.keys(data) };
    },

    async create({ documentType, data, parentUuid, options } = {}) {
      need(data, "data");
      const cls = docClass(documentType);
      const parent = parentUuid ? allowed(await find(parentUuid)) : null;
      const opts = { ...(options ?? {}) };
      if (parent) opts.parent = parent;
      const made = await cls.create(data, opts);
      const list = Array.isArray(made) ? made : [made];
      return { created: list.map(brief) };
    },

    async delete({ uuid, options } = {}) {
      const doc = allowed(await find(uuid));
      const info = brief(doc);
      await doc.delete(options ?? {});
      return { deleted: info };
    },

    async useItem({ uuid, targets, activityId } = {}) {
      const item = await find(uuid);
      if (item.documentName !== "Item") throw new Error(`${uuid} is not an item.`);
      if (Array.isArray(targets)) {
        for (const t of [...(game.user.targets ?? [])]) t.setTarget(false, { releaseOthers: false, groupSelection: true });
        for (const targetUuid of targets) {
          const tokenDoc = await find(targetUuid);
          const token = tokenDoc.object;
          if (!token) throw new Error(`${targetUuid} is not on the scene that is showing.`);
          token.setTarget(true, { releaseOthers: false, groupSelection: true });
        }
      }
      if (activityId) {
        const activity = item.system?.activities?.get?.(activityId);
        if (!activity) throw new Error(`No activity ${activityId} on ${item.name}.`);
        await activity.use({}, { configure: false }, {});
      } else {
        await item.use({}, { configure: false });
      }
      return { used: brief(item), targets: targets ?? [] };
    },

    async moveToken({ uuid, x, y } = {}) {
      need(x, "x");
      need(y, "y");
      const token = await find(uuid);
      if (token.documentName !== "Token") throw new Error(`${uuid} is not a token.`);
      await token.update({ x: Number(x), y: Number(y) });
      return { ...brief(token), x: Number(x), y: Number(y) };
    },

    async switchScene({ id, name, activate } = {}) {
      const scene = id ? game.scenes.get(id) : game.scenes.contents.find((s) => s.name === name);
      if (!scene) throw new Error("No matching scene.");
      if (activate) await scene.activate();
      else await scene.view();
      return { ...brief(scene), activated: !!activate };
    },

    async combatCreate({ sceneId, tokenUuids, rollInitiative, start } = {}) {
      const scene = sceneId ? game.scenes.get(sceneId) : (game.scenes.viewed ?? game.scenes.active);
      if (!scene) throw new Error(sceneId ? `No scene with id ${sceneId}.` : "No scene is showing.");
      let combat = game.combats.contents.find((c) => (c.scene?.id ?? c.sceneId) === scene.id);
      const madeNew = !combat;
      if (!combat) combat = await docClass("Combat").create({ scene: scene.id, active: true });
      const have = new Set(combat.combatants.contents.map((x) => x.tokenId));
      const rows = [];
      for (const uuid of tokenUuids ?? []) {
        const token = await find(uuid);
        if (token.documentName !== "Token") throw new Error(`${uuid} is not a token.`);
        if (have.has(token.id)) continue;
        have.add(token.id);
        rows.push({ tokenId: token.id, sceneId: scene.id, actorId: token.actorId ?? token.actor?.id ?? null, hidden: !!token.hidden });
      }
      if (rows.length) await combat.createEmbeddedDocuments("Combatant", rows);
      if (rollInitiative) await combat.rollAll();
      if (start) await combat.startCombat();
      return { created: madeNew, added: rows.length, combat: combatBrief(combat) };
    },

    async combatControl({ action, combatId } = {}) {
      need(action, "action");
      const methods = {
        start: "startCombat", nextTurn: "nextTurn", previousTurn: "previousTurn", nextRound: "nextRound",
        previousRound: "previousRound", rollAll: "rollAll", rollNpc: "rollNPC", end: "endCombat"
      };
      const method = methods[action];
      if (!method) throw new Error(`Unknown combat action ${action}. Use one of: ${Object.keys(methods).join(", ")}.`);
      const combat = pickCombat(combatId);
      if (typeof combat[method] !== "function") throw new Error(`This Foundry cannot do ${action}.`);
      const ended = { id: combat.id, uuid: combat.uuid };
      await combat[method]();
      return action === "end" ? { ended } : { action, combat: combatBrief(combat) };
    },

    async applyDamage({ uuid, amount, mode, type, multiplier } = {}) {
      need(uuid, "uuid");
      const n = Number(need(amount, "amount"));
      if (!Number.isFinite(n) || n < 0) throw new Error("amount must be a number that is zero or more.");
      const how = mode ?? "damage";
      if (!["damage", "heal", "temp"].includes(how)) throw new Error(`Unknown mode ${how}. Use damage, heal or temp.`);
      const doc = await find(uuid);
      const actor = doc.documentName === "Actor" ? doc : doc.actor;
      if (!actor) throw new Error(`${uuid} is not an actor or a token with an actor.`);
      const before = hpOf(actor);
      const options = multiplier !== undefined && multiplier !== null ? { multiplier: Number(multiplier) } : {};
      if (how === "temp") {
        await actor.update({ "system.attributes.hp.temp": Math.max(before.temp, Math.floor(n)) });
      } else if (typeof actor.applyDamage === "function") {
        // dnd5e handles resistances, immunities and temporary hit points for us.
        const row = how === "heal" ? { value: n, type: "healing" } : (type ? { value: n, type: String(type) } : { value: n });
        await actor.applyDamage([row], options);
      } else if (how === "damage") {
        const amountIn = Math.floor(n * (options.multiplier ?? 1));
        const soaked = Math.min(before.temp, amountIn);
        await actor.update({
          "system.attributes.hp.temp": before.temp - soaked,
          "system.attributes.hp.value": Math.max(0, before.value - (amountIn - soaked))
        });
      } else {
        const healed = Math.floor(n * (options.multiplier ?? 1));
        await actor.update({ "system.attributes.hp.value": Math.min(before.max || Infinity, before.value + healed) });
      }
      return { actor: brief(actor), mode: how, amount: n, before, after: hpOf(actor) };
    },

    async rest({ uuid, type, hitDice } = {}) {
      need(uuid, "uuid");
      const kind = type ?? "long";
      const dice = hitDice === undefined || hitDice === null ? 0 : Number(hitDice);
      if (!Number.isInteger(dice) || dice < 0 || dice > 20) throw new Error("hitDice must be a whole number from 0 to 20.");
      if (dice > 0 && kind !== "short") throw new Error("Hit dice are only spent on a short rest.");
      if (!["long", "short"].includes(kind)) throw new Error(`Unknown rest type ${kind}. Use long or short.`);
      const doc = await find(uuid);
      const actor = doc.documentName === "Actor" ? doc : doc.actor;
      if (!actor) throw new Error(`${uuid} is not an actor or a token with an actor.`);
      const method = kind === "long" ? "longRest" : "shortRest";
      if (typeof actor[method] !== "function") throw new Error(`${actor.name} cannot take a ${kind} rest. This needs the D&D 5e system.`);
      const before = hpOf(actor);
      // dialog:false rests straight away. The system posts its own rest message to chat.
      const result = await actor[method]({ dialog: false, chat: true, ...(kind === "long" ? { newDay: true } : {}) });
      if (result === false || result === null) throw new Error(`${actor.name} could not rest. Foundry or the system stopped it.`);
      const out = { actor: brief(actor), type: kind, before, after: hpOf(actor) };
      if (dice > 0) {
        out.hitDice = await spendHitDice(actor, dice);
        out.after = hpOf(actor);
      }
      return out;
    },

    async listFiles({ path, source } = {}) {
      const where = source ?? "data";
      if (!FILE_SOURCES.includes(where)) throw new Error(`Cannot browse ${where}. Try one of: ${FILE_SOURCES.join(", ")}.`);
      cleanPath(path ?? "", true);
      const result = await ctx.FilePicker.browse(where, path ?? "");
      return { path: result.target ?? path ?? "", source: where, dirs: result.dirs ?? [], files: result.files ?? [] };
    },

    async readFile({ path, source } = {}) {
      need(path, "path");
      const where = source ?? "data";
      if (!FILE_SOURCES.includes(where)) throw new Error(`Cannot read from ${where}. Try one of: ${FILE_SOURCES.join(", ")}.`);
      cleanPath(path);
      const response = await ctx.fetch(ctx.getRoute(path));
      if (!response.ok) throw new Error(`Could not read ${path} (status ${response.status}).`);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > MAX_FILE_BYTES) {
        throw new Error(`${path} is ${buffer.byteLength} bytes. The limit is ${MAX_FILE_BYTES}.`);
      }
      return {
        path,
        size: buffer.byteLength,
        mimeType: response.headers?.get?.("content-type") ?? "application/octet-stream",
        base64: toBase64(new Uint8Array(buffer))
      };
    }
  };

  return commands;
}
