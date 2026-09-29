import { RelayLink } from "./link.mjs";
import { makeCommands } from "./commands.mjs";
import { installPanel } from "./indicators.mjs";

const ID = "fga-relay-connect";

/** Built once Foundry is ready. See commands.mjs for the list. */
let commands = {};

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
let lastChange = null;
let link = null;

/** Status panels that are open on a settings page. Closed ones drop out on the next refresh. */
const panels = new Set();

function refreshPanels() {
  for (const panel of [...panels]) {
    if (!panel.element.isConnected) panels.delete(panel);
    else panel.refresh();
  }
}

function onState(state) {
  if (state === lastState) return;
  lastState = state;
  lastChange = Date.now();
  const text = game.i18n.localize(MESSAGES[state] ?? MESSAGES.off);
  console.log(`${ID} | ${text}`);
  // Only nag the GM about problems and the first successful connection.
  if (["connected", "no-settings", "bad-key", "replaced"].includes(state)) {
    const level = state === "connected" ? "info" : "warn";
    ui.notifications?.[level](text);
  }
  game.modules.get(ID).api.state = state;
  refreshPanels();
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
  game.modules.get(ID).api = { state: "off", commands: {} };
});

/** Show live status lights at the top of our settings. */
Hooks.on("renderSettingsConfig", (app, html) => {
  const root = html instanceof HTMLElement ? html : (app.element ?? html?.[0]);
  if (!root?.querySelector) return;
  const panel = installPanel(root, {
    doc: document,
    localize: (key) => game.i18n.localize(key),
    getState: () => lastState ?? "off",
    getSince: () => lastChange,
    getSaved: () => ({ url: game.settings.get(ID, "url"), key: game.settings.get(ID, "key") }),
    getEnabled: () => game.settings.get(ID, "enabled"),
    securePage: window.location.protocol === "https:",
    onReconnect: () => {
      if (!link || !game.settings.get(ID, "enabled")) return;
      link.stop();
      link.start();
    }
  });
  if (panel) panels.add(panel);
});

Hooks.once("ready", () => {
  commands = makeCommands({
    game, fromUuid, Roll, ChatMessage, CONFIG,
    FilePicker: foundry.applications.apps.FilePicker.implementation,
    fetch: (url) => fetch(url),
    getRoute: (path) => foundry.utils.getRoute(path)
  });
  game.modules.get(ID).api.commands = commands;
  link = new RelayLink({
    getSettings: () => ({ url: game.settings.get(ID, "url"), key: game.settings.get(ID, "key") }),
    hello,
    handle: async (type, data) => {
      const fn = Object.hasOwn(commands, type) ? commands[type] : null;
      if (!fn) throw new Error(`Unknown command: ${type}`);
      return fn(data);
    },
    onState
  });
  game.modules.get(ID).api.link = link;
  if (game.settings.get(ID, "enabled")) link.start();
});
