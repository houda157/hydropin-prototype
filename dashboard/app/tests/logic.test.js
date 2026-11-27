// Severity, money saved and the view model of the farmer app (spec: docs/superpowers/specs/2026-11-27-farmer-app-design.md).
import { test } from "node:test";
import assert from "node:assert/strict";

import { DEMO_FARM_SCALE, FARM_SCALE } from "../../config.js";
import { severity } from "../lib/severity.js";
import { benchLostM3, leakMoney, leakNumbers, moneyReady, seasonSavedDt } from "../lib/savings.js";
import { toView } from "../lib/status.js";

test("severity thresholds", () => {
  assert.equal(severity(0.04, 1), "small"); assert.equal(severity(0.05, 1), "medium");
  assert.equal(severity(0.149, 1), "medium"); assert.equal(severity(0.15, 1), "large");
  assert.equal(severity(0.3, 0), null); assert.equal(severity(0.3, null), null);
});

test("money: worked example of the spec", () => {
  const m = leakMoney({ share: 0.03, lostM3: 18 }, DEMO_FARM_SCALE);
  assert.equal(m.leakM3PerH, 6); assert.equal(m.wouldLoseM3, 480);
  assert.equal(m.savedM3, 462); assert.equal(m.savedDt, 115.5);
});

test("money is null when a parameter is missing", () => {
  assert.equal(leakMoney({ share: 0.03, lostM3: 18 }, { ...DEMO_FARM_SCALE, price_dt_per_m3: null }), null);
  // ledger ruling: FARM_SCALE holds the example figures for now, so the "not filled in" case uses an explicit null
  const unset = { ...FARM_SCALE, farm_flow_m3_per_h: null };
  assert.equal(moneyReady(unset), false);
  assert.equal(seasonSavedDt([{ share: 0.03, lostM3: 18, status: "fixed" }], unset), null);
});

test("saved never negative", () => {
  assert.equal(leakMoney({ share: 0.001, lostM3: 999 }, DEMO_FARM_SCALE).savedM3, 0);
});

test("season total sums only fixed leaks", () => {
  const leaks = [{ share: 0.03, lostM3: 18, status: "fixed" }, { share: 0.03, lostM3: 18, status: "open" }];
  assert.equal(seasonSavedDt(leaks, DEMO_FARM_SCALE), 115.5);
});

test("bench litres to farm m3", () => {   // 1.5 L/min bench = 0.09 m3/h ; farm 200 m3/h -> x 2222.2
  assert.equal(Math.round(benchLostM3(9, 1.5, 200)), 20);
  assert.equal(benchLostM3(9, 0, 200), null);
});

test("leakNumbers: demo m3 first, bench scaling otherwise", () => {
  assert.deepEqual(leakNumbers({ max_leak_lpm: 8, base_lpm: 100, lost_m3: 3, status: "open" }, DEMO_FARM_SCALE),
                   { share: 0.08, lostM3: 3, status: "open" });
  assert.equal(Math.round(leakNumbers({ max_leak_lpm: 0.3, base_lpm: 1.5, lost_l: 9, status: "fixed" }, DEMO_FARM_SCALE).lostM3), 20);
});

test("offline when state OFFLINE or frame null", () => {
  assert.equal(toView({ state: "OFFLINE", frame: null }, [], ["A", "B"]).status, "offline");
  assert.equal(toView({ state: "HEALTHY", frame: null }, [], ["A", "B"]).status, "offline");
});

test("pump off = at rest, healthy/watch = fine and irrigating", () => {
  const off = toView({ state: "PUMP_OFF", frame: { state: "PUMP_OFF" } }, [], ["A", "B"]);
  assert.equal(off.status, "ok"); assert.equal(off.irrigating, false);
  for (const s of ["SETTLING", "LEARNING", "HEALTHY", "WATCH"]) {
    const v = toView({ state: s, frame: { state: s } }, [], ["A", "B"]);
    assert.equal(v.status, "ok", s); assert.equal(v.irrigating, true, s);
  }
});

test("leak view", () => {
  const v = toView({ state: "LEAK", frame: { state: "LEAK", branch: "B", flow_base_lpm: 1.5, leak_lpm: 0.3, loc: { L1: .1, L2: .7, L3: .2 } } },
                   [{ id: 4, status: "open", started_ts: "2026-11-27T06:12:00.000Z" }], ["A", "B"]);
  assert.deepEqual([v.status, v.sector, v.severity, v.whereTap, v.leakId], ["leak", "B", "large", "L2", 4]);
  assert.equal(v.foundTs, "2026-11-27T06:12:00.000Z");
});

test("leak in checking stays the current leak; no tap under 0.6", () => {
  const v = toView({ state: "LEAK", frame: { state: "LEAK", branch: "A", flow_base_lpm: 1.5, leak_lpm: 0.1, loc: { L1: .55, L2: .3, L3: .15 } } },
                   [{ id: 7, status: "checking", started_ts: "x" }, { id: 6, status: "fixed", started_ts: "y" }], ["A", "B"]);
  assert.equal(v.leakId, 7); assert.equal(v.leakStatus, "checking"); assert.equal(v.whereTap, null);
});
