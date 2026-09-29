import test from "node:test";
import assert from "node:assert/strict";
import { buildSocketUrl, backoffMs, explainClose, RelayLink } from "../scripts/link.mjs";

class FakeSocket {
  static last = null;
  constructor(url) { this.url = url; this.sent = []; this.readyState = 1; FakeSocket.last = this; }
  send(text) { this.sent.push(JSON.parse(text)); }
  close(code = 1000) { this.onclose?.({ code }); }
}

function make(overrides = {}) {
  const states = [];
  const timers = [];
  const link = new RelayLink({
    getSettings: () => ({ url: "ws://relay:3011", key: "fga_abc" }),
    hello: () => ({ clientId: "w:1", worldId: "w" }),
    handle: async (type) => { if (type === "boom") throw new Error("nope"); return { type }; },
    onState: (s) => states.push(s),
    WebSocketImpl: FakeSocket,
    setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    ...overrides
  });
  return { link, states, timers };
}

test("buildSocketUrl adds path and key", () => {
  assert.equal(buildSocketUrl("ws://relay:3011", "k1"), "ws://relay:3011/ws/module?key=k1");
  assert.equal(buildSocketUrl("wss://r.example/ws/module", " k 2 "), "wss://r.example/ws/module?key=k+2");
});

test("buildSocketUrl rejects bad input", () => {
  assert.equal(buildSocketUrl("", "k"), null);
  assert.equal(buildSocketUrl("ws://x", ""), null);
  assert.equal(buildSocketUrl("http://relay", "k"), null);
  assert.equal(buildSocketUrl("not a url", "k"), null);
});

test("backoff doubles then caps at 30 seconds", () => {
  assert.deepEqual([0, 1, 2, 3, 10].map(backoffMs), [1000, 2000, 4000, 8000, 30000]);
});

test("close codes are explained", () => {
  assert.equal(explainClose(4401), "bad-key");
  assert.equal(explainClose(4409), "replaced");
  assert.equal(explainClose(1006), "lost");
});

test("sends hello on open and reports connected after welcome", () => {
  const { link, states } = make();
  link.start();
  const s = FakeSocket.last;
  s.onopen();
  assert.deepEqual(s.sent[0], { type: "hello", clientId: "w:1", worldId: "w" });
  s.onmessage({ data: JSON.stringify({ type: "welcome" }) });
  assert.deepEqual(states, ["connecting", "connected"]);
  link.stop();
});

test("answers a command with ok and data", async () => {
  const { link } = make();
  link.start();
  const s = FakeSocket.last;
  await s.onmessage({ data: JSON.stringify({ id: 7, type: "ping", data: {} }) });
  assert.deepEqual(s.sent.at(-1), { id: 7, ok: true, data: { type: "ping" } });
  link.stop();
});

test("answers a failing command with a plain error", async () => {
  const { link } = make();
  link.start();
  const s = FakeSocket.last;
  await s.onmessage({ data: JSON.stringify({ id: 8, type: "boom" }) });
  assert.deepEqual(s.sent.at(-1), { id: 8, ok: false, error: "nope" });
  link.stop();
});

test("retries after a lost link with growing waits", () => {
  const { link, states, timers } = make();
  link.start();
  FakeSocket.last.onclose({ code: 1006 });
  assert.equal(timers.at(-1).ms, 1000);
  timers.at(-1).fn();
  FakeSocket.last.onclose({ code: 1006 });
  assert.equal(timers.at(-1).ms, 2000);
  assert.equal(states.at(-1), "connecting");
  link.stop();
});

test("wrong key stops retrying and says so", () => {
  const { link, states, timers } = make();
  link.start();
  FakeSocket.last.onclose({ code: 4401 });
  assert.equal(states.at(-1), "bad-key");
  assert.equal(timers.length, 0);
});

test("replaced link stops retrying", () => {
  const { link, states, timers } = make();
  link.start();
  FakeSocket.last.onclose({ code: 4409 });
  assert.equal(states.at(-1), "replaced");
  assert.equal(timers.length, 0);
});

test("missing settings reports no-settings without opening a socket", () => {
  FakeSocket.last = null;
  const { link, states } = make({ getSettings: () => ({ url: "", key: "" }) });
  link.start();
  assert.equal(FakeSocket.last, null);
  assert.deepEqual(states, ["no-settings"]);
});
