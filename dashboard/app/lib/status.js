import { severity } from "./severity.js";

const IRRIGATING = new Set(["SETTLING", "LEARNING", "HEALTHY", "WATCH", "LEAK"]);

/** What the farmer should see, from the backend's /api/state and /api/leaks (or the demo). */
export function toView(stateResponse, leaks, sectors) {
  const frame = stateResponse && stateResponse.frame;
  const state = stateResponse ? stateResponse.state : "OFFLINE";
  const current = (leaks || []).find((l) => l.status === "open" || l.status === "checking") || null;
  const view = {
    status: "ok", irrigating: false, sector: null, severity: null, share: null, whereTap: null, confirmed: true,
    leakId: current ? current.id : null, leakStatus: current ? current.status : null,
    foundTs: current ? current.started_ts : null, sectors,
  };
  if (!frame || state === "OFFLINE") return { ...view, status: "offline" };
  view.irrigating = IRRIGATING.has(state);
  if (state === "LEAK") {
    view.status = "leak";
    view.sector = frame.branch || null;
    view.severity = severity(frame.leak_lpm, frame.flow_base_lpm);
    view.share = frame.flow_base_lpm > 0 ? frame.leak_lpm / frame.flow_base_lpm : null;
    const best = Object.entries(frame.loc || {}).sort((a, b) => b[1] - a[1])[0];
    view.whereTap = best && best[1] >= 0.6 ? best[0] : null;
  } else if (current) {
    // an episode still open while the sensors do not show it (pump stopped, baseline re-learned):
    // never an all-clear, the farmer must still be able to reach "I fixed it"
    view.status = "leak";
    view.sector = current.branch || null;
    view.confirmed = false;
  }
  return view;
}
