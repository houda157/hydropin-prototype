// Texts in French, Arabic (right to left) and English; language helpers.
import { test } from "node:test";
import assert from "node:assert/strict";

import { STRINGS } from "../lib/strings.js";
import { detectLang, fmt, isRtl, loadLang, locale, saveLang, t } from "../lib/i18n.js";

const REQUIRED = `tab.home tab.map tab.savings tab.help hello.morning hello.afternoon hello.evening badge.demo badge.live
bench.name money.if_farm money.if_farm_no_area status.ok.title status.ok.sub status.leak.title status.leak.sub
status.offline.title status.offline.sub farm.irrigating farm.rest saved.season alerts.title alerts.see_all
alerts.leak_fixed alerts.leak_open btn.show_where btn.take_me btn.call_tech btn.fixed_it btn.back_home btn.call_us
btn.whatsapp_us btn.share_report btn.add_photo where.title where.sector where.near_tap details.title details.severity
sev.small sev.medium sev.large sev.advice.small sev.advice.medium sev.advice.large details.why details.why_text
details.lost details.where details.how_we_count money.how money.not_set money.estimate checking.title checking.sub
fixed.title fixed.sub fixed.saved fixed.not_confirmed map.title map.sensors_ok map.sensors_pipes savings.title
savings.season savings.count savings.details help.title help.next_visit help.plan profile.title profile.language
profile.source currency`.split(/\s+/);

test("every required key exists", () => {
  for (const k of REQUIRED) assert.ok(k in STRINGS.fr, `missing fr:${k}`);
});

test("same keys and placeholders in fr, ar, en", () => {
  const keys = (o) => Object.keys(o).sort();
  assert.deepEqual(keys(STRINGS.ar), keys(STRINGS.fr)); assert.deepEqual(keys(STRINGS.en), keys(STRINGS.fr));
  const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
  for (const k of keys(STRINGS.fr)) for (const l of ["ar", "en"]) assert.equal(ph(STRINGS[l][k]), ph(STRINGS.fr[k]), `${l}:${k}`);
  for (const l of ["fr", "ar", "en"]) for (const k of keys(STRINGS[l])) assert.ok(STRINGS[l][k].trim(), `${l}:${k} empty`);
});

test("the live bench is named as a bench", () => {
  assert.equal(t("en", "badge.live"), "Test bench · 2 sectors");
  assert.equal(t("en", "bench.name"), "HydroPin test bench");
  assert.equal(t("en", "money.if_farm", { area: 50, dt: "115.5" }), "If this leak happened on a 50 ha farm: about 115.5 DT");
});

test("t interpolates and falls back", () => {
  assert.equal(t("en", "status.leak.title", { sector: "B" }), "Leak in Sector B");
  assert.equal(t("en", "no.such.key"), "no.such.key");
});

test("detectLang", () => {
  assert.equal(detectLang("ar-TN", null), "ar"); assert.equal(detectLang("en-US", null), "en");
  assert.equal(detectLang("de-DE", null), "fr"); assert.equal(detectLang("en-US", "ar"), "ar");
  assert.equal(detectLang(undefined, "xx"), "fr");
});

test("isRtl and locale", () => {
  assert.equal(isRtl("ar"), true); assert.equal(isRtl("fr"), false);
  assert.equal(locale("ar"), "ar-TN"); assert.equal(locale("fr"), "fr-TN"); assert.equal(locale("en"), "en");
});

test("storage that throws is survived", () => {
  const bad = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(loadLang(bad), null); assert.doesNotThrow(() => saveLang("ar", bad));
  const mem = { v: null, getItem() { return this.v; }, setItem(_, x) { this.v = x; } };
  saveLang("ar", mem); assert.equal(loadLang(mem), "ar");
});

test("Arabic numbers use Latin digits", () => {
  assert.equal(fmt("ar", 86), "86"); assert.equal(fmt("en", 115.5, 1), "115.5");
});
