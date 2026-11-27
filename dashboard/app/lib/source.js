// Live data: the laptop backend (Kmar's FastAPI) for the test bench, shown as a 2-sector mini-farm.
// Snapshot = { stateResponse: {state, frame}, leaks, sectors, kind, scale }.
import { FARM_SCALE } from "../../config.js";

const OFFLINE = { state: "OFFLINE", frame: null };

function every(ms, fn) {
  const h = setInterval(fn, ms);
  if (h && typeof h.unref === "function") h.unref();   // Node tests; browsers ignore it
  return h;
}

/** "live" when the page is served by the backend with the bench detector, else "demo". */
export async function detectSource(base = "..", fetchImpl = fetch) {
  const ctrl = typeof AbortController === "function" ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), 2000) : null;
  try {
    const r = await fetchImpl(`${base}/health`, ctrl ? { signal: ctrl.signal } : undefined);
    if (!r.ok) return "demo";
    const h = await r.json();
    return h && h.ok && h.bench_detector ? "live" : "demo";
  } catch {
    return "demo";
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export function liveSource(base = "..", { fetchImpl = fetch, intervalMs = 2000 } = {}) {
  let cb = null, handle = null, lastLeaks = [];
  const getJson = async (url) => {
    const r = await fetchImpl(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  };
  const snap = (stateResponse, leaks) => ({ stateResponse, leaks, sectors: ["A", "B"], kind: "live", scale: FARM_SCALE });
  async function poll() {
    let s;
    try {
      const [state, leaks] = await Promise.all([getJson(`${base}/api/state`), getJson(`${base}/api/leaks?limit=20`)]);
      lastLeaks = leaks;
      s = snap(state, leaks);
    } catch {
      s = snap(OFFLINE, lastLeaks);
    }
    if (cb) cb(s);
  }
  return {
    kind: "live",
    start(onSnapshot) { cb = onSnapshot; poll(); handle = every(intervalMs, poll); },
    stop() { cb = null; if (handle) clearInterval(handle); handle = null; },
    async markFixed(id) {
      try { await fetchImpl(`${base}/api/leaks/${id}/fixed`, { method: "POST" }); } finally { await poll(); }
    },
  };
}
