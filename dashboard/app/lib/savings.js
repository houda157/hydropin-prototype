// Money saved by finding a leak early (spec: "Money saved"). Every result is an estimate built
// from the farm figures in dashboard/config.js; a missing figure gives null, shown as "—".
const KEYS = ["farm_flow_m3_per_h", "irrigation_hours_per_day", "days_to_notice_without_hydropin", "price_dt_per_m3"];
const r2 = (x) => Math.round(x * 100) / 100;

export function moneyReady(scale) {
  return !!scale && KEYS.every((k) => Number.isFinite(scale[k]) && scale[k] > 0);
}

/** Litres lost on the bench, scaled to the reference farm by the share of the flow. */
export function benchLostM3(lostL, baseLpm, farmFlowM3PerH) {
  if (!Number.isFinite(lostL) || !Number.isFinite(baseLpm) || baseLpm <= 0 || !Number.isFinite(farmFlowM3PerH)) return null;
  return (lostL / 1000) * farmFlowM3PerH / (baseLpm * 0.06);
}

export function leakMoney({ share, lostM3 }, scale) {
  if (!moneyReady(scale) || !Number.isFinite(share) || !Number.isFinite(lostM3)) return null;
  const leakM3PerH = share * scale.farm_flow_m3_per_h;
  const wouldLoseM3 = leakM3PerH * scale.irrigation_hours_per_day * scale.days_to_notice_without_hydropin;
  const savedM3 = Math.max(0, wouldLoseM3 - lostM3);
  return { leakM3PerH: r2(leakM3PerH), wouldLoseM3: r2(wouldLoseM3), savedM3: r2(savedM3), savedDt: r2(savedM3 * scale.price_dt_per_m3) };
}

/** A leak episode (backend row or demo leak) as the numbers the money formula needs. */
export function leakNumbers(leak, scale) {
  const share = Number.isFinite(leak.max_leak_lpm) && leak.base_lpm > 0 ? leak.max_leak_lpm / leak.base_lpm : null;
  const lostM3 = Number.isFinite(leak.lost_m3) ? leak.lost_m3
    : benchLostM3(leak.lost_l, leak.base_lpm, scale ? scale.farm_flow_m3_per_h : NaN);
  return { share, lostM3, status: leak.status };
}

export function seasonSavedDt(leaks, scale) {
  if (!moneyReady(scale)) return null;
  let total = 0;
  for (const l of leaks) {
    if (l.status !== "fixed") continue;
    const m = leakMoney(l, scale);
    if (m) total += m.savedDt;
  }
  return r2(total);
}
