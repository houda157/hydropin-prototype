// The screen the app opens on. An explicit known hash wins; ?demo=fixed starts on the repair.
export const ROUTE_HASHES = ["#/home", "#/where", "#/fixed", "#/alerts", "#/map", "#/savings", "#/help"];

export function initialHash(params, hash) {
  if (ROUTE_HASHES.includes(hash)) return hash;
  return params.get("demo") === "fixed" ? "#/fixed" : "#/home";
}
