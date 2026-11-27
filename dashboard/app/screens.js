// The farmer app's screens, as pure functions: context in, HTML out (main.js puts them on the page).
// Rules (spec "Screens"): one sentence and one main button per screen; numbers only behind Details,
// except money; red only for a leak; the live test bench is always named as a bench.
import { FARM_LOCATION } from "../config.js";
import { farmSvg, whereSvg } from "./farm.js";
import { fmt, locale, t } from "./lib/i18n.js";
import { leakMoney, leakNumbers, moneyReady, seasonSavedDt } from "./lib/savings.js";

const PHONE = "+21600000000";          // placeholder until the HydroPin number (open item)
const IRRIGATED = ["A", "B"];

export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
const T = (c, key, vars) => esc(t(c.lang, key, vars));
const ic = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const isLive = (c) => c.snap.kind === "live";

function clock(c, ts) {
  const d = new Date(ts);
  return isNaN(d) ? "" : d.toLocaleTimeString(locale(c.lang), { hour: "2-digit", minute: "2-digit", numberingSystem: "latn" });
}
function day(c, ts) {
  const d = new Date(ts);
  return isNaN(d) ? "" : d.toLocaleDateString(locale(c.lang), { day: "numeric", month: "short", numberingSystem: "latn" });
}
function hello(c) {
  const h = c.now.getHours();
  return T(c, h < 12 ? "hello.morning" : h < 18 ? "hello.afternoon" : "hello.evening");
}

const estimate = (c) => `<span class="est">${T(c, "money.estimate")}</span>`;

/** A money figure: "115 DT" (demo) or "If this leak happened on a 50 ha farm: about 115 DT" (live bench). */
function money(c, dt) {
  if (dt === null || dt === undefined) return `<span class="muted">${T(c, "money.not_set")}</span>`;
  const v = fmt(c.lang, dt, dt < 10 ? 1 : 0);
  if (isLive(c)) {
    const area = c.snap.scale.area_ha;
    return `${area ? T(c, "money.if_farm", { area: fmt(c.lang, area), dt: v }) : T(c, "money.if_farm_no_area", { dt: v })} ${estimate(c)}`;
  }
  return `<b class="money">${esc(v)} ${T(c, "currency")}</b> ${estimate(c)}`;
}

const currentLeak = (c) => c.snap.leaks.find((l) => l.id === c.view.leakId) || null;
const seasonDt = (c) => seasonSavedDt(c.snap.leaks.map((l) => leakNumbers(l, c.snap.scale)), c.snap.scale);

function badge(c) {
  return `<span class="chip ${isLive(c) ? "live" : "demo"}">${T(c, isLive(c) ? "badge.live" : "badge.demo")}</span>`;
}

function header(c) {
  const who = isLive(c)
    ? `<div class="n">${T(c, "bench.name")}</div>`
    : `<div class="t">${hello(c)}</div><div class="n">Mr Moez</div>`;
  return `<header class="hello"><div>${who}${badge(c)}</div>`
    + `<button class="avatar" data-action="profile" aria-label="${T(c, "profile.title")}">${isLive(c) ? ic("user") : "M"}</button></header>`;
}

function statusCard(c) {
  const v = c.view;
  if (v.status === "offline") {
    return `<section class="status off">${ic("alert", "xl")}<div><div class="t">${T(c, "status.offline.title")}</div>`
      + `<div class="s">${T(c, "status.offline.sub")}</div></div></section>`
      + `<a class="btn primary" href="tel:${PHONE}">${ic("help")}${T(c, "btn.call_us")}</a>`;
  }
  if (v.status === "leak") {
    return `<section class="status bad">${ic("alert", "xl")}<div><div class="t">${T(c, "status.leak.title", { sector: v.sector || "?" })}</div>`
      + `<div class="s">${T(c, "status.leak.sub", { time: clock(c, v.foundTs) })}</div></div></section>`
      + `<a class="btn danger" href="#/where">${ic("map")}${T(c, "btn.show_where")}</a>`;
  }
  return `<section class="status ok">${ic("check", "xl")}<div><div class="t">${T(c, "status.ok.title")}</div>`
    + `<div class="s">${T(c, "status.ok.sub")}</div></div></section>`;
}

function farmCard(c, sensors = false) {
  const v = c.view, sectors = c.snap.sectors;
  const irrigating = v.irrigating && v.status !== "offline" ? IRRIGATED.filter((s) => sectors.includes(s)) : [];
  const svg = farmSvg({ sectors, irrigating, leakSector: v.status === "leak" ? v.sector : null, sensors });
  let chip = "";
  if (v.status === "ok") {
    chip = irrigating.length
      ? `<span class="chip"><span class="dot pulse"></span>${T(c, "farm.irrigating", { sectors: irrigating.join(", ") })}</span>`
      : `<span class="chip rest"><span class="dot"></span>${T(c, "farm.rest")}</span>`;
  }
  return `<section class="card farm">${svg}${chip}</section>`;
}

function alertLines(c, leaks) {
  return leaks.map((l) => {
    const fixed = l.status === "fixed";
    const txt = fixed ? T(c, "alerts.leak_fixed", { sector: l.branch || "?", date: day(c, l.ended_ts || l.started_ts) })
      : T(c, "alerts.leak_open", { sector: l.branch || "?" });
    return `<div class="li">${ic(fixed ? "check" : "alert", `sm ${fixed ? "ok-c" : "bad-c"}`)}<span class="tx">${txt}</span></div>`;
  }).join("");
}

export function homeScreen(c) {
  const past = c.snap.leaks.filter((l) => l.id !== c.view.leakId).slice(0, 3);
  let saved = "";
  if (c.view.status === "ok" && !isLive(c)) {
    saved = `<section class="saved"><span class="l">${T(c, "saved.season")}</span><span class="v">${money(c, seasonDt(c))}</span></section>`;
  }
  const alerts = past.length
    ? `<div class="sec"><span class="h">${T(c, "alerts.title")}</span><a class="a" href="#/alerts">${T(c, "alerts.see_all")}</a></div>${alertLines(c, past)}`
    : "";
  return header(c) + statusCard(c) + farmCard(c) + saved + alerts;
}

function topbar(c, title, back = "#/home") {
  return `<div class="topbar"><a class="back" href="${back}" aria-label="back">${ic("back", "sm ic-dir")}</a><span>${title}</span></div>`;
}

export function whereScreen(c) {
  const leak = currentLeak(c);
  if (c.view.status !== "leak" && !leak) {
    return topbar(c, T(c, "map.title")) + statusCard(c) + `<a class="btn outline" href="#/home">${T(c, "btn.back_home")}</a>`;
  }
  const sector = c.view.sector || (leak && leak.branch) || "?";
  const maps = `https://www.google.com/maps/search/?api=1&query=${FARM_LOCATION.lat},${FARM_LOCATION.lon}`;
  return topbar(c, T(c, "where.sector", { sector }))
    + `<section class="card map">${whereSvg({ tap: c.view.whereTap })}</section>`
    + `<h1 class="bigsay">${T(c, "where.title")}</h1>`
    + `<p class="sub">${c.view.whereTap ? T(c, "where.near_tap", { tap: c.view.whereTap }) : T(c, "where.sector", { sector })}</p>`
    + `<a class="btn primary" href="${maps}" target="_blank" rel="noopener">${ic("go", "ic-dir")}${T(c, "btn.take_me")}</a>`
    + `<a class="btn outline" href="tel:${PHONE}">${ic("help")}${T(c, "btn.call_tech")}</a>`
    + `<button class="details" data-action="details"><span>${T(c, "details.title")}</span>${ic("down", "sm")}</button>`
    + `<button class="btn link" data-action="fixed">${T(c, "btn.fixed_it")}</button>`;
}

export function detailsSheet(c) {
  const v = c.view, leak = currentLeak(c), scale = c.snap.scale;
  const sector = v.sector || (leak && leak.branch) || "?";
  const rows = [];
  if (v.severity) {
    rows.push(`<div class="kv"><span class="k">${T(c, "details.severity")}</span><span class="pill sev-${v.severity}">${T(c, `sev.${v.severity}`)}</span> ${T(c, `sev.advice.${v.severity}`)}</div>`);
  }
  rows.push(`<div class="kv"><span class="k">${T(c, "details.why")}</span>${T(c, "details.why_text", { sector })}</div>`);
  const nums = leak ? leakNumbers(leak, scale) : { share: v.share, lostM3: null };
  if (!Number.isFinite(nums.share)) nums.share = v.share;
  let lost = `<span class="muted">${T(c, "money.not_set")}</span>`, how = lost;
  if (moneyReady(scale) && Number.isFinite(nums.lostM3)) {
    lost = `≈ ${esc(fmt(c.lang, nums.lostM3, 1))} m³ · ${money(c, Math.round(nums.lostM3 * scale.price_dt_per_m3 * 100) / 100)}`;
    const m = leakMoney(nums, scale);
    if (m) {
      const hours = Math.max(0, (c.now - new Date(v.foundTs || (leak && leak.started_ts))) / 3.6e6);
      how = T(c, "money.how", {
        perHour: fmt(c.lang, m.leakM3PerH, 1), days: fmt(c.lang, scale.days_to_notice_without_hydropin),
        hours: fmt(c.lang, Number.isFinite(hours) ? hours : 0, 1), saved: fmt(c.lang, m.savedM3), price: fmt(c.lang, scale.price_dt_per_m3, 2),
        dt: fmt(c.lang, m.savedDt, 1),
      }) + ` ${estimate(c)}`;
    }
  }
  rows.push(`<div class="kv"><span class="k">${T(c, "details.lost")}</span>${lost}</div>`);
  rows.push(`<div class="kv"><span class="k">${T(c, "details.where")}</span>${v.whereTap ? T(c, "where.near_tap", { tap: v.whereTap }) : T(c, "where.sector", { sector })}</div>`);
  rows.push(`<div class="kv"><span class="k">${T(c, "details.how_we_count")}</span>${how}</div>`);
  return `<h2>${T(c, "details.title")}</h2>${rows.join("")}<button class="btn outline" data-action="fixed">${T(c, "btn.fixed_it")}</button>`;
}

export function fixedScreen(c) {
  const leak = c.snap.leaks.find((l) => l.id === c.lastFixedId) || currentLeak(c) || c.snap.leaks[0];
  if (!leak) return homeScreen(c);
  if (leak.status !== "fixed") {
    return `<div class="center tall"><div class="spinner" aria-hidden="true"></div><h1 class="bigsay">${T(c, "checking.title")}</h1>`
      + `<p class="sub">${T(c, "checking.sub")}</p></div>`;
  }
  const nums = leakNumbers(leak, c.snap.scale), m = leakMoney(nums, c.snap.scale);
  const confirmed = !(leak.pump_stopped && !leak.ended_ts);
  return `<div class="center tall"><div class="bigcheck">${ic("check")}</div>`
    + `<h1 class="bigsay">${T(c, "fixed.title")}</h1><p class="sub">${T(c, confirmed ? "fixed.sub" : "fixed.not_confirmed")}</p>`
    + `<section class="saved"><span class="l">${T(c, "fixed.saved")}</span><span class="v">${money(c, m ? m.savedDt : null)}</span></section>`
    + `<label class="btn outline">${ic("cam")}${T(c, "btn.add_photo")}<input type="file" accept="image/*" capture="environment" hidden></label>`
    + `<a class="btn primary" href="#/home">${T(c, "btn.back_home")}</a></div>`;
}

export function mapScreen(c) {
  const n = isLive(c) ? 3 : 6;
  const status = c.view.status === "offline"
    ? `<section class="status off">${ic("alert")}<div class="t">${T(c, "status.offline.title")}</div></section>`
    : `<section class="status ok">${ic("check")}<div class="t">${T(c, "map.sensors_ok", { n })}</div></section>`;
  return `<h1 class="title">${T(c, "map.title")}</h1>${badge(c)}${farmCard(c, true)}${status}`
    + `<button class="details" data-action="sensors"><span>${T(c, "map.sensors_pipes")}</span>${ic("down", "sm")}</button>`;
}

export function sensorsSheet(c) {
  const names = isLive(c) ? ["F0 · Pump", "P1 · Sector A", "P2 · Sector B"]
    : ["F0 · Pump", "P1 · Sector A", "P2 · Sector B", "P3 · Sector C", "P4 · Sector D", "P5 · Main pipe"];
  return `<h2>${T(c, "sheet.sensors")}</h2>` + names.map((s) => `<div class="li">${ic("check", "sm ok-c")}<span class="tx">${esc(s)}</span></div>`).join("");
}

function monthBars(c) {
  const months = [];
  for (let i = 4; i >= 0; i--) months.push(new Date(c.now.getFullYear(), c.now.getMonth() - i, 1));
  const sums = months.map((m) => c.snap.leaks.filter((l) => l.status === "fixed").reduce((acc, l) => {
    const d = new Date(l.ended_ts || l.started_ts);
    if (d.getFullYear() !== m.getFullYear() || d.getMonth() !== m.getMonth()) return acc;
    const mm = leakMoney(leakNumbers(l, c.snap.scale), c.snap.scale);
    return acc + (mm ? mm.savedDt : 0);
  }, 0));
  const max = Math.max(1, ...sums);
  return `<div class="bars">${sums.map((v) => `<div style="height:${Math.max(4, Math.round(100 * v / max))}%"></div>`).join("")}</div>`
    + `<div class="bars-l">${months.map((m) => `<span>${esc(m.toLocaleDateString(locale(c.lang), { month: "short" }))}</span>`).join("")}</div>`;
}

export function savingsScreen(c) {
  const fixed = c.snap.leaks.filter((l) => l.status === "fixed").length;
  return `<h1 class="title">${T(c, "savings.title")}</h1>${badge(c)}`
    + `<div class="center"><p class="sub">${T(c, "savings.season", { year: c.now.getFullYear() })}</p>`
    + `<div class="huge">${money(c, seasonDt(c))}</div><p class="sub">${T(c, "savings.count", { n: fixed })}</p></div>`
    + `<section class="card">${monthBars(c)}</section>`
    + `<button class="details" data-action="savings"><span>${T(c, "savings.details")}</span>${ic("down", "sm")}</button>`
    + `<button class="btn outline" data-action="share">${ic("share")}${T(c, "btn.share_report")}</button>`;
}

export function savingsSheet(c) {
  const fixed = c.snap.leaks.filter((l) => l.status === "fixed");
  let m3 = 0, hours = 0, n = 0;
  for (const l of fixed) {
    const mm = leakMoney(leakNumbers(l, c.snap.scale), c.snap.scale);
    if (mm) m3 += mm.savedM3;
    const h = (new Date(l.ended_ts) - new Date(l.started_ts)) / 3.6e6;
    if (Number.isFinite(h)) { hours += h; n++; }
  }
  return `<h2>${T(c, "savings.details")}</h2>`
    + `<div class="kv"><span class="k">${T(c, "sheet.water_saved")}</span>≈ ${esc(fmt(c.lang, m3))} m³ ${estimate(c)}</div>`
    + `<div class="kv"><span class="k">${T(c, "sheet.avg_repair")}</span>${n ? esc(fmt(c.lang, hours / n, 1)) + " h" : "—"}</div>`;
}

export function shareText(c) {
  const dt = seasonDt(c);
  return t(c.lang, "share.text", { year: c.now.getFullYear(), n: c.snap.leaks.filter((l) => l.status === "fixed").length, dt: dt === null ? "—" : fmt(c.lang, dt) });
}

export function helpScreen(c) {
  return `<h1 class="title">${T(c, "help.title")}</h1>`
    + `<a class="btn primary big" href="tel:${PHONE}">${ic("help")}${T(c, "btn.call_us")}</a>`
    + `<a class="btn outline" href="https://wa.me/${PHONE.replace("+", "")}" target="_blank" rel="noopener">${ic("wa")}${T(c, "btn.whatsapp_us")}</a>`
    + `<section class="card row-card">${ic("cal", "ok-c")}<div>${T(c, "help.next_visit")}</div></section>`
    + `<button class="details" data-action="plan"><span>${T(c, "help.plan")}</span>${ic("down", "sm")}</button>`;
}

export function planSheet(c) {
  return `<h2>${T(c, "help.plan")}</h2><div class="kv">${T(c, "plan.monitor")}</div><div class="kv">${T(c, "plan.pinpoint")}</div>`
    + `<div class="kv">${T(c, "plan.payment")}</div>`;
}

export function alertsScreen(c) {
  return topbar(c, T(c, "alerts.title")) + (alertLines(c, c.snap.leaks) || `<p class="sub">—</p>`);
}

export function profileSheet(c) {
  const langs = [["fr", "Français"], ["ar", "العربية"], ["en", "English"]];
  return `<h2>${T(c, "profile.title")}</h2>`
    + `<div class="kv"><span class="k">${T(c, "profile.language")}</span><div class="langs">`
    + langs.map(([k, name]) => `<button class="lang" data-lang="${k}" aria-pressed="${c.lang === k}" lang="${k}">${name}</button>`).join("")
    + `</div></div><div class="kv"><span class="k">${T(c, "profile.source")}</span>${badge(c)}</div>`;
}
