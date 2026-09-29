import test from "node:test";
import assert from "node:assert/strict";
import { describeState, checkAddress, checkKey, formatSince, STATE_INFO } from "../scripts/indicators.mjs";

test("every link state has a look, and unknown ones read as off", () => {
  for (const state of ["connected", "connecting", "off", "no-settings", "bad-key", "replaced"]) {
    const info = describeState(state);
    assert.ok(["ok", "wait", "bad", "off"].includes(info.level), state);
    assert.match(info.title, /^FGA_RELAY\.Panel\./);
    assert.match(info.detail, /^FGA_RELAY\.Panel\./);
  }
  assert.equal(describeState("connected").level, "ok");
  assert.equal(describeState("connecting").level, "wait");
  assert.equal(describeState("bad-key").level, "bad");
  assert.equal(describeState("weird"), STATE_INFO.off);
  assert.equal(describeState(undefined), STATE_INFO.off);
});

test("address check: empty, garbage, wrong scheme, and good", () => {
  assert.equal(checkAddress("").level, "empty");
  assert.equal(checkAddress("   ").level, "empty");
  assert.equal(checkAddress(undefined).level, "empty");
  assert.equal(checkAddress("not a url").key, "FGA_RELAY.Check.AddressBad");
  assert.equal(checkAddress("https://rest-relay.mogie.io").key, "FGA_RELAY.Check.AddressHttp");
  assert.equal(checkAddress("http://172.16.90.75:3011").key, "FGA_RELAY.Check.AddressHttp");
  assert.equal(checkAddress("ftp://x.example").key, "FGA_RELAY.Check.AddressBad");
  assert.deepEqual(checkAddress("wss://rest-relay.mogie.io"), { level: "ok", key: "FGA_RELAY.Check.AddressOk" });
  assert.equal(checkAddress("  ws://172.16.90.75:3011  ").level, "ok");
});

test("address check: an https Foundry page needs wss", () => {
  assert.equal(checkAddress("ws://172.16.90.75:3011", { securePage: true }).key, "FGA_RELAY.Check.AddressNeedsWss");
  assert.equal(checkAddress("wss://rest-relay.mogie.io", { securePage: true }).level, "ok");
  assert.equal(checkAddress("ws://172.16.90.75:3011", { securePage: false }).level, "ok");
});

test("key check: empty, spaces, short, and good", () => {
  assert.equal(checkKey("").level, "empty");
  assert.equal(checkKey(null).level, "empty");
  assert.equal(checkKey("abc def ghi jkl mno").key, "FGA_RELAY.Check.KeySpaces");
  assert.equal(checkKey("short").key, "FGA_RELAY.Check.KeyShort");
  assert.deepEqual(checkKey("k3Yx9Qp2Lm8Vw4Zr7Tn1"), { level: "ok", key: "FGA_RELAY.Check.KeyOk" });
  assert.equal(checkKey("  k3Yx9Qp2Lm8Vw4Zr7Tn1  ").level, "ok");
});

test("since time is empty without a time and a clock string with one", () => {
  assert.equal(formatSince(null), "");
  assert.match(formatSince(Date.UTC(2026, 8, 29, 22, 4), "en-US"), /\d{1,2}:\d{2}/);
});
