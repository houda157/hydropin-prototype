// Reference values for the "at farm scale" line on the Bench tab (market lead).
// Leave a value null and the line stays hidden. Every number here is an assumption until
// the market lead fills it in with a source; the line says "estimate".
export const FARM_SCALE = {
  area_ha: null,              // reference farm, e.g. 50
  m3_per_ha_season: null,     // irrigation water per hectare per season
  price_dt_per_m3: null,      // water price (DT per m3)
  source: "",                 // where the values come from
};
