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

  const actorOf = (doc, uuid) => {
    const actor = doc.documentName === "Actor" ? doc : doc.actor;
    if (!actor) throw new Error(`${uuid} is not an actor or a token with an actor.`);
    return actor;
  };

  const rollFrom = (out) => {
    const first = Array.isArray(out) ? out[0] : out;
    if (first && first.total !== undefined) return first;
    return first?.rolls?.[0] ?? null;
  };

  const rollBrief = (roll) => roll ? {
    formula: roll.formula,
    total: roll.total,
    dice: (roll.dice ?? []).map((d) => ({ faces: d.faces, results: (d.results ?? []).map((r) => r.result) }))
  } : null;

  /** Match "dex", "Dexterity" or "Sleight of Hand" against a Foundry config table like CONFIG.DND5E.skills. */
  const resolveKey = (table, input, what) => {
    const text = String(input ?? "").trim();
    if (!table || typeof table !== "object") return text;
    const lower = text.toLowerCase();
    const label = (entry) => {
      const raw = typeof entry === "string" ? entry : entry?.label ?? "";
      return String(ctx.game?.i18n?.localize?.(raw) ?? raw).toLowerCase();
    };
    if (Object.hasOwn(table, text)) return text;
    const hit = Object.entries(table).find(([key, entry]) => key.toLowerCase() === lower || label(entry) === lower);
    if (!hit) throw new Error(`Unknown ${what} ${text}. Use one of: ${Object.keys(table).join(", ")}.`);
    return hit[0];
  };

  const setTargets = async (uuids) => {
    for (const t of [...(game.user.targets ?? [])]) t.setTarget(false, { releaseOthers: false, groupSelection: true });
    for (const targetUuid of uuids) {
      const tokenDoc = await find(targetUuid);
      const token = tokenDoc.object;
      if (!token) throw new Error(`${targetUuid} is not on the scene that is showing.`);
      token.setTarget(true, { releaseOthers: false, groupSelection: true });
    }
  };

  const sceneFor = (sceneId) => {
    const scene = sceneId ? game.scenes.get(sceneId) : (game.scenes.viewed ?? game.scenes.active);
    if (!scene) throw new Error(sceneId ? `No scene with id ${sceneId}.` : "No scene is showing.");
    return scene;
  };

  const placeToken = async (actor, { sceneId, x, y, hidden, name } = {}) => {
    const scene = sceneFor(sceneId);
    const data = await actor.getTokenDocument({ x: Number(x ?? 0), y: Number(y ?? 0), hidden: !!hidden, ...(name ? { name } : {}) });
    const made = await scene.createEmbeddedDocuments("Token", [data.toObject ? data.toObject() : data]);
    return { scene: brief(scene), tokens: made.map(brief) };
  };

  const plainText = (html) => String(html ?? "").replace(/<[^>]+>/g, "").trim();

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

    // ----- conditions -----

    async conditions({ uuid } = {}) {
      const actor = actorOf(await find(uuid), uuid);
      return { actor: brief(actor), conditions: [...(actor.statuses ?? [])] };
    },

    async condition({ uuid, condition, state } = {}) {
      need(condition, "condition");
      const how = state ?? "add";
      if (!["add", "remove", "toggle"].includes(how)) throw new Error(`Unknown state ${how}. Use add, remove or toggle.`);
      const actor = actorOf(await find(uuid), uuid);
      if (typeof actor.toggleStatusEffect !== "function") throw new Error(`${actor.name} cannot take conditions this way.`);
      const list = ctx.CONFIG?.statusEffects;
      let id = String(condition);
      if (Array.isArray(list) && list.length) {
        const lower = id.toLowerCase();
        const name = (e) => String(ctx.game?.i18n?.localize?.(e.name ?? e.label ?? "") ?? e.name ?? "").toLowerCase();
        const hit = list.find((e) => String(e.id).toLowerCase() === lower) ?? list.find((e) => name(e) === lower);
        if (!hit) throw new Error(`Unknown condition ${condition}. Use one of: ${list.map((e) => e.id).join(", ")}.`);
        id = hit.id;
      }
      const has = !!actor.statuses?.has?.(id);
      const want = how === "toggle" ? !has : how === "add";
      if (want !== has) await actor.toggleStatusEffect(id, { active: want });
      return { actor: brief(actor), condition: id, active: !!actor.statuses?.has?.(id), conditions: [...(actor.statuses ?? [])] };
    },

    // ----- death saves, saving throws, checks -----

    async deathSave({ uuid } = {}) {
      const actor = actorOf(await find(uuid), uuid);
      if (typeof actor.rollDeathSave !== "function") throw new Error(`${actor.name} cannot roll a death save. This needs the D&D 5e system.`);
      const roll = rollFrom(await actor.rollDeathSave({}, { configure: false }, { create: true }));
      const death = actor.system?.attributes?.death ?? {};
      return { actor: brief(actor), roll: rollBrief(roll), successes: death.success ?? 0, failures: death.failure ?? 0, hp: hpOf(actor) };
    },

    async check({ uuid, kind, key, dc, advantage, disadvantage } = {}) {
      need(key, "key");
      const what = kind ?? "ability";
      if (!["save", "ability", "skill"].includes(what)) throw new Error(`Unknown kind ${what}. Use save, ability or skill.`);
      const actor = actorOf(await find(uuid), uuid);
      const dnd = ctx.CONFIG?.DND5E;
      const config = {};
      let method;
      if (what === "skill") {
        config.skill = resolveKey(dnd?.skills, key, "skill");
        method = "rollSkill";
      } else {
        config.ability = resolveKey(dnd?.abilities, key, "ability");
        method = what === "save" ? "rollSavingThrow" : (typeof actor.rollAbilityCheck === "function" ? "rollAbilityCheck" : "rollAbilityTest");
      }
      if (advantage && disadvantage) throw new Error("Pick advantage or disadvantage, not both.");
      if (advantage) config.advantage = true;
      if (disadvantage) config.disadvantage = true;
      if (typeof actor[method] !== "function") throw new Error(`${actor.name} cannot roll that. This needs a recent D&D 5e system.`);
      const roll = rollFrom(await actor[method](config, { configure: false }, { create: true }));
      if (!roll) throw new Error(`${actor.name}'s roll was cancelled.`);
      const out = { actor: brief(actor), kind: what, key: config.skill ?? config.ability, roll: rollBrief(roll) };
      if (dc !== undefined && dc !== null && dc !== "") {
        out.dc = Number(dc);
        out.success = roll.total >= Number(dc);
      }
      return out;
    },

    // ----- spell slots, item uses, quantities -----

    async resources({ uuid } = {}) {
      const actor = actorOf(await find(uuid), uuid);
      const spells = actor.system?.spells ?? {};
      const slots = Object.entries(spells)
        .filter(([k]) => /^spell\d+$/.test(k) || k === "pact")
        .map(([k, v]) => ({ key: k, level: k === "pact" ? (v.level ?? null) : Number(k.slice(5)), value: Number(v.value ?? 0), max: Number(v.max ?? 0) }))
        .filter((x) => x.max > 0);
      const items = [...(actor.items ?? [])];
      const uses = items
        .filter((i) => Number(i.system?.uses?.max) > 0)
        .map((i) => ({ id: i.id, uuid: i.uuid, name: i.name, spent: Number(i.system.uses.spent ?? 0), max: Number(i.system.uses.max), left: Number(i.system.uses.max) - Number(i.system.uses.spent ?? 0) }));
      const quantities = items
        .filter((i) => i.type === "consumable" && Number.isFinite(Number(i.system?.quantity)))
        .map((i) => ({ id: i.id, uuid: i.uuid, name: i.name, quantity: Number(i.system.quantity) }));
      return { actor: brief(actor), slots, uses, quantities };
    },

    async resource({ uuid, target, level, itemUuid, mode, amount } = {}) {
      const kind = target ?? "slot";
      if (!["slot", "uses", "quantity"].includes(kind)) throw new Error(`Unknown target ${kind}. Use slot, uses or quantity.`);
      const how = mode ?? "spend";
      if (!["spend", "restore", "set"].includes(how)) throw new Error(`Unknown mode ${how}. Use spend, restore or set.`);
      const n = amount === undefined || amount === null ? 1 : Number(amount);
      if (!Number.isInteger(n) || n < 0 || n > 1000) throw new Error("amount must be a whole number, 0 or more.");
      if (kind === "slot") {
        const actor = actorOf(await find(uuid), uuid);
        need(level, "level");
        const key = String(level).toLowerCase() === "pact" ? "pact" : `spell${Number(level)}`;
        const slot = actor.system?.spells?.[key];
        if (!slot || !(Number(slot.max) > 0)) throw new Error(`${actor.name} has no ${key === "pact" ? "pact" : `level ${level}`} spell slots.`);
        const before = Number(slot.value ?? 0);
        const max = Number(slot.max);
        let after = how === "spend" ? before - n : how === "restore" ? Math.min(max, before + n) : Math.min(max, n);
        if (after < 0) throw new Error(`${actor.name} has only ${before} ${key === "pact" ? "pact" : `level ${level}`} slots left.`);
        await actor.update({ [`system.spells.${key}.value`]: after });
        return { actor: brief(actor), target: "slot", key, before, after, max };
      }
      const item = await find(itemUuid);
      if (item.documentName !== "Item") throw new Error(`${itemUuid} is not an item.`);
      if (kind === "uses") {
        const uses = item.system?.uses;
        const max = Number(uses?.max);
        if (!(max > 0)) throw new Error(`${item.name} has no limited uses.`);
        const spent = Number(uses.spent ?? 0);
        const left = max - spent;
        const wanted = how === "spend" ? left - n : how === "restore" ? Math.min(max, left + n) : Math.min(max, n);
        if (wanted < 0) throw new Error(`${item.name} has only ${left} uses left.`);
        await item.update({ "system.uses.spent": max - wanted });
        return { item: brief(item), target: "uses", before: left, after: wanted, max };
      }
      const before = Number(item.system?.quantity);
      if (!Number.isFinite(before)) throw new Error(`${item.name} has no quantity.`);
      const after = how === "spend" ? before - n : how === "restore" ? before + n : n;
      if (after < 0) throw new Error(`There are only ${before} of ${item.name}.`);
      await item.update({ "system.quantity": after });
      return { item: brief(item), target: "quantity", before, after };
    },

    // ----- what just happened -----

    async lastAttack({ alias, limit } = {}) {
      const messages = game.messages.contents.slice(-clamp(limit, 60, 200));
      const who = String(alias ?? "").toLowerCase();
      let start = -1;
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (!/attack roll/i.test(m.flavor ?? "")) continue;
        if (who && !String(m.speaker?.alias ?? "").toLowerCase().includes(who)) continue;
        start = i;
        break;
      }
      if (start < 0) throw new Error(who ? `No recent attack roll from ${alias}.` : "No recent attack roll in chat.");
      const attackMsg = messages[start];
      const out = {
        attacker: attackMsg.speaker?.alias ?? null,
        weapon: String(attackMsg.flavor ?? "").replace(/\s*-\s*Attack Roll.*/i, "") || null,
        attack: rollBrief(attackMsg.rolls?.[0]),
        outcome: null, target: null, ac: null, damage: null
      };
      for (const m of messages.slice(start + 1)) {
        if (/attack roll/i.test(m.flavor ?? "")) break;
        const text = plainText(m.content);
        const hit = text.match(/(critical hit|critical miss|hit|miss)\s+on\s+(.+?)\s+\((\d+)\s+vs\s+AC\s+(\d+)\)/i);
        if (hit && !out.outcome) {
          out.outcome = hit[1].toLowerCase();
          out.target = hit[2];
          out.ac = Number(hit[4]);
        }
        if (/damage roll/i.test(m.flavor ?? "") && !out.damage) {
          out.damage = { ...rollBrief(m.rolls?.[0]), flavor: m.flavor };
        }
      }
      out.pending = out.outcome !== null && /hit/.test(out.outcome) && out.damage === null;
      return out;
    },

    // ----- targeting and tokens -----

    async target({ uuids } = {}) {
      const list = Array.isArray(uuids) ? uuids : [];
      await setTargets(list);
      return { targets: list };
    },

    async tokenCreate({ actorUuid, sceneId, x, y, hidden, name } = {}) {
      const actor = actorOf(await find(actorUuid), actorUuid);
      const placed = await placeToken(actor, { sceneId, x, y, hidden, name });
      return { actor: brief(actor), ...placed };
    },

    async tokenSet({ uuid, hidden, rotation, elevation, x, y } = {}) {
      const token = await find(uuid);
      if (token.documentName !== "Token") throw new Error(`${uuid} is not a token.`);
      const data = {};
      if (hidden !== undefined && hidden !== null) data.hidden = !!hidden;
      if (rotation !== undefined && rotation !== null) data.rotation = Number(rotation);
      if (elevation !== undefined && elevation !== null) data.elevation = Number(elevation);
      if (x !== undefined && x !== null) data.x = Number(x);
      if (y !== undefined && y !== null) data.y = Number(y);
      if (!Object.keys(data).length) throw new Error("Nothing to change. Give hidden, rotation, elevation, x or y.");
      await token.update(data);
      return { ...brief(token), updated: data };
    },

    // ----- journals and tables -----

    async journal({ uuid, name, pages, content, folder } = {}) {
      const list = Array.isArray(pages) && pages.length ? pages : [{ name, text: content ?? "" }];
      const pageData = list.map((p) => {
        const title = p.name ?? name;
        need(title, "page name");
        return { name: String(title), type: "text", text: { content: String(p.text ?? p.content ?? ""), format: 1 } };
      });
      if (uuid) {
        const entry = await find(uuid);
        if (entry.documentName !== "JournalEntry") throw new Error(`${uuid} is not a journal entry.`);
        const made = await entry.createEmbeddedDocuments("JournalEntryPage", pageData);
        return { entry: brief(entry), addedPages: made.map(brief) };
      }
      need(name, "name");
      const data = { name: String(name), pages: pageData };
      if (folder) data.folder = folder;
      const made = await docClass("JournalEntry").create(data);
      return { created: brief(made), pages: pageData.length };
    },

    async tableRoll({ uuid, name, chat } = {}) {
      let table = null;
      if (uuid) table = await find(uuid);
      else if (name) table = game.collections.get("RollTable")?.contents.find((t) => t.name === name);
      if (!table || table.documentName !== "RollTable") throw new Error(uuid ? `${uuid} is not a rollable table.` : `No rollable table called ${name}.`);
      const draw = await table.draw({ displayChat: chat !== false });
      return {
        table: brief(table),
        roll: rollBrief(draw.roll),
        results: (draw.results ?? []).map((r) => ({ text: r.description ?? r.text ?? r.name ?? "", documentUuid: r.documentUuid ?? null, range: r.range ?? null }))
      };
    },

    // ----- compendiums -----

    async packs({ type, q } = {}) {
      const needle = String(q ?? "").trim().toLowerCase();
      return [...(game.packs?.contents ?? [])]
        .filter((p) => (!type || p.documentName === type) && (!needle || `${p.title} ${p.collection}`.toLowerCase().includes(needle)))
        .map((p) => ({ id: p.collection, label: p.title, type: p.documentName, count: p.index?.size ?? null, package: p.metadata?.packageName ?? null }));
    },

    async packIndex({ pack, q, limit } = {}) {
      need(pack, "pack");
      const p = game.packs?.get(pack);
      if (!p) throw new Error(`No compendium called ${pack}. List them with packs.`);
      const index = await p.getIndex();
      const needle = String(q ?? "").trim().toLowerCase();
      const all = [...index].filter((e) => !needle || String(e.name ?? "").toLowerCase().includes(needle));
      const max = clamp(limit, 25, 200);
      return {
        pack, total: all.length, returned: Math.min(all.length, max),
        results: all.slice(0, max).map((e) => ({ id: e._id, uuid: e.uuid ?? `Compendium.${pack}.${p.documentName}.${e._id}`, name: e.name, type: e.type ?? null }))
      };
    },

    async importFromPack({ pack, id, ids, name, folder, place, sceneId, x, y, hidden, actorUuid } = {}) {
      need(pack, "pack");
      const wanted = Array.isArray(ids) && ids.length ? ids.map(String) : [];
      if (id) wanted.unshift(String(id));
      if (!wanted.length) throw new Error("id is required.");
      const p = game.packs?.get(pack);
      if (!p) throw new Error(`No compendium called ${pack}. List them with packs.`);
      if (!ALLOWED.includes(p.documentName)) throw new Error(`${p.documentName} documents are not allowed through the relay.`);
      if (actorUuid) {
        // Copy Item entries (spells, features, gear, class) straight onto an actor.
        if (p.documentName !== "Item") throw new Error(`${pack} holds ${p.documentName} entries. Only Item compendiums can add to an actor.`);
        if (wanted.length > 30) throw new Error("Add 30 items or fewer at a time.");
        const actor = allowed(await find(actorUuid));
        if (actor.documentName !== "Actor") throw new Error(`${actorUuid} is not an actor.`);
        const worldItems = game.collections.get("Item");
        const rows = [];
        for (const one of wanted) {
          const source = await p.getDocument(one);
          if (!source) throw new Error(`Nothing with id ${one} in ${pack}. Nothing was added.`);
          const data = worldItems?.fromCompendium ? worldItems.fromCompendium(source) : source.toObject();
          delete data._id;
          if (name && wanted.length === 1) data.name = name;
          rows.push(data);
        }
        const created = await actor.createEmbeddedDocuments("Item", rows);
        return { actor: brief(actor), added: created.map(brief) };
      }
      if (wanted.length > 1) throw new Error("Give one id at a time, unless you also give an actor to add to.");
      id = wanted[0];
      const world = game.collections.get(p.documentName);
      if (!world?.importFromCompendium) throw new Error(`Cannot import ${p.documentName} documents.`);
      const doc = await world.importFromCompendium(p, id, { ...(name ? { name } : {}), ...(folder ? { folder } : {}) }, {});
      if (!doc) throw new Error(`Nothing with id ${id} in ${pack}.`);
      const out = { imported: brief(doc) };
      if (place) {
        if (doc.documentName !== "Actor") throw new Error("Only actors can be placed on a scene.");
        Object.assign(out, await placeToken(doc, { sceneId, x, y, hidden }));
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
