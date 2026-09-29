/**
 * Status lights for the module settings page.
 * The checks are plain functions so Node can test them. installPanel is the only part that
 * touches the page, and it takes the document as an argument for the same reason.
 */

const ID = "fga-relay-connect";

/** How each link state looks. level is ok, wait, bad or off. */
export const STATE_INFO = {
  connected: { level: "ok", title: "FGA_RELAY.Panel.Connected", detail: "FGA_RELAY.Panel.ConnectedDetail" },
  connecting: { level: "wait", title: "FGA_RELAY.Panel.Connecting", detail: "FGA_RELAY.Panel.ConnectingDetail" },
  off: { level: "off", title: "FGA_RELAY.Panel.Off", detail: "FGA_RELAY.Panel.OffDetail" },
  "no-settings": { level: "bad", title: "FGA_RELAY.Panel.NoSettings", detail: "FGA_RELAY.Panel.NoSettingsDetail" },
  "bad-key": { level: "bad", title: "FGA_RELAY.Panel.BadKey", detail: "FGA_RELAY.Panel.BadKeyDetail" },
  replaced: { level: "bad", title: "FGA_RELAY.Panel.Replaced", detail: "FGA_RELAY.Panel.ReplacedDetail" }
};

/** The look for a state. Unknown states read as off. */
export function describeState(state) {
  return STATE_INFO[state] ?? STATE_INFO.off;
}

/**
 * Check a typed relay address.
 * @returns {{level:"ok"|"bad"|"empty", key:string}} key is a language key
 */
export function checkAddress(address, { securePage = false } = {}) {
  const text = String(address ?? "").trim();
  if (!text) return { level: "empty", key: "FGA_RELAY.Check.AddressEmpty" };
  let url;
  try {
    url = new URL(text);
  } catch {
    return { level: "bad", key: "FGA_RELAY.Check.AddressBad" };
  }
  if (url.protocol === "http:" || url.protocol === "https:") return { level: "bad", key: "FGA_RELAY.Check.AddressHttp" };
  if (url.protocol !== "ws:" && url.protocol !== "wss:") return { level: "bad", key: "FGA_RELAY.Check.AddressBad" };
  if (securePage && url.protocol === "ws:") return { level: "bad", key: "FGA_RELAY.Check.AddressNeedsWss" };
  return { level: "ok", key: "FGA_RELAY.Check.AddressOk" };
}

/** Check a typed connect key. It only checks that something sensible is there. */
export function checkKey(key) {
  const text = String(key ?? "").trim();
  if (!text) return { level: "empty", key: "FGA_RELAY.Check.KeyEmpty" };
  if (/\s/.test(text)) return { level: "bad", key: "FGA_RELAY.Check.KeySpaces" };
  if (text.length < 12) return { level: "bad", key: "FGA_RELAY.Check.KeyShort" };
  return { level: "ok", key: "FGA_RELAY.Check.KeyOk" };
}

/** "3:04 PM" style time for the since line. */
export function formatSince(when, locale) {
  if (!when) return "";
  return new Date(when).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

const CSS = `
.fga-relay-status { display: flex; gap: 0.6em; align-items: flex-start; margin: 0.4em 0 0.8em; padding: 0.6em 0.8em; border: 1px solid var(--color-border-light-tertiary, #888); border-left-width: 6px; border-radius: 4px; }
.fga-relay-status[data-level="ok"] { border-left-color: #2e9d4f; }
.fga-relay-status[data-level="wait"] { border-left-color: #d69a17; }
.fga-relay-status[data-level="bad"] { border-left-color: #c0392b; }
.fga-relay-status[data-level="off"] { border-left-color: #8a8a8a; }
.fga-relay-status .fga-relay-dot { flex: none; width: 0.9em; height: 0.9em; margin-top: 0.3em; border-radius: 50%; background: #8a8a8a; }
.fga-relay-status[data-level="ok"] .fga-relay-dot { background: #2e9d4f; }
.fga-relay-status[data-level="wait"] .fga-relay-dot { background: #d69a17; }
.fga-relay-status[data-level="bad"] .fga-relay-dot { background: #c0392b; }
.fga-relay-status .fga-relay-text { flex: 1; }
.fga-relay-status .fga-relay-title { font-weight: bold; }
.fga-relay-status .fga-relay-detail, .fga-relay-status .fga-relay-since, .fga-relay-status .fga-relay-pending { display: block; font-size: 0.9em; opacity: 0.85; }
.fga-relay-check { margin: 0.2em 0 0; font-size: 0.9em; }
.fga-relay-check[data-level="ok"]::before { content: "Good: "; color: #2e9d4f; font-weight: bold; }
.fga-relay-check[data-level="bad"]::before { content: "Fix: "; color: #c0392b; font-weight: bold; }
.fga-relay-check[data-level="empty"]::before { content: "Needed: "; color: #d69a17; font-weight: bold; }
`;

function ensureStyle(doc) {
  if (doc.getElementById("fga-relay-style")) return;
  const style = doc.createElement("style");
  style.id = "fga-relay-style";
  style.textContent = CSS;
  doc.head.append(style);
}

/** The form row for one of our settings, found by Foundry's own markers. */
function groupFor(root, name) {
  const byId = root.querySelector(`[data-setting-id="${ID}.${name}"]`);
  if (byId) return byId;
  const input = root.querySelector(`[name="${ID}.${name}"]`);
  return input?.closest(".form-group") ?? null;
}

/**
 * Put the status panel and the field checks on the settings page.
 * @param {HTMLElement} root  the settings window
 * @param {object} opts
 * @param {Document} opts.doc
 * @param {(key:string) => string} opts.localize
 * @param {() => string} opts.getState  current link state
 * @param {() => number|null} opts.getSince  when the state last changed
 * @param {() => {url:string,key:string}} opts.getSaved  saved settings
 * @param {() => boolean} [opts.getEnabled]  saved value of the connect switch
 * @param {boolean} opts.securePage  true when Foundry itself is on https
 * @param {() => void} opts.onReconnect
 * @returns {{refresh: () => void, element: HTMLElement}|null} null when our settings are not on this page
 */
export function installPanel(root, opts) {
  const anchor = groupFor(root, "enabled");
  if (!anchor) return null;
  const { doc, localize } = opts;
  ensureStyle(doc);
  root.querySelector(".fga-relay-status")?.remove();

  const panel = doc.createElement("div");
  panel.className = "fga-relay-status";
  panel.setAttribute("role", "status");
  panel.setAttribute("aria-live", "polite");
  const dot = doc.createElement("span");
  dot.className = "fga-relay-dot";
  dot.setAttribute("aria-hidden", "true");
  const text = doc.createElement("span");
  text.className = "fga-relay-text";
  const title = doc.createElement("span");
  title.className = "fga-relay-title";
  const detail = doc.createElement("span");
  detail.className = "fga-relay-detail";
  const since = doc.createElement("span");
  since.className = "fga-relay-since";
  const pending = doc.createElement("span");
  pending.className = "fga-relay-pending";
  text.append(title, detail, since, pending);
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "fga-relay-reconnect";
  button.textContent = localize("FGA_RELAY.Panel.Reconnect");
  button.addEventListener("click", () => opts.onReconnect());
  panel.append(dot, text, button);
  anchor.insertAdjacentElement("beforebegin", panel);

  const urlGroup = groupFor(root, "url");
  const keyGroup = groupFor(root, "key");
  const enabledInput = anchor.querySelector("input");
  const urlInput = urlGroup?.querySelector("input");
  const keyInput = keyGroup?.querySelector("input");
  const makeCheck = (group) => {
    if (!group) return null;
    group.querySelector(".fga-relay-check")?.remove();
    const p = doc.createElement("p");
    p.className = "fga-relay-check";
    group.append(p);
    return p;
  };
  const urlCheck = makeCheck(urlGroup);
  const keyCheck = makeCheck(keyGroup);

  const refresh = () => {
    const info = describeState(opts.getState());
    panel.dataset.level = info.level;
    title.textContent = localize(info.title);
    detail.textContent = localize(info.detail);
    const when = opts.getState() === "connected" ? formatSince(opts.getSince?.(), undefined) : "";
    since.textContent = when ? `${localize("FGA_RELAY.Panel.Since")} ${when}` : "";
    const saved = opts.getSaved();
    const typedUrl = urlInput ? urlInput.value : saved.url;
    const typedKey = keyInput ? keyInput.value : saved.key;
    const changed = typedUrl !== saved.url || typedKey !== saved.key || (enabledInput ? enabledInput.checked : true) !== (opts.getEnabled?.() ?? true);
    pending.textContent = changed ? localize("FGA_RELAY.Panel.Pending") : "";
    button.disabled = info.level === "off";
    for (const [check, result] of [
      [urlCheck, checkAddress(typedUrl, { securePage: opts.securePage })],
      [keyCheck, checkKey(typedKey)]
    ]) {
      if (!check) continue;
      check.dataset.level = result.level;
      check.textContent = localize(result.key);
    }
  };

  for (const input of [urlInput, keyInput, enabledInput]) {
    input?.addEventListener("input", refresh);
    input?.addEventListener("change", refresh);
  }
  refresh();
  return { refresh, element: panel };
}
