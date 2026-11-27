// HydroPin dashboard: live mode (WebSocket from the laptop backend) and replay mode (recorded runs,
// works on GitHub Pages). No build step, no external libraries; charts are plain SVG.
import { FARM_SCALE } from "./config.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = (v, d = 2, unit = "") => (v === null || v === undefined || Number.isNaN(v)) ? "–" : `${Number(v).toFixed(d)}${unit}`;
const getJSON = (url) => fetch(url, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });
const TAP_BRANCH = { L1: "A", L2: "B", L3: "B" };
// text typed into the dashboard (run label, opening, notes) or read from data files goes into
// innerHTML only through esc(), so it can never become markup or script
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ------------------------------------------------------------------ SVG line chart
function lineChart(el, { series, x0, x1, yMin, yMax, hlines = [], vlines = [], xlabel = "", yfmt = (v) => v.toFixed(2), legend = true }) {
  const w = el.clientWidth || 600, h = el.clientHeight || 180;
  const m = { l: 44, r: 10, t: legend ? 18 : 8, b: 22 };
  const pts = series.flatMap((s) => s.y.filter((v) => v !== null && Number.isFinite(v)));
  let lo = yMin ?? Math.min(...pts), hi = yMax ?? Math.max(...pts);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1; }
  if (hi - lo < 1e-9) { lo -= 0.05; hi += 0.05; }
  const pad = (yMin === undefined || yMax === undefined) ? (hi - lo) * 0.08 : 0;
  if (yMin === undefined) lo -= pad;
  if (yMax === undefined) hi += pad;
  const X = (x) => m.l + (x - x0) / Math.max(1e-9, x1 - x0) * (w - m.l - m.r);
  const Y = (y) => m.t + (1 - (y - lo) / (hi - lo)) * (h - m.t - m.b);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  const add = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text !== undefined) e.textContent = text; svg.appendChild(e); return e; };
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4;
    add("line", { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v), stroke: css("--grid"), "stroke-width": 1 });
    add("text", { x: m.l - 6, y: Y(v) + 3, "text-anchor": "end" }, yfmt(v));
  }
  const xt = niceStep((x1 - x0) / 6);
  for (let v = Math.ceil(x0 / xt) * xt; v <= x1 + 1e-9; v += xt) add("text", { x: X(v), y: h - 6, "text-anchor": "middle" }, `${+v.toFixed(3)}${xlabel}`);
  for (const hl of hlines) add("line", { x1: m.l, x2: w - m.r, y1: Y(hl.y), y2: Y(hl.y), stroke: hl.color || css("--muted"), "stroke-dasharray": "4 4", "stroke-width": 1 });
  for (const vl of vlines) {
    if (vl.x < x0 || vl.x > x1) continue;
    add("line", { x1: X(vl.x), x2: X(vl.x), y1: m.t, y2: h - m.b, stroke: vl.color || css("--muted"), "stroke-width": 1, "stroke-dasharray": vl.dash || "" });
    if (vl.label) add("text", { x: X(vl.x) + 4, y: m.t + 10 }, vl.label);
  }
  series.forEach((s) => {
    let d = "", pen = false;
    for (let i = 0; i < s.x.length; i++) {
      const y = s.y[i];
      if (y === null || !Number.isFinite(y) || s.x[i] < x0 || s.x[i] > x1) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(s.x[i]).toFixed(1)},${Y(Math.min(hi, Math.max(lo, y))).toFixed(1)}`;
      pen = true;
    }
    add("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 1.6, "stroke-dasharray": s.dash || "", "stroke-linejoin": "round" });
  });
  if (legend) {
    let lx = m.l;
    series.forEach((s) => {
      add("line", { x1: lx, x2: lx + 12, y1: 7, y2: 7, stroke: s.color, "stroke-width": 2, "stroke-dasharray": s.dash || "" });
      const t = add("text", { x: lx + 16, y: 10 }, s.label);
      lx += 26 + s.label.length * 6.2;
    });
  }
  el.replaceChildren(svg);
}
function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

// ------------------------------------------------------------------ bench schematic
const TAP_POS = { L1: [300, 58], L2: [260, 152], L3: [440, 152] };
function drawSchematic() {
  const s = $("schematic");
  s.innerHTML = `
    <g fill="none" stroke="var(--pipe)" stroke-width="3" stroke-linecap="round">
      <path d="M30 105 H150"/><path d="M150 105 V58 H560 V105"/><path d="M150 105 V152 H560 V105"/><path d="M560 105 H610"/>
    </g>
    <g font-family="var(--font-mono)">
      <rect x="16" y="88" width="40" height="34" rx="8" fill="var(--panel)" stroke="var(--line)" stroke-width="1.5"/>
      <text x="36" y="109" text-anchor="middle" style="fill:var(--ink);font-weight:600">Pump</text>
      <circle cx="100" cy="105" r="13" fill="var(--panel)" stroke="var(--s1)" stroke-width="2"/>
      <text x="100" y="109" text-anchor="middle" style="fill:var(--ink);font-weight:600">F0</text>
      <text x="100" y="135" text-anchor="middle" id="sv-f">–</text>
      <text x="190" y="48">Branch A</text><text x="190" y="176">Branch B</text>
      <circle cx="380" cy="58" r="13" fill="var(--panel)" stroke="var(--s1)" stroke-width="2"/>
      <text x="380" y="62" text-anchor="middle" style="fill:var(--ink);font-weight:600">PT1</text>
      <text x="380" y="88" text-anchor="middle" id="sv-p1">–</text>
      <circle cx="350" cy="152" r="13" fill="var(--panel)" stroke="var(--s2)" stroke-width="2"/>
      <text x="350" y="156" text-anchor="middle" style="fill:var(--ink);font-weight:600">PT2</text>
      <text x="350" y="130" text-anchor="middle" id="sv-p2">–</text>
      <text x="600" y="95" text-anchor="end">bucket</text>
      ${Object.entries(TAP_POS).map(([k, [x, y]]) => `
        <g id="tap-${k}"><circle cx="${x}" cy="${y}" r="16" fill="var(--leak)" opacity="0" class="halo"/>
        <rect x="${x - 7}" y="${y - 7}" width="14" height="14" rx="2" transform="rotate(45 ${x} ${y})" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/>
        <text x="${x}" y="${y + (y < 100 ? -16 : 28)}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${k}</text></g>`).join("")}
    </g>`;
}
// ------------------------------------------------------------------ 3D bench
// Houda's 3D bench (simulator/run/viewer3d) fed with THIS backend's frames: readings, state and the
// per-tap leak chance come from the frame; the twin (bench3d/board.json, tools/export_bench3d.py) only
// adds the pipe pressures and the flow split the bench does not measure.
const b3 = { view: "3d", h: null, bd: null, loading: null, last: null };
try { b3.view = localStorage.getItem("hp-bench-view") === "2d" ? "2d" : "3d"; } catch (e) { /* storage blocked */ }
const loadScript = (src) => new Promise((ok, ko) => {
  const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => ko(new Error(`${src} not found`));
  document.head.appendChild(s);
});
function webglOK() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
}
async function ensure3d() {
  if (b3.h) return true;
  if (!b3.loading) b3.loading = (async () => {
    if (!webglOK()) throw new Error("this browser has no WebGL");
    const [bd] = await Promise.all([getJSON("bench3d/board.json"), window.HP3D ? null : loadScript("bench3d/hp3d.bundle.js")]);
    b3.bd = bd;
    b3.h = window.HP3D.init(bd, $("bench3d"), { colours: () => true, labels: () => true, rotate: () => false },
      { bg: css("--panel"), floor: css("--panel-2") });
    b3.h.view("board");          // close-up on the board: the panel is smaller than the twin viewer's
  })();
  try { await b3.loading; return true; }
  catch (e) {
    b3.loading = null;
    const m = $("bench3d-msg"); m.hidden = false; m.textContent = `3D view unavailable (${e.message}): showing the 2D drawing.`;
    return false;
  }
}
const FLOWING = new Set(["SETTLING", "LEARNING", "HEALTHY", "WATCH", "LEAK"]);
// twin row for a tap whose leak flow is closest to the measured one
function twinFor(tap, leakLpm) {
  const S = b3.bd.states;
  let best = null, err = Infinity;
  for (const d of b3.bd.D) {
    const row = S[`${tap}|${d}`];
    if (row && Math.abs(row[3] - (leakLpm || 0)) < err) { err = Math.abs(row[3] - (leakLpm || 0)); best = row; }
  }
  return best || S["none|0"];
}
function liveArgs(fr) {
  if (!fr) return null;
  const st = fr.state, alarm = st === "LEAK" || st === "WATCH", loc = fr.loc || {};
  const ranked = ["L1", "L2", "L3"].map((t) => [t, loc[t] || 0]).sort((a, b) => b[1] - a[1]);
  // a tap is drawn open only when the detector is sure of it; a branch-B split (L2 ≈ L3) stays "suspected"
  const open = st === "LEAK" && ranked[0][1] >= 0.6 ? ranked[0][0] : null;
  const taps = {};
  for (const [t, p] of ranked) taps[t] = { p, open: t === open, suspect: alarm && t !== open && p >= 0.25 };
  const nN = b3.bd.nodes.length;
  let twin = b3.bd.states["none|0"];
  if (open) twin = twinFor(open, fr.leak_lpm);
  else {
    const sus = ranked.filter(([t]) => taps[t].suspect).map(([t]) => twinFor(t, fr.leak_lpm));
    if (sus.length) twin = sus[0].map((_, i) => sus.reduce((a, r) => a + r[i], 0) / sus.length);
  }
  if (!FLOWING.has(st)) twin = twin.map((v, i) => (i >= 6 && i < 6 + nN ? 0 : v));   // pump off: no pressure
  const cls = $("status-card").className;
  const kind = cls.includes("is-leak") ? "leak" : cls.includes("is-watch") ? "watch" : cls.includes("is-ok") ? "ok" : "idle";
  return { p1: fr.pt1_bar, p2: fr.pt2_bar, f0: FLOWING.has(st) ? fr.flow_lpm : 0, leakLpm: fr.leak_lpm || 0, twin, taps,
    setting: b3.bd.setting, status: { kind, text: $("status-title").textContent } };
}
function update3d(fr) {
  b3.last = fr;
  if (b3.h && b3.view === "3d") b3.h.setLive(liveArgs(fr));
}
function benchVisible() { return !$("tab-bench").hidden; }
async function setBenchView(v) {
  b3.view = v;
  try { localStorage.setItem("hp-bench-view", v); } catch (e) { /* storage blocked */ }
  $("bv-3d").setAttribute("aria-pressed", v === "3d");
  $("bv-2d").setAttribute("aria-pressed", v === "2d");
  $("schematic").toggleAttribute("hidden", v === "3d");   // an <svg> has no .hidden property
  $("bench3d").hidden = v !== "3d";
  $("b3-home").hidden = $("bench3d-details").hidden = v !== "3d";
  if (v !== "3d") { if (b3.h) b3.h.pause(true); return; }
  if (!(await ensure3d())) { $("bv-3d").disabled = true; return setBenchView("2d"); }
  b3.h.pause(!benchVisible());
  update3d(b3.last);
}

function updateSchematic(fr) {
  update3d(fr);
  $("sv-f").textContent = fr ? `${fmt(fr.flow_lpm, 2)} L/min` : "–";
  $("sv-p1").textContent = fr ? `${fmt(fr.pt1_bar, 3)} bar` : "–";
  $("sv-p2").textContent = fr ? `${fmt(fr.pt2_bar, 3)} bar` : "–";
  for (const k of Object.keys(TAP_POS)) {
    const v = fr && fr.loc ? fr.loc[k] || 0 : 0;
    document.querySelector(`#tap-${k} .halo`).setAttribute("opacity", (0.85 * v).toFixed(2));
  }
}

// ------------------------------------------------------------------ bench view
const bench = { frames: [], events: [], mode: null, replay: null, idx: 0, playing: false, timer: null, ws: null, runInfo: "" };
const stateClass = (s) => s === "LEAK" ? "st-leak" : s === "WATCH" ? "st-watch" : s === "HEALTHY" ? "st-ok" : "st-idle";

// Status card at the top of the Bench tab: one sentence, in the farmer app's words.
const ICONS = {
  ok: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.2 9.5"/>',
  leak: '<path d="M10.3 4 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4"/><path d="M12 17v.01"/>',
  watch: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/>',
  wait: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
  off: '<path d="M12 3.5v8"/><path d="M6.6 7a7.5 7.5 0 1 0 10.8 0"/>',
};
function renderStatus(st, fr) {
  const pct = fr && fr.p_leak !== null ? `${Math.round(100 * fr.p_leak)} %` : "–";
  const br = fr && fr.branch ? fr.branch : null;
  const [cls, icon, title, sub] =
    st === "HEALTHY" ? ["is-ok", "ok", "Everything is fine", "No leak on the bench"]
    : st === "WATCH" ? ["is-watch", "watch", "Watching a possible leak", br ? `Branch ${br}, P(leak) ${pct}` : `P(leak) ${pct}`]
    : st === "LEAK" ? ["is-leak", "leak", br ? `Leak in branch ${br}` : "Leak detected",
      fr && fr.leak_lpm ? `About ${fmt(fr.leak_lpm, 2)} L/min lost` : "Water is escaping"]
    : st === "PUMP_OFF" ? ["", "off", "Pump off", "Turn the pump on to start watching"]
    : st === "SETTLING" ? ["", "wait", "Settling", "The water is settling after the pump started"]
    : st === "LEARNING" ? ["", "wait", "Learning normal", "Learning what a healthy bench looks like"]
    : ["", "wait", "Waiting for bench data", "Start the ESP32 or the simulator"];
  $("status-card").className = `status ${cls}`;
  $("status-ic").innerHTML = ICONS[icon];
  $("status-title").textContent = title;
  $("status-sub").textContent = sub;
}

// "At farm scale": the same share of the flow lost on the reference farm (hidden until the market
// lead fills dashboard/config.js).
function farmScaleLine(fr) {
  const c = FARM_SCALE || {}, el = $("d-farm");
  const ok = c.area_ha && c.m3_per_ha_season && c.price_dt_per_m3 && fr && fr.leak_lpm > 0 && fr.flow_base_lpm > 0;
  el.hidden = !ok;
  if (!ok) return;
  const share = fr.leak_lpm / fr.flow_base_lpm;
  const m3 = share * c.area_ha * c.m3_per_ha_season;
  el.textContent = `At farm scale (estimate): the same ${Math.round(100 * share)} % of the flow on a ${c.area_ha} ha farm ` +
    `is ~${Math.round(m3).toLocaleString("en")} m³ and ~${Math.round(m3 * c.price_dt_per_m3).toLocaleString("en")} DT per season` +
    (c.source ? ` (${c.source})` : "") + ".";
}

function renderFrame(fr) {
  const st = fr ? fr.state : "–";
  for (const id of ["h-state"]) { $(id).textContent = st; $(id).className = `cellv dot ${stateClass(st)}`; }
  renderStatus(st, fr);
  $("d-state").textContent = st;
  $("d-state").style.color = st === "LEAK" ? "var(--leak)" : st === "WATCH" ? "var(--watch)" : st === "HEALTHY" ? "var(--ok)" : "";
  const p = fr ? fr.p_leak : null;
  $("h-p").textContent = fmt(p, 2);
  $("d-p").textContent = fmt(p, 3);
  const bar = $("d-pbar");
  bar.style.width = `${Math.round(100 * (p || 0))}%`;
  bar.style.background = p > 0.9 ? "var(--leak)" : p > 0.5 ? "var(--watch)" : "var(--ok)";
  const br = fr && fr.branch ? `Branch ${fr.branch}` : "–";
  $("h-branch").textContent = br; $("d-branch").textContent = fr && fr.branch ? fr.branch : "–";
  $("d-leak").textContent = fr && fr.leak_lpm ? `${fmt(fr.leak_lpm, 2)} L/min` : "–";
  $("d-lost").textContent = fr ? `${fmt(fr.lost_l, 2)} L` : "–";
  farmScaleLine(fr);
  $("d-fbase").textContent = fr && fr.flow_base_lpm !== null ? `${fmt(fr.flow_base_lpm, 2)} L/min` : "–";
  $("d-dp").textContent = fr && fr.dp_bar !== null ? `${fmt(fr.dp_bar, 3)} bar` : "–";
  const tb = $("d-methods").tBodies[0];
  tb.innerHTML = "";
  if (fr) for (const [name, m] of Object.entries(fr.methods)) {
    const tr = tb.insertRow();
    tr.innerHTML = `<td>${name === "m2" ? "M2" : "Flow"}</td><td>z ${fmt(m.z, 1)}</td><td>${m.score === null ? "–" : fmt(m.score, 2)}</td>
      <td>${m.excluded ? '<span class="pill no">excluded</span>' : '<span class="pill ok">ok</span>'}</td>`;
  }
  const faults = fr ? fr.faults || [] : [];
  $("d-faults").innerHTML = faults.length ? faults.map((f) => `<span class="chip">${esc(f)}</span>`).join("") : '<span class="note">none</span>';
  $("d-loc").innerHTML = ["L1", "L2", "L3"].map((k) => {
    const v = fr && fr.loc ? fr.loc[k] || 0 : 0;
    return `<div class="r"><span>${k}</span><div class="t"><div style="width:${Math.round(100 * v)}%"></div></div><small>${Math.round(100 * v)}%</small></div>`;
  }).join("");
  updateSchematic(fr);
}

function renderCharts(frames, x0, x1, tOf) {
  const x = frames.map(tOf);
  const ev = bench.events.map((e) => ({ x: e.t_s, label: e.type + (e.tap ? ` ${e.tap}` : ""), color: css("--muted"), dash: "3 3" }));
  lineChart($("c-p"), { x0, x1, xlabel: " s", yfmt: (v) => v.toFixed(2), vlines: ev, series: [
    { label: "PT1 (A)", x, y: frames.map((f) => f.pt1_bar), color: css("--s1") },
    { label: "PT2 (B)", x, y: frames.map((f) => f.pt2_bar), color: css("--s2") }] });
  lineChart($("c-f"), { x0, x1, xlabel: " s", vlines: ev, series: [
    { label: "F0", x, y: frames.map((f) => f.flow_lpm), color: css("--s1") },
    { label: "baseline", x, y: frames.map((f) => f.flow_base_lpm), color: css("--base"), dash: "5 4" }] });
  lineChart($("c-pl"), { x0, x1, yMin: 0, yMax: 1, xlabel: " s", yfmt: (v) => v.toFixed(1), vlines: ev,
    hlines: [{ y: 0.5, color: css("--watch") }, { y: 0.9, color: css("--leak") }],
    series: [{ label: "P(leak)", x, y: frames.map((f) => f.p_leak), color: css("--leak") }] });
}

function setSource(kind) {
  const el = $("h-source");
  el.textContent = kind === "sim" ? "Simulation" : kind === "bench" ? "Measured (bench)" : kind === "live" ? "Live (bench)" : "–";
  el.style.color = kind === "sim" ? "var(--sim-ink)" : kind ? "var(--ok)" : "";
}

// "What's real" tab: claim measured bench data only when a recorded bench run is published
function setRealPills(hasBench) {
  const set = (id, ok, okText, noText, noClass) => {
    $(id).textContent = ok ? okText : noText;
    $(id).className = `pill ${ok ? "ok" : noClass}`;
  };
  set("real-bench", hasBench, "measured", "not recorded yet", "no");
  set("real-detect", hasBench, "runs on real data", "tested on simulation", "sim");
}

// --- replay
async function loadReplayIndex() {
  try {
    const idx = await getJSON("replays/index.json");
    const pick = $("replay-pick");
    const runs = idx.runs.slice().sort((a, b) => (a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind === "bench" ? -1 : 1));
    pick.innerHTML = runs.map((r) => `<option value="${esc(r.file)}">${r.simulation ? "[sim] " : "[bench] "}${esc(r.label)}${r.opening ? ` · ${esc(r.opening)}` : ""} · ${esc(r.id)}</option>`).join("");
    const first = runs.find((r) => r.label === "leak_L1" && r.opening === "medium") || runs[0];
    if (first) pick.value = first.file;
    setRealPills(runs.some((r) => r.kind === "bench" && !r.simulation));
    return runs.length > 0;
  } catch (e) {
    $("replay-pick").innerHTML = "<option>no replays found</option>";
    return false;
  }
}
async function openReplay(file) {
  stopPlay();
  const rep = await getJSON(`replays/${file}`);
  bench.replay = rep; bench.events = rep.events; bench.idx = 0;
  setSource(rep.simulation ? "sim" : "bench");
  const b = $("bench-banner");
  b.hidden = false;
  b.className = `banner ${rep.simulation ? "is-sim" : "is-real"}`;
  b.textContent = rep.simulation
    ? `Simulation (${rep.source}): ${rep.meta.notes || ""} Detector output is real code; the readings are simulated.`
    : `Recorded on the bench: ${rep.meta.notes || rep.id}${rep.meta.measured_leak_lpm ? `, measured leak ${rep.meta.measured_leak_lpm} L/min` : ""}.`;
  $("run-info").innerHTML = `<b>${esc(rep.label)}</b>${rep.meta.opening ? ` · ${esc(rep.meta.opening)}` : ""}<br>${rep.events.map((e) => `${esc(e.type)}${e.tap ? " " + esc(e.tap) : ""} @ ${esc(e.t_s)} s`).join("<br>") || "no events"}`;
  const sc = $("rp-scrub"); sc.max = rep.frames.length - 1; sc.value = rep.frames.length - 1;
  seek(rep.frames.length - 1);
}
function seek(i) {
  const rep = bench.replay; if (!rep) return;
  bench.idx = Math.max(0, Math.min(rep.frames.length - 1, i));
  const shown = rep.frames.slice(0, bench.idx + 1);
  renderFrame(shown[shown.length - 1]);
  renderCharts(shown, 0, rep.frames[rep.frames.length - 1].t_s, (f) => f.t_s);
  $("rp-scrub").value = bench.idx;
  $("rp-time").textContent = `${shown[shown.length - 1].t_s.toFixed(1)} s`;
}
function stopPlay() { bench.playing = false; clearInterval(bench.timer); $("rp-play").textContent = "Play"; }
function togglePlay() {
  if (bench.playing) return stopPlay();
  const rep = bench.replay; if (!rep) return;
  if (bench.idx >= rep.frames.length - 1) bench.idx = 0;
  bench.playing = true; $("rp-play").textContent = "Pause";
  const tick = 100; // ms
  bench.timer = setInterval(() => {
    const speed = +$("rp-speed").value;
    const tNow = rep.frames[bench.idx].t_s + speed * tick / 1000;
    let j = bench.idx;
    while (j < rep.frames.length - 1 && rep.frames[j + 1].t_s <= tNow) j++;
    if (j === bench.idx && j < rep.frames.length - 1) j++;
    seek(j);
    if (j >= rep.frames.length - 1) stopPlay();
  }, tick);
}

// --- live
const LIVE_WINDOW_S = 180;
const tsSec = (ts) => Date.parse(ts) / 1000;
function liveRender() {
  const fr = bench.frames;
  if (!fr.length) { renderFrame(null); return; }
  const first = tsSec(fr[0].ts);
  const t1 = Math.max(tsSec(fr[fr.length - 1].ts), first + 30), t0 = Math.max(first, t1 - LIVE_WINDOW_S);
  const shown = fr.filter((f) => tsSec(f.ts) >= t0);
  bench.events = bench.liveEvents.map((e) => ({ ...e, t_s: tsSec(e.ts) - first }));
  renderFrame(shown[shown.length - 1]);
  renderCharts(shown, t0 - first, t1 - first, (f) => tsSec(f.ts) - first);
}
function startLive() {
  bench.frames = []; bench.liveEvents = [];
  setSource("live");
  $("bench-banner").hidden = false;
  $("bench-banner").className = "banner is-real";
  $("bench-banner").textContent = "Live from the bench via the laptop backend (MQTT → detector → WebSocket).";
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  bench.ws = ws;
  ws.onopen = () => { $("live-conn").textContent = "connected"; };
  ws.onclose = () => { $("live-conn").textContent = "disconnected"; };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.frames && msg.frames.length) {
      bench.frames.push(...msg.frames);
      if (bench.frames.length > 4000) bench.frames.splice(0, bench.frames.length - 4000);
    }
    $("live-conn").textContent = `connected · ${msg.state}`;
    liveRender();
    // the last frame still carries its old state: OFFLINE must win everywhere, after the render
    if (msg.state === "OFFLINE") {
      $("h-state").textContent = "OFFLINE"; $("h-state").className = "cellv dot st-idle";
      $("d-state").textContent = "OFFLINE"; $("d-state").style.color = ""; renderStatus("OFFLINE", null);
    }
  };
  refreshRuns();
}
function stopLive() { if (bench.ws) { bench.ws.onclose = null; bench.ws.close(); bench.ws = null; } }
async function refreshRuns() {
  try {
    const runs = await getJSON("api/runs?limit=1");
    const r = runs[0];
    $("run-info").innerHTML = r ? `Run #${esc(r.id)} <b>${esc(r.label)}</b>${r.opening ? ` · ${esc(r.opening)}` : ""} ${r.stopped_ts ? "(stopped)" : "(recording)"}` : "No run yet";
    if (r && !r.stopped_ts) bench.liveEvents = (await getJSON(`api/events?run_id=${r.id}`)) || [];
  } catch (e) { /* backend without runs */ }
}
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.status);
  return j;
}
function wireLiveForms() {
  const msg = (t) => { $("live-msg").textContent = t; };
  $("f-run").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await post("api/runs", { label: fd.get("label"), opening: fd.get("opening") || null,
        measured_leak_lpm: fd.get("measured_leak_lpm") || null, blind: fd.get("blind") === "on", notes: fd.get("notes") });
      msg(`Run #${r.id} started`); refreshRuns();
    } catch (err) { msg(`Error: ${err.message}`); }
  });
  $("b-stop").addEventListener("click", async () => {
    try { const runs = await getJSON("api/runs?limit=1"); if (runs[0]) { await post(`api/runs/${runs[0].id}/stop`); msg(`Run #${runs[0].id} stopped`); refreshRuns(); } }
    catch (err) { msg(`Error: ${err.message}`); }
  });
  document.querySelectorAll("[data-ev]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const ev = await post("api/events", { type: b.dataset.ev, tap: b.dataset.tap || null });
      bench.liveEvents.push(ev); msg(`${ev.type}${ev.tap ? " " + ev.tap : ""} recorded`);
      if (ev.type === "valve_change") msg("Valve moved: press Re-baseline once the flow is steady.");
    } catch (err) { msg(`Error: ${err.message}`); }
  }));
  $("b-reset").addEventListener("click", async () => {
    try { await post("api/baseline/reset"); msg("Baseline reset: settling, then learning for 30 s."); } catch (err) { msg(`Error: ${err.message}`); }
  });
}

async function setMode(mode) {
  if (bench.mode === mode) return;
  bench.mode = mode;
  $("mode-live").setAttribute("aria-pressed", mode === "live");
  $("mode-replay").setAttribute("aria-pressed", mode === "replay");
  $("replay-ctl").hidden = mode !== "replay";
  $("live-ctl").hidden = mode !== "live";
  $("live-forms").hidden = mode !== "live";
  if (mode === "live") { stopPlay(); startLive(); }
  else { stopLive(); const f = $("replay-pick").value; if (f && f.endsWith(".json")) await openReplay(f); }
}

async function backendAvailable() {
  if (location.protocol === "file:" || location.hostname.endsWith("github.io")) return false;
  try { const h = await getJSON("health"); return !!h.ok; } catch (e) { return false; }
}

// ------------------------------------------------------------------ scoreboard
async function loadScoreboard() {
  let board, real = true;
  try { board = await getJSON("scoreboard.json"); } catch (e) { real = false; }
  if (!board) { try { board = await getJSON("scoreboard_sim.json"); } catch (e) { $("score-banner").textContent = "No scoreboard exported yet."; return; } }
  const sim = board.simulation;
  $("real-score").textContent = sim ? "simulation for now" : "measured";
  $("real-score").className = `pill ${sim ? "sim" : "ok"}`;
  const ban = $("score-banner");
  ban.className = `banner ${sim ? "is-sim" : "is-real"}`;
  ban.textContent = (sim ? "Simulation: " : "Measured on the bench: ") + board.notes + (board.headline ? ` Headline: ${board.headline}.` : "");
  const s = board.summary;
  const pct = (v) => v === null ? "–" : `${Math.round(100 * v)}%`;
  const tiles = [["Leak runs", s.leak_runs], ["Detected (LEAK)", pct(s.detection_rate)], ["WATCH or LEAK", pct(s.watch_or_leak_rate)],
    ["Right branch", pct(s.branch_accuracy)], ["Median delay", s.median_delay_s === null ? "–" : `${s.median_delay_s} s`],
    ["False-alarm runs", `${s.false_alarm_runs} / ${s.leak_runs + s.clean_runs}`]];
  if (s.false_alarms_per_hour !== undefined && s.false_alarms_per_hour !== null)
    tiles.push(["False alarms / hour", `${s.false_alarms_per_hour}`]);
  if (s.tap_accuracy !== undefined && s.tap_accuracy !== null) tiles.splice(4, 0, ["Right tap", pct(s.tap_accuracy)]);
  $("score-tiles").innerHTML = tiles.map(([k, v]) => `<div class="tile"><span class="lbl">${k}</span><b>${v}</b></div>`).join("");
  $("score-tap").innerHTML = `<thead><tr><th>Tap</th><th>Branch</th><th>Runs</th><th>Detected</th><th>Right branch</th></tr></thead><tbody>${
    Object.entries(board.per_tap).map(([t, d]) => `<tr><td>${t}</td><td>${TAP_BRANCH[t]}</td><td>${d.runs}</td><td>${d.detected}</td><td>${d.branch_ok}</td></tr>`).join("")}</tbody>`;
  $("score-size").innerHTML = `<thead><tr><th>Size</th><th>Runs</th><th>LEAK</th><th>WATCH or LEAK</th></tr></thead><tbody>${
    Object.entries(board.per_opening || {}).map(([t, d]) => `<tr><td>${t}</td><td>${d.runs}</td><td>${d.detected}</td><td>${d.watched}</td></tr>`).join("")}</tbody>`;
  const pm = board.per_method || {};
  const mname = { fused: "Fused (flow + M2)", flow: "Flow alone", m2: "M2 alone" };
  $("score-methods").innerHTML = `<thead><tr><th>Method</th><th>Detected</th><th>Median delay</th><th>False alarms / h</th></tr></thead><tbody>${
    Object.entries(pm).map(([m, d]) => `<tr><td>${mname[m] || m}</td><td>${pct(d.detection_rate)}</td><td>${d.median_delay_s ?? "–"}${d.median_delay_s != null ? " s" : ""}</td><td>${d.false_alarms_per_hour ?? "–"}</td></tr>`).join("")
    || '<tr><td colspan="4">Not in this scoreboard.</td></tr>'}</tbody>`;
  const cm = (board.confusion || {}).taps;
  $("score-confusion").innerHTML = cm ? `<thead><tr><th>Opened</th>${["L1", "L2", "L3", "missed"].map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${
    ["L1", "L2", "L3"].map((r) => `<tr><td>${r} (${TAP_BRANCH[r]})</td>${["L1", "L2", "L3", "missed"].map((c) => `<td${r === c ? ' style="font-weight:700"' : ""}>${cm[r][c]}</td>`).join("")}</tr>`).join("")}</tbody>`
    : "<tbody><tr><td>Not in this scoreboard.</td></tr></tbody>";
  const bl = board.blind || { runs: 0 };
  $("score-blind-pn").hidden = !bl.runs;
  if (bl.runs) {
    $("score-blind-n").textContent = `${bl.runs} events`;
    $("score-blind").innerHTML = `<thead><tr><th>Run</th><th>Truth</th><th>Result</th><th>Delay</th><th>Branch</th></tr></thead><tbody>${
      bl.events.map((r) => `<tr><td>${esc(r.id)}</td><td>${esc(r.label)}</td><td>${r.detected === null ? (r.false_alarm ? '<span class="pill">false alarm</span>' : '<span class="pill ok">quiet</span>') : r.detected ? '<span class="pill ok">LEAK</span>' : '<span class="pill no">missed</span>'}</td><td>${r.delay_s ?? "–"}</td><td>${r.branch ?? "–"}</td></tr>`).join("")}</tbody>`;
  }
  $("score-n").textContent = `${board.runs.length} runs`;
  $("score-runs").innerHTML = `<thead><tr><th>Run</th><th>Label</th><th>Split</th><th>Result</th><th>Delay</th><th>Branch</th><th>Faults</th></tr></thead><tbody>${
    board.runs.map((r) => {
      const res = r.detected === null ? (r.false_alarm ? '<span class="pill">false alarm</span>' : '<span class="pill ok">quiet</span>')
        : r.detected ? '<span class="pill ok">LEAK</span>' : r.watched ? '<span class="pill">WATCH</span>' : '<span class="pill no">missed</span>';
      return `<tr><td>${esc(r.id)}</td><td>${esc(r.label)}</td><td>${esc(r.split || (r.blind ? "blind" : "–"))}</td><td>${res}</td><td>${r.delay_s ?? "–"}</td><td>${r.branch ?? "–"}${r.branch_ok === false && r.detected ? " ✗" : ""}</td><td>${esc((r.faults || []).join(", ")) || "–"}</td></tr>`;
    }).join("")}</tbody>`;
}

// ------------------------------------------------------------------ M3
let m3Index = null;
async function loadM3() {
  try { m3Index = await getJSON("m3/index.json"); } catch (e) { $("m3-story").textContent = "M3 data not found."; return; }
  $("m3-banner").textContent = m3Index.label;
  $("m3-pick").innerHTML = m3Index.cases.map((c) => `<option value="${c.file}">${c.title}</option>`).join("");
  $("m3-pick").addEventListener("change", (e) => showM3(e.target.value));
  showM3(m3Index.cases[0].file);
}
async function showM3(file) {
  const c = await getJSON(`m3/${file}`);
  $("m3-story").textContent = c.story || "";
  const s = c.sensor;
  const t = s.H_m.map((_, i) => s.t0_s + i * s.dt_s);
  const xs = { series: [{ label: "measured (simulated, with noise)", x: t, y: s.H_m, color: css("--s1"), width: 1.2 },
    ...(s.model_H_m ? [{ label: "intact-pipe model", x: t, y: s.model_H_m, color: css("--base"), dash: "5 4" }] : [])] };
  const vl = [];
  if (c.timing && c.timing.echo_expected_s) vl.push({ x: c.timing.echo_expected_s, label: "leak echo" });
  lineChart($("m3-trace"), { ...xs, x0: t[0], x1: t[t.length - 1], xlabel: " s", yfmt: (v) => v.toFixed(0), vlines: vl });
  const trMax = Math.max(...c.tr.energy);
  const ser = [{ label: "time reversal", x: c.tr.x_m, y: c.tr.energy.map((v) => v / trMax), color: css("--primary") }];
  if (c.mfp) { const mm = Math.max(...c.mfp.match); ser.push({ label: "matched-field", x: c.mfp.x_m, y: c.mfp.match.map((v) => v / mm), color: css("--s2"), dash: "5 4" }); }
  lineChart($("m3-tr"), { series: ser, x0: c.tr.x_m[0], x1: c.tr.x_m[c.tr.x_m.length - 1], yMin: 0, yMax: 1.05, xlabel: " m",
    yfmt: (v) => v.toFixed(1), vlines: [{ x: c.leak.x_true_m, label: "true leak", color: css("--leak") }] });
  const names = { tr: "Time reversal", mfp: "Matched-field", echo: "Echo timing", cnn: "1D CNN" };
  $("m3-est").innerHTML = `<thead><tr><th>Method</th><th>Estimate (m)</th><th>Error (m)</th></tr></thead><tbody>${
    Object.keys(c.estimates_m).map((k) => `<tr><td>${names[k] || k}</td><td>${fmt(c.estimates_m[k], 1)}</td><td>${fmt(c.error_m[k], 2)}</td></tr>`).join("")
  }<tr><td>True position</td><td>${fmt(c.leak.x_true_m, 1)}</td><td>–</td></tr></tbody>`;
}


// ------------------------------------------------------------------ farm (simulation)
const farm = { lay: null, place: null, res: null, drone: null, view: "place", n: 6, set: "6", method: "fused", scen: 0, raf: 0 };
async function loadFarm() {
  const get = (u) => getJSON(u).catch(() => null);
  [farm.lay, farm.place, farm.res, farm.drone] = await Promise.all([get("farm/layout.json"), get("farm/placement.json"),
    get("farm/results.json"), get("farm/drone.json")]);
  if (!farm.lay) { $("farm-map").textContent = "farm/layout.json not found."; return; }
  if (farm.place) { $("f-n").value = farm.n = farm.place.recommended_n || 6; }
  if (farm.res) {
    $("f-scen").innerHTML = farm.res.scenarios.map((sc, i) => `<option value="${i}">${sc.title}</option>`).join("");
    if (!farm.res.methods.includes("m1")) document.querySelector('[data-fm="m1"]').disabled = true;
  } else $("fv-leak").disabled = true;
  if (!farm.place) $("fv-place").disabled = true;
  $("fv-place").addEventListener("click", () => setFarmView("place"));
  $("fv-leak").addEventListener("click", () => setFarmView("leak"));
  $("f-n").addEventListener("input", (e) => { farm.n = +e.target.value; renderFarm(); });
  $("f-scen").addEventListener("change", (e) => { farm.scen = +e.target.value; renderFarm(); });
  $("f-drone").addEventListener("change", renderFarm);
  document.querySelectorAll("[data-fs]").forEach((b) => b.addEventListener("click", () => { farm.set = b.dataset.fs; renderFarm(); }));
  document.querySelectorAll("[data-fm]").forEach((b) => b.addEventListener("click", () => { farm.method = b.dataset.fm; renderFarm(); }));
  setFarmView(farm.place ? "place" : "leak");
}
function setFarmView(v) {
  farm.view = v;
  $("fv-place").setAttribute("aria-pressed", v === "place");
  $("fv-leak").setAttribute("aria-pressed", v === "leak");
  $("fc-place").hidden = v !== "place"; $("fc-leak").hidden = v !== "leak";
  $("fp-place").hidden = v !== "place"; $("fp-meth").hidden = v !== "leak";
  $("fp-scen").hidden = v !== "leak"; $("fp-drone").hidden = v !== "leak";
  renderFarm();
}
function renderFarm() {
  if (!farm.lay) return;
  cancelAnimationFrame(farm.raf);
  const L = farm.lay, W = L.farm.width_m, H = L.farm.length_m, pad = 30;
  const X = (x) => pad + x, Y = (y) => pad + H - y;
  const node = Object.fromEntries(L.nodes.map((n) => [n.id, n]));
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W + 2 * pad} ${H + 2 * pad + 10}`);
  const add = (tag, attrs, text, parent = svg) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text !== undefined) e.textContent = text; parent.appendChild(e); return e; };
  for (const sc of L.sectors) {
    const [x0, y0, x1, y1] = sc.bbox;
    add("rect", { x: X(x0), y: Y(y1), width: x1 - x0, height: y1 - y0, fill: css("--panel-2"), stroke: css("--line") });
    add("text", { x: X((x0 + x1) / 2), y: Y(y1) + 14, "text-anchor": "middle" }, `sector ${sc.id}`);
  }
  // pipe probabilities (leak view)
  let probs = {}, sensors = [], scen = null, by = null;
  if (farm.view === "leak" && farm.res) {
    document.querySelectorAll("[data-fs]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.fs === farm.set));
    document.querySelectorAll("[data-fm]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.fm === farm.method));
    scen = farm.res.scenarios[farm.scen]; by = scen.by_sensors[farm.set];
    sensors = by.sensors;
    for (const [pid, v] of Object.entries(by.pipes)) probs[pid] = v[farm.method] || 0;
  } else if (farm.place) {
    const set = farm.place.sets.find((x) => x.n === farm.n);
    sensors = set ? set.nodes : [];
  }
  const pmax = Math.max(1e-9, ...Object.values(probs));
  for (const p of L.pipes) {
    if (p.kind === "pump") continue;
    const a = node[p.from], b = node[p.to];
    const base = p.kind === "main" ? 6 : 3.2;
    add("line", { x1: X(a.x), y1: Y(a.y), x2: X(b.x), y2: Y(b.y), stroke: css("--pipe"), "stroke-width": base, "stroke-linecap": "round", opacity: 0.85 });
    const v = probs[p.id] || 0;
    if (v > 0.005) add("line", { x1: X(a.x), y1: Y(a.y), x2: X(b.x), y2: Y(b.y), stroke: css("--leak"), "stroke-width": base + 2 + 10 * v / pmax, "stroke-linecap": "round", opacity: 0.25 + 0.75 * v / pmax }).appendChild(Object.assign(document.createElementNS(NS, "title"), { textContent: `${p.id}: ${(100 * v).toFixed(1)} %` }));
  }
  if (scen) {
    add("circle", { cx: X(scen.true.x), cy: Y(scen.true.y), r: 13, fill: "none", stroke: css("--ink"), "stroke-width": 2, "stroke-dasharray": "3 3" });
  }
  for (const n of L.nodes) {
    if (!n.candidate) continue;
    const on = sensors.includes(n.id);
    if (on) add("circle", { cx: X(n.x), cy: Y(n.y), r: 8, fill: css("--primary"), stroke: css("--panel"), "stroke-width": 2.5 });
    else add("circle", { cx: X(n.x), cy: Y(n.y), r: 3.5, fill: css("--panel"), stroke: css("--muted") });
  }
  const pump = node[L.farm.pump_node];
  add("text", { x: X(pump.x) + 10, y: Y(pump.y) + 16 }, "pump station");
  // drone
  let route = null;
  if (farm.view === "leak" && farm.drone && $("f-drone").checked) {
    route = farm.drone.routes.find((r) => r.scenario === scen.id && String(r.sensors_n) === farm.set);
    if (route) {
      add("polyline", { points: route.waypoints.map(([x, y]) => `${X(x)},${Y(y)}`).join(" "), fill: "none", stroke: css("--ink"), "stroke-width": 1.6, "stroke-dasharray": "6 4" });
      const dot = add("circle", { r: 6, fill: css("--ink"), stroke: css("--panel"), "stroke-width": 2 });
      const pts = route.waypoints, seg = [0];
      for (let i = 1; i < pts.length; i++) seg.push(seg[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
      const total = seg[seg.length - 1] || 1, t0 = performance.now(), dur = 8000;
      const step = (now) => {
        const d = ((now - t0) % dur) / dur * total;
        let i = seg.findIndex((v) => v >= d); i = Math.max(1, i);
        const f = (d - seg[i - 1]) / Math.max(1e-9, seg[i] - seg[i - 1]);
        dot.setAttribute("cx", X(pts[i - 1][0] + f * (pts[i][0] - pts[i - 1][0])));
        dot.setAttribute("cy", Y(pts[i - 1][1] + f * (pts[i][1] - pts[i - 1][1])));
        if (!$("tab-farm").hidden) farm.raf = requestAnimationFrame(step);
      };
      farm.raf = requestAnimationFrame(step);
    }
  }
  $("farm-map").replaceChildren(svg);
  // panels
  const pct = (v) => v === null || v === undefined ? "–" : `${Math.round(v)} %`;
  if (farm.view === "place" && farm.place) {
    const set = farm.place.sets.find((x) => x.n === farm.n);
    $("f-n-v").textContent = farm.n;
    $("fm-title").textContent = `${farm.n} sensors: ${set.nodes.join(", ")}`;
    $("fp-iso").textContent = pct(set.by_size["3"].isolated_pct);
    $("fp-det").textContent = pct(set.by_size["3"].detected_pct);
    $("fp-det1").textContent = pct(set.by_size["1"].detected_pct);
    $("fp-rob").textContent = set.robust ? `${pct(set.robust.by_size["3"].isolated_pct)} traced` : "–";
    $("fp-cost").textContent = `${set.cost_dt.toLocaleString("en")} DT`;
    $("fp-rec").textContent = `best: ${farm.place.recommended_n}`;
    $("fp-note").textContent = `k·σ = ${farm.place.k} × ${(1000 * farm.place.sigma_bar).toFixed(0)} mbar (${farm.place.sigma_note}). ${farm.place.cost_note}.`;
    $("fm-legend").innerHTML = `<span style="--c:${css("--primary")}">chosen sensor</span><span style="--c:${css("--muted")}">possible spot</span><span style="--c:${css("--pipe")}">pipes</span>`;
  } else if (scen) {
    $("fm-title").textContent = `${scen.title}: ${farm.method === "fused" ? "fused" : farm.method.toUpperCase()} leak probability`;
    $("fs-true").textContent = scen.true.site;
    $("fs-top").textContent = by.detected ? by.top_site : "not detected";
    $("fs-q").textContent = `${scen.true.leak_lps.toFixed(2)} L/s`;
    $("fs-open").textContent = scen.open_sectors.join(" + ");
    const m = farm.res.metrics[farm.res.showcase_case][farm.set];
    $("fp-mt").innerHTML = `<thead><tr><th></th><th>Branch</th><th>Pipe ±1</th><th>Pipe</th></tr></thead><tbody>${
      Object.entries(m).map(([k, v]) => `<tr><td>${k === "fused" ? "Fused" : k.toUpperCase()}</td><td>${pct(v["3+10"].right_branch_pct)}</td><td>${pct(v["3+10"].within_one_hop_pct)}</td><td>${pct(v["3+10"].right_site_pct)}</td></tr>`).join("")}</tbody>`;
    if (route) {
      $("fd-take").textContent = route.takeoff.split(" ")[1] + " sunrise";
      $("fd-time").textContent = `${(route.flight_s / 60).toFixed(1)} min`;
      $("fd-len").textContent = `${Math.round(route.length_m)} m, ${route.pipes.length} pipes`;
      $("fd-hit").textContent = route.true_pipe_in_route ? "yes" : "no";
      $("fd-note").textContent = `${farm.drone.rule}. Real flights: ${farm.drone.next_steps}.`;
    } else {
      ["fd-take", "fd-time", "fd-len", "fd-hit"].forEach((id) => { $(id).textContent = "–"; });
      $("fd-note").textContent = by.detected ? "Drone off." : "Leak not detected: no flight.";
    }
    $("fm-legend").innerHTML = `<span style="--c:${css("--leak")}">leak probability</span><span style="--c:${css("--primary")}">sensor</span><span style="--c:${css("--ink")}">drone route</span><span style="--c:${css("--ink")}">true leak (dashed ring)</span>`;
  }
}

// ------------------------------------------------------------------ tabs + boot
const loaded = {};
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  if (!loaded[name]) {
    loaded[name] = true;
    if (name === "score") loadScoreboard();
    if (name === "m3") loadM3();
    if (name === "farm") loadFarm();
  }
  if (b3.h) b3.h.pause(name !== "bench" || b3.view !== "3d");   // no WebGL work on hidden tabs
  if (name === "bench" && bench.mode === "replay") seek(bench.idx);
  if (name === "m3" && m3Index) showM3($("m3-pick").value);
  if (name === "farm" && farm.lay) renderFarm();
  try { history.replaceState(null, "", `#${name}`); } catch (e) { /* file:// */ }
}

async function boot() {
  drawSchematic();
  renderFrame(null);
  $("bv-3d").addEventListener("click", () => setBenchView("3d"));
  $("bv-2d").addEventListener("click", () => setBenchView("2d"));
  $("b3-home").addEventListener("click", () => { if (b3.h) b3.h.view("board"); });
  setBenchView(b3.view);
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("rp-play").addEventListener("click", togglePlay);
  $("rp-scrub").addEventListener("input", (e) => { stopPlay(); seek(+e.target.value); });
  $("replay-pick").addEventListener("change", (e) => openReplay(e.target.value));
  $("mode-live").addEventListener("click", () => setMode("live"));
  $("mode-replay").addEventListener("click", () => setMode("replay"));
  wireLiveForms();
  const [live, hasReplays] = await Promise.all([backendAvailable(), loadReplayIndex()]);
  if (!live) { $("mode-live").disabled = true; $("mode-live").title = "Live mode needs the laptop backend (not available on GitHub Pages)"; }
  const tab = (location.hash || "#bench").slice(1);
  showTab(["bench", "score", "farm", "m3", "real"].includes(tab) ? tab : "bench");
  await setMode(live ? "live" : "replay");
  if (!live && !hasReplays) $("bench-banner").hidden = false, $("bench-banner").textContent = "No replays exported yet: python -m tools.export_replays --sim";
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (bench.mode === "replay") seek(bench.idx); else liveRender(); if (!$("tab-m3").hidden && m3Index) showM3($("m3-pick").value); }, 150); });
}
boot();
