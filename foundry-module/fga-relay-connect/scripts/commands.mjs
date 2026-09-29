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
      return game.combats.contents.map((c) => ({
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
      }));
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

    async sendChat({ content, actorId, alias, whisper } = {}) {
      need(content, "content");
      const data = { content: String(content) };
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
    }
  };

  return commands;
}
