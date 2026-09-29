import { RelayLink } from "./link.mjs";

const ID = "fga-relay-connect";

/** Commands the relay can ask for. More arrive in later versions. */
const commands = {
  async ping() {
    return { pong: true, time: Date.now() };
  }
};

function hello() {
  return {
    clientId: game.userId ? `${game.world.id}:${game.userId}` : game.world.id,
    worldId: game.world.id,
    worldTitle: game.world.title,
    foundryVersion: game.version,
    systemId: game.system.id,
    systemVersion: game.system.version,
    userName: game.user?.name,
    isGM: !!game.user?.isGM,
    moduleVersion: game.modules.get(ID)?.version
  };
}

const MESSAGES = {
  connected: "FGA_RELAY.Status.Connected",
  connecting: "FGA_RELAY.Status.Connecting",
  off: "FGA_RELAY.Status.Off",
  "no-settings": "FGA_RELAY.Status.NoSettings",
  "bad-key": "FGA_RELAY.Status.BadKey",
  replaced: "FGA_RELAY.Status.Replaced"
};

let lastState = null;
let link = null;

function onState(state) {
  if (state === lastState) return;
  lastState = state;
  const text = game.i18n.localize(MESSAGES[state] ?? MESSAGES.off);
  console.log(`${ID} | ${text}`);
  // Only nag the GM about problems and the first successful connection.
  if (["connected", "no-settings", "bad-key", "replaced"].includes(state)) {
    const level = state === "connected" ? "info" : "warn";
    ui.notifications?.[level](text);
  }
  game.modules.get(ID).api.state = state;
}

Hooks.once("init", () => {
  game.settings.register(ID, "enabled", {
    name: "FGA_RELAY.Enabled.Name",
    hint: "FGA_RELAY.Enabled.Hint",
    scope: "client",
    config: true,
    type: Boolean,
    default: false,
    onChange: (on) => (on ? link?.start() : link?.stop())
  });
  game.settings.register(ID, "url", {
    name: "FGA_RELAY.Url.Name",
    hint: "FGA_RELAY.Url.Hint",
    scope: "client",
    config: true,
    type: String,
    default: "",
    onChange: () => game.settings.get(ID, "enabled") && (link.stop(), link.start())
  });
  game.settings.register(ID, "key", {
    name: "FGA_RELAY.Key.Name",
    hint: "FGA_RELAY.Key.Hint",
    scope: "client",
    config: true,
    type: String,
    default: "",
    onChange: () => game.settings.get(ID, "enabled") && (link.stop(), link.start())
  });
  game.modules.get(ID).api = { state: "off", commands };
});

Hooks.once("ready", () => {
  link = new RelayLink({
    getSettings: () => ({ url: game.settings.get(ID, "url"), key: game.settings.get(ID, "key") }),
    hello,
    handle: async (type, data) => {
      const fn = commands[type];
      if (!fn) throw new Error(`Unknown command: ${type}`);
      return fn(data);
    },
    onState
  });
  game.modules.get(ID).api.link = link;
  if (game.settings.get(ID, "enabled")) link.start();
});
