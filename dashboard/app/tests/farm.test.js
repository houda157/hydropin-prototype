// The farm drawn on Home and Map, and the small map of "Where is it?".
import { test } from "node:test";
import assert from "node:assert/strict";

import { farmSvg, whereSvg } from "../farm.js";

const count = (s, re) => (s.match(re) || []).length;

test("sectors drawn", () => {
  assert.equal(count(farmSvg({ sectors: ["A", "B"], irrigating: [], leakSector: null, sensors: false }), /data-sector=/g), 2);
  assert.equal(count(farmSvg({ sectors: ["A", "B", "C", "D"], irrigating: [], leakSector: null, sensors: false }), /data-sector=/g), 4);
});

test("water flows only when irrigating", () => {
  assert.ok(farmSvg({ sectors: ["A", "B", "C", "D"], irrigating: ["A"], leakSector: null, sensors: false }).includes('class="flow"'));
  assert.ok(!farmSvg({ sectors: ["A", "B", "C", "D"], irrigating: [], leakSector: null, sensors: false }).includes('class="flow"'));
});

test("pin only on a leak", () => {
  assert.ok(farmSvg({ sectors: ["A", "B"], irrigating: ["A", "B"], leakSector: "B", sensors: false }).includes("data-pin"));
  assert.ok(!farmSvg({ sectors: ["A", "B"], irrigating: ["A", "B"], leakSector: null, sensors: false }).includes("data-pin"));
});

test("sensor dots on request", () => {
  assert.ok(count(farmSvg({ sectors: ["A", "B"], irrigating: [], leakSector: null, sensors: true }), /data-sensor/g) >= 2);
  assert.equal(count(farmSvg({ sectors: ["A", "B"], irrigating: [], leakSector: null, sensors: false }), /data-sensor/g), 0);
});

test("where map has the pin and the tap label", () => {
  const s = whereSvg({ tap: "L2" });
  assert.ok(s.includes("data-pin") && s.includes("L2"));
  assert.ok(!whereSvg({ tap: null }).includes(">L2<"));
});
