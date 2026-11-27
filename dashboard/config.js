// Farm reference figures (market lead). Used by the dashboard's "at farm scale" line and by the
// farmer app's money-saved formula (docs/superpowers/specs/2026-11-27-farmer-app-design.md).
// placeholder: true = example figures until the market lead's real ones (with a source) arrive;
// the app labels every money figure "estimate". Set a value to null to hide the money ("—").
export const FARM_SCALE = {
  area_ha: 50,                          // reference farm
  m3_per_ha_season: null,               // irrigation water per hectare per season (dashboard line)
  price_dt_per_m3: 0.25,                // water + pumping energy, DT per m3
  farm_flow_m3_per_h: 200,              // pump flow while irrigating
  irrigation_hours_per_day: 8,          // hours of irrigation per day in season
  days_to_notice_without_hydropin: 10,  // how long a buried leak runs before anyone sees it
  placeholder: true,
  source: "example figures (placeholders) until the market lead's figures",
};

// The farmer app's demo farm (GitHub Pages, no backend): always shown as "estimate".
export const DEMO_FARM_SCALE = {
  area_ha: 50,
  farm_flow_m3_per_h: 200,
  irrigation_hours_per_day: 8,
  days_to_notice_without_hydropin: 10,
  price_dt_per_m3: 0.25,
};

// Severity from the share of the pumped water lost (leak_lpm / base_lpm).
export const SEVERITY = { medium_from: 0.05, large_from: 0.15 };

// "Take me there" opens the phone's maps app here (placeholder until a real farm).
export const FARM_LOCATION = { lat: 36.80, lon: 10.18, placeholder: true };
