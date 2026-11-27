// Where the app's data comes from: the laptop backend (live, the test bench) or the demo script.
import { test } from "node:test";
import assert from "node:assert/strict";

import { DEMO_FARM_SCALE, FARM_SCALE } from "../../config.js";
import { demoSource } from "../demo.js";
import { detectSource, liveSource } from "../lib/source.js";

test("demo timeline", () => {
  let t = 0; const s = demoSource({ now: () => t }); let snap; s.start((x) => (snap = x));
  s.tick();
  assert.equal(snap.stateResponse.state, "HEALTHY");
  assert.deepEqual(snap.sectors, ["A", "B", "C", "D"]);
  assert.equal(snap.kind, "demo"); assert.equal(snap.scale, DEMO_FARM_SCALE);
  t = 9000; s.tick();
  assert.equal(snap.stateResponse.state, "LEAK");
  assert.equal(snap.stateResponse.frame.branch, "B");
  assert.equal(snap.stateResponse.frame.leak_lpm / snap.stateResponse.frame.flow_base_lpm, 0.08);
  s.markFixed(1); s.tick(); assert.equal(snap.leaks.find((l) => l.id === 1).status, "checking");
  t = 14000; s.tick();
  const fixed = snap.leaks.find((l) => l.id === 1);
  assert.equal(fixed.status, "fixed"); assert.equal(fixed.lost_m3, 4.6);
  assert.equal(snap.stateResponse.state, "HEALTHY");
  s.stop();
});

test("demo has two past fixed leaks for the history", () => {
  const s = demoSource({ now: () => 0 }); let snap; s.start((x) => (snap = x)); s.stop();
  const past = snap.leaks.filter((l) => l.status === "fixed");
  assert.equal(past.length, 2); assert.deepEqual(past.map((l) => l.branch).sort(), ["A", "C"]);
});

test("demo can start on the leak or on the repair", () => {
  let snap; const a = demoSource({ now: () => 0, start: "leak" }); a.start((x) => (snap = x)); a.stop();
  assert.equal(snap.stateResponse.state, "LEAK");
  const b = demoSource({ now: () => 0, start: "fixed" }); b.start((x) => (snap = x)); b.stop();
  assert.equal(snap.leaks.find((l) => l.id === 1).status, "fixed");
});

test("live source turns a failed fetch into OFFLINE", async () => {
  const s = liveSource("..", { fetchImpl: async () => { throw new Error("down"); }, intervalMs: 10 });
  const snap = await new Promise((res) => s.start(res)); s.stop();
  assert.equal(snap.stateResponse.state, "OFFLINE");
  assert.equal(snap.kind, "live"); assert.deepEqual(snap.sectors, ["A", "B"]); assert.equal(snap.scale, FARM_SCALE);
});

test("live source passes the backend's answers through", async () => {
  const answers = {
    "../api/state": { state: "LEAK", frame: { state: "LEAK", branch: "B" } },
    "../api/leaks?limit=20": [{ id: 3, status: "open" }],
  };
  const fetchImpl = async (url) => ({ ok: true, json: async () => answers[url] });
  const s = liveSource("..", { fetchImpl, intervalMs: 10 });
  const snap = await new Promise((res) => s.start(res)); s.stop();
  assert.equal(snap.stateResponse.state, "LEAK"); assert.equal(snap.leaks[0].id, 3);
});

test("detectSource", async () => {
  const ok = async () => ({ ok: true, json: async () => ({ ok: true, bench_detector: true }) });
  assert.equal(await detectSource("..", ok), "live");
  assert.equal(await detectSource("..", async () => { throw new Error("x"); }), "demo");
  assert.equal(await detectSource("..", async () => ({ ok: false, json: async () => ({}) })), "demo");
});

test("final fix 3: a poll that hangs (laptop asleep) ends as OFFLINE after the timeout", async () => {
  const hang = () => new Promise(() => {});
  const s = liveSource("..", { fetchImpl: hang, intervalMs: 1000, timeoutMs: 30 });
  const snap = await new Promise((res) => s.start(res)); s.stop();
  assert.equal(snap.stateResponse.state, "OFFLINE");
});
