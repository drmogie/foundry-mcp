/**
 * The link to the relay, with no Foundry code inside so it can be tested with Node.
 * It keeps one WebSocket open, reconnects on its own, and answers commands.
 */

export const CLOSE_BAD_KEY = 4401;
export const CLOSE_REPLACED = 4409;

/** Give a friendly reason for a socket closing. */
export function explainClose(code) {
  if (code === CLOSE_BAD_KEY) return "bad-key";
  if (code === CLOSE_REPLACED) return "replaced";
  return "lost";
}

/** Wait time before retry number `attempt` (0 based): 1s, 2s, 4s ... up to 30s. */
export function backoffMs(attempt) {
  return Math.min(30000, 1000 * 2 ** attempt);
}

/** Turn a typed address into the socket address, or return null when it is unusable. */
export function buildSocketUrl(address, key) {
  if (!address || !key) return null;
  let url;
  try {
    url = new URL(address.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "ws:" && url.protocol !== "wss:") return null;
  if (!url.pathname || url.pathname === "/") url.pathname = "/ws/module";
  url.searchParams.set("key", key.trim());
  return url.toString();
}

export class RelayLink {
  /**
   * @param {object} opts
   * @param {() => {url:string,key:string}} opts.getSettings
   * @param {() => object} opts.hello        info sent when the socket opens
   * @param {(type:string,data:object) => Promise<any>} opts.handle  runs a command
   * @param {(state:string) => void} opts.onState  connected, connecting, off, no-settings, bad-key, replaced
   * @param {typeof WebSocket} [opts.WebSocketImpl]
   * @param {(fn:Function, ms:number) => any} [opts.setTimer]
   */
  constructor(opts) {
    this.opts = opts;
    this.WS = opts.WebSocketImpl ?? globalThis.WebSocket;
    this.setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.socket = null;
    this.attempt = 0;
    this.wanted = false;
    this.timer = null;
    this.beat = null;
  }

  start() {
    this.wanted = true;
    this.attempt = 0;
    this.#open();
  }

  stop() {
    this.wanted = false;
    clearTimeout(this.timer);
    clearInterval(this.beat);
    if (this.socket) this.socket.close(1000, "stopped");
    this.socket = null;
    this.opts.onState("off");
  }

  #open() {
    if (!this.wanted) return;
    const { url, key } = this.opts.getSettings();
    const target = buildSocketUrl(url, key);
    if (!target) {
      this.opts.onState("no-settings");
      return;
    }
    this.opts.onState("connecting");
    const socket = new this.WS(target);
    this.socket = socket;

    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "hello", ...this.opts.hello() }));
    };

    socket.onmessage = async (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === "welcome") {
        this.attempt = 0;
        this.opts.onState("connected");
        clearInterval(this.beat);
        this.beat = setInterval(() => {
          if (socket.readyState === 1) socket.send(JSON.stringify({ type: "heartbeat" }));
        }, 20000);
        return;
      }
      if (msg.type === "heartbeat" || msg.id === undefined) return;
      try {
        const data = await this.opts.handle(msg.type, msg.data ?? {});
        socket.send(JSON.stringify({ id: msg.id, ok: true, data }));
      } catch (err) {
        socket.send(JSON.stringify({ id: msg.id, ok: false, error: String(err?.message ?? err) }));
      }
    };

    socket.onclose = (event) => {
      clearInterval(this.beat);
      if (this.socket === socket) this.socket = null;
      if (!this.wanted) return;
      const why = explainClose(event.code);
      if (why === "bad-key") {
        this.opts.onState("bad-key");
        return; // do not hammer the relay with a wrong key
      }
      if (why === "replaced") {
        this.opts.onState("replaced");
        return;
      }
      const wait = backoffMs(this.attempt++);
      this.opts.onState("connecting");
      this.timer = this.setTimer(() => this.#open(), wait);
    };

    socket.onerror = () => {
      /* onclose follows and handles the retry */
    };
  }
}
