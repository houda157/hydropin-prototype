import { SEVERITY } from "../../config.js";

/** How severe a leak is, from the share of the pumped water it loses. */
export function severity(leakLpm, baseLpm, thr = SEVERITY) {
  if (!Number.isFinite(leakLpm) || !Number.isFinite(baseLpm) || baseLpm <= 0) return null;
  const share = leakLpm / baseLpm;
  if (share >= thr.large_from) return "large";
  if (share >= thr.medium_from) return "medium";
  return "small";
}
