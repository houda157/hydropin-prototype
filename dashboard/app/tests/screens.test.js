// The rules of the screens (spec "Screens"): one main button, numbers behind Details, the
// test bench named as a bench, money "—" when the farm figures are missing.
import { test } from "node:test";
import assert from "node:assert/strict";

import { demoSource } from "../demo.js";
import { t } from "../lib/i18n.js";
import { toView } from "../lib/status.js";
import { detailsSheet, fixedScreen, helpScreen, homeScreen, mapScreen, savingsScreen, whereScreen } from "../screens.js";

const NOW = new Date("2026-11-27T07:00:00");
const primaries = (html) => (html.match(/class="btn (primary|danger)/g) || []).length;

function ctx(start = "leak", lang = "en", over = {}) {
  let snap; const s = demoSource({ now: () => NOW.getTime(), start }); s.start((x) => (snap = x)); s.stop();
  snap = { ...snap, ...over };
  return { snap, view: toView(snap.stateResponse, snap.leaks, snap.sectors), lang, now: NOW, lastFixedId: 1 };
}

test("home on a leak: status first, one main button, no raw numbers", () => {
  const html = homeScreen(ctx("leak"));
  assert.ok(html.includes(t("en", "status.leak.title", { sector: "B" })));
  assert.ok(html.includes(t("en", "btn.show_where")));
  assert.equal(primaries(html), 1);
  assert.ok(!/m³|L\/min/.test(html), "numbers belong behind Details");
});

test("home on a normal demo day: Mr Moez, demo badge, saved money, no main button", () => {
  const html = homeScreen(ctx("normal"));
  assert.ok(html.includes("Mr Moez") && html.includes(t("en", "badge.demo")));
  assert.ok(html.includes(t("en", "saved.season")));
  assert.equal(primaries(html), 0);
});

test("live mode names the test bench", () => {
  const c = ctx("normal", "en", { kind: "live", sectors: ["A", "B"] });
  const html = homeScreen(c);
  assert.ok(html.includes(t("en", "bench.name")) && html.includes(t("en", "badge.live")));
  assert.ok(!html.includes("Mr Moez"));
});

test("offline is said, never a stale 'fine'", () => {
  const c = ctx("normal", "en", { stateResponse: { state: "OFFLINE", frame: null } });
  const html = homeScreen(c);
  assert.ok(html.includes(t("en", "status.offline.title")));
  assert.ok(!html.includes(t("en", "status.ok.title")));
});

test("details: severity, plain why, money with 'estimate'", () => {
  const html = detailsSheet(ctx("leak"));
  assert.ok(html.includes(t("en", "sev.medium")) && html.includes(t("en", "sev.advice.medium")));
  assert.ok(html.includes(t("en", "details.why_text", { sector: "B" })));
  assert.ok(html.includes(t("en", "money.estimate")));
});

test("details: money is a dash when the farm figures are missing", () => {
  const c = ctx("leak");
  c.snap = { ...c.snap, scale: { ...c.snap.scale, price_dt_per_m3: null } };
  assert.ok(detailsSheet(c).includes(t("en", "money.not_set")));
});

test("details in live mode: money as a farm projection", () => {
  const c = ctx("leak", "en", { kind: "live" });
  assert.ok(detailsSheet(c).includes("If this leak happened on a 50 ha farm"));
});

test("details: no severity row when it is unknown", () => {
  const c = ctx("leak");
  c.view = { ...c.view, severity: null };
  assert.ok(!detailsSheet(c).includes(t("en", "details.severity")));
});

test("where, fixed, map, savings, help: at most one main button each", () => {
  for (const [name, fn, start] of [["where", whereScreen, "leak"], ["fixed", fixedScreen, "fixed"],
    ["map", mapScreen, "normal"], ["savings", savingsScreen, "normal"], ["help", helpScreen, "normal"]]) {
    assert.ok(primaries(fn(ctx(start))) <= 1, name);
  }
});

test("fixed screen: thanks and the money saved", () => {
  const html = fixedScreen(ctx("fixed"));
  assert.ok(html.includes(t("en", "fixed.title")) && html.includes(t("en", "fixed.saved")));
});

test("Arabic screens are in Arabic", () => {
  assert.ok(homeScreen(ctx("leak", "ar")).includes(t("ar", "status.leak.title", { sector: "B" })));
});
