// Demo data (GitHub Pages, no backend): a scripted farm morning, always labelled "Demo farm".
// Same Snapshot shape as the live source, at farm scale: leaks carry lost_m3 directly.
import { DEMO_FARM_SCALE } from "../config.js";

const LEAK_AT_MS = 8000;      // the leak appears 8 s after the page opens
const CHECKING_MS = 4000;     // after "I fixed it", the sensors confirm 4 s later

const today = () => new Date().toISOString().slice(0, 10);

// two leaks found and fixed earlier in the season, for the history and the savings
const PAST = [
  { id: 102, branch: "A", started_ts: "2026-11-25T06:40:00Z", ended_ts: "2026-11-25T10:10:00Z",
    base_lpm: 100, max_leak_lpm: 4, lost_m3: 2.4, pump_stopped: 0, user_fixed_ts: "2026-11-25T10:05:00Z", status: "fixed" },
  { id: 101, branch: "C", started_ts: "2026-11-08T07:15:00Z", ended_ts: "2026-11-08T12:00:00Z",
    base_lpm: 100, max_leak_lpm: 6, lost_m3: 5, pump_stopped: 0, user_fixed_ts: "2026-11-08T11:50:00Z", status: "fixed" },
];

export function demoSource({ now = () => Date.now(), start = "normal" } = {}) {
  const t0 = now() - (start === "normal" ? 0 : LEAK_AT_MS);
  let fixedAt = start === "fixed" ? now() - CHECKING_MS : null;
  let cb = null, handle = null;

  function snapshot() {
    const t = now() - t0;
    const leaking = t >= LEAK_AT_MS;
    const status = fixedAt === null ? "open" : now() - fixedAt >= CHECKING_MS ? "fixed" : "checking";
    const leaks = [...PAST];
    let stateResponse = { state: "HEALTHY", frame: { state: "HEALTHY", flow_base_lpm: 100, leak_lpm: 0 } };
    if (leaking) {
      const current = {
        id: 1, branch: "B", started_ts: `${today()}T06:12:00`, ended_ts: status === "fixed" ? new Date(now()).toISOString() : null,
        base_lpm: 100, max_leak_lpm: 8, lost_m3: status === "fixed" ? 4.6 : 3, pump_stopped: 0,
        user_fixed_ts: fixedAt === null ? null : new Date(fixedAt).toISOString(), status,
      };
      leaks.unshift(current);
      if (status !== "fixed") {
        stateResponse = { state: "LEAK", frame: { state: "LEAK", branch: "B", flow_base_lpm: 100, leak_lpm: 8,
          lost_l: 0, loc: { L1: 0.1, L2: 0.7, L3: 0.2 } } };
      }
    }
    return { stateResponse, leaks, sectors: ["A", "B", "C", "D"], kind: "demo", scale: DEMO_FARM_SCALE };
  }

  const source = {
    kind: "demo",
    tick() { if (cb) cb(snapshot()); },
    start(onSnapshot) {
      cb = onSnapshot;
      source.tick();
      handle = setInterval(source.tick, 500);
      if (handle && typeof handle.unref === "function") handle.unref();
    },
    stop() { if (handle) clearInterval(handle); handle = null; },
    async markFixed(id) { if (id === 1 && fixedAt === null) fixedAt = now(); source.tick(); },
  };
  return source;
}
