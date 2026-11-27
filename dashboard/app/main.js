// HydroPin farmer app: picks the data source (laptop backend = live test bench, else demo), keeps
// the latest snapshot and puts the screens of screens.js on the page. Hash routes, no build step.
// URL options for filming: ?demo=leak|fixed, ?source=demo, ?lang=fr|ar|en.
import { demoSource } from "./demo.js";
import { detectLang, isRtl, loadLang, saveLang, t } from "./lib/i18n.js";
import { detectSource, liveSource } from "./lib/source.js";
import { toView } from "./lib/status.js";
import * as S from "./screens.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const qlang = params.get("lang");

const state = {
  lang: ["fr", "ar", "en"].includes(qlang) ? qlang : detectLang(navigator.language, loadLang()),
  snap: null, sheet: null, lastFixedId: null, source: null,
};

const ROUTES = {
  "#/home": S.homeScreen, "#/where": S.whereScreen, "#/fixed": S.fixedScreen, "#/alerts": S.alertsScreen,
  "#/map": S.mapScreen, "#/savings": S.savingsScreen, "#/help": S.helpScreen,
};
const SHEETS = { details: S.detailsSheet, profile: S.profileSheet, sensors: S.sensorsSheet, savings: S.savingsSheet, plan: S.planSheet };
const TABS = [["#/home", "home", "tab.home"], ["#/map", "map", "tab.map"], ["#/savings", "money", "tab.savings"], ["#/help", "help", "tab.help"]];
const TAB_OF = { "#/where": "#/home", "#/fixed": "#/home", "#/alerts": "#/home" };

function applyLang() {
  document.documentElement.lang = state.lang;
  document.documentElement.dir = isRtl(state.lang) ? "rtl" : "ltr";
}

function ctx() {
  const snap = state.snap;
  return { snap, view: toView(snap.stateResponse, snap.leaks, snap.sectors), lang: state.lang, now: new Date(), lastFixedId: state.lastFixedId };
}

// only touch the page when the HTML changed: the demo ticks every 0.5 s and a rebuild would restart the water animation
const last = { screen: null, tabs: null, sheet: null };
function put(id, html) {
  if (last[id] === html) return;
  last[id] = html;
  $(id).innerHTML = html;
}

function render() {
  if (!state.snap) return;
  const c = ctx();
  const route = ROUTES[location.hash] ? location.hash : "#/home";
  put("screen", ROUTES[route](c));
  const active = TAB_OF[route] || route;
  put("tabs", TABS.map(([href, icon, key]) =>
    `<a href="${href}" class="tab${active === href ? " on" : ""}"${active === href ? ' aria-current="page"' : ""}>`
    + `<svg class="ic" aria-hidden="true"><use href="#i-${icon}"/></svg>${S.esc(t(state.lang, key))}</a>`).join(""));
  const sheet = state.sheet && SHEETS[state.sheet]
    ? `<div class="dim" data-action="close"></div><div class="panel" role="dialog" aria-modal="true"><div class="grab"></div>`
      + `${SHEETS[state.sheet](c)}<button class="btn link" data-action="close">${S.esc(t(state.lang, "btn.close"))}</button></div>`
    : "";
  $("sheet").hidden = !sheet;
  put("sheet", sheet);
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-action],[data-lang]");
  if (!el || !state.snap) return;
  if (el.dataset.lang) {
    state.lang = el.dataset.lang;
    saveLang(state.lang);
    applyLang();
    render();
    return;
  }
  const action = el.dataset.action;
  if (SHEETS[action]) { state.sheet = action; render(); return; }
  if (action === "close") { state.sheet = null; render(); return; }
  if (action === "fixed") {
    const id = ctx().view.leakId;
    state.sheet = null;
    if (id !== null && id !== undefined) {
      state.lastFixedId = id;
      location.hash = "#/fixed";
      await state.source.markFixed(id);
    }
    render();
    return;
  }
  if (action === "share") {
    const text = S.shareText(ctx());
    if (navigator.share) navigator.share({ title: "HydroPin", text }).catch(() => {});
    else if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {});
  }
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.sheet) { state.sheet = null; render(); } });
window.addEventListener("hashchange", () => { state.sheet = null; render(); window.scrollTo(0, 0); });

async function boot() {
  applyLang();
  const demo = params.get("demo");
  const kind = demo || params.get("source") === "demo" ? "demo" : await detectSource("..");
  state.source = kind === "demo" ? demoSource({ start: ["leak", "fixed"].includes(demo) ? demo : "normal" }) : liveSource("..");
  if (demo === "fixed") state.lastFixedId = 1;
  state.source.start((snap) => { state.snap = snap; render(); });
}

boot();

// installable app: cache the app shell so it opens offline (see sw.js)
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
