# Dashboard data files – v1.1

Every JSON file the static dashboard reads, the command that writes it and its required keys. These are the
files GitHub Pages serves (paths relative to `dashboard/`). Bench frames, REST, WebSocket and
the replay file itself are in `contract/api.md`; this file references them and does not repeat
them. Changing a format means bumping `version` and updating the code that reads it.

**Rule for everything below:** a file made from simulation carries `"simulation": true`, and the
page shows a "Simulation" label wherever it is used.

| File | Made with | Read by (tab) |
|---|---|---|
| `replays/index.json`, `replays/<id>.json` | `python -m tools.export_replays --sim` or `--db data/hydropin.db` | Bench (replay) |
| `scoreboard.json` (bench) / `scoreboard_sim.json` (simulated) | same | Scoreboard |
| `farm/layout.json` | `python -m farm.model.export_layout` | Farm |
| `farm/placement.json` | `python -m farm.placement.optimise` | Farm (placement) |
| `farm/results.json` | `python -m farm.methods.m1_gnn` then `python -m farm.methods.results` | Farm (leak) |
| `farm/drone.json` | `python -m farm.drone.dispatch` | Farm (leak + drone) |
| `m3/index.json`, `m3/m3_case_XX.json` | `python -m m3.export_dashboard` | M3 |

Regenerate the farm files in this order: `farm.leaks.generate` → `farm.placement.optimise` →
`farm.methods.m1_gnn` → `farm.methods.results` → `farm.drone.dispatch` →
`farm.explorer.build_data`. Once the bench σ is measured, pass `--sigma-bar <σ>` to the first one.

---

## Replays and scoreboard

- **Replay file** and **`replays/index.json`**: `contract/api.md` ("Replay file").
  - Index entries: `id, kind (sim|bench), simulation, label, opening, notes, duration_s,
    detected, delay_s, branch, false_alarm, split, blind, file`.
- **Scoreboard** (`version` "1.1"):

| Key | Content |
|---|---|
| `simulation` | true for the simulated scoreboard and for rehearsal databases (notes starting "SIMULATED") |
| `notes` | free text |
| `headline` | "test split only (runs the model never trained on)" when `data/model.json` has a split, else "all runs" |
| `split_counts` | `{train, test}` or null |
| `summary` | on the headline runs: `leak_runs, detected, detection_rate, watch_or_leak_rate, branch_accuracy, tap_accuracy, median_delay_s, clean_runs, false_alarm_runs, healthy_hours, false_alarms_per_hour` |
| `summary_all_runs` | same keys over every run, or null |
| `per_method` | `{fused, flow, m2}` → `{detection_rate, median_delay_s, false_alarms_per_hour}`. A method alone "fires" when its own score stays above `tau2` for `n_consecutive` samples |
| `confusion` | `taps[true][L1|L2|L3|missed]` and `branches[true][A|B|missed]`; rows = truth, columns = detector |
| `per_tap` | `{L1: {runs, detected, branch_ok}, …}` |
| `per_opening` | `{small: {runs, detected, watched}, …}` |
| `blind` | `{runs, summary, events[]: {id, label, detected, delay_s, branch, false_alarm}}`, misses included |
| `runs[]` | one per run: `id, label, simulation, split, blind, detected, watched, delay_s, branch, branch_ok, tap_top, leak_lpm, measured_leak_lpm, opening, false_alarm, faults, healthy_s, false_episodes{fused, flow, m2}, methods_alone{flow, m2: {detected, delay_s}}` |

## `farm/layout.json`

| Key | Content |
|---|---|
| `farm` | `area_ha, width_m, length_m, pump_node, source_node, irrigation_shifts` (lists of open sectors) |
| `nodes[]` | `id, x, y, elev, kind, sector, branch, candidate`. Kinds: `reservoir, pump_out, main, sector_head, manifold, submain_end`. `candidate` = a realistic sensor spot |
| `pipes[]` | `id, from, to, kind, sector, branch, leak_candidate, length, diameter`. Kinds: `pump, main, sector_link, sector_valve, submain_1, submain_2` |
| `sectors[]` | `id, name, row, side, nodes, bbox [x0, y0, x1, y1], design_flow_lps` |

Coordinates are in metres, y pointing north; the pump station is at the south edge. Branch is
`main` or `sector_<s>`.

## `farm/placement.json`

| Key | Content |
|---|---|
| `version, simulation, source, n_scenarios, candidates[]` | — |
| `sigma_bar, sigma_note, k` | detection threshold k·σ |
| `cost_per_node_dt, cost_note` | 292 DT; assumption until the BOM is confirmed |
| `rules` | text of the detected / isolated / distinguishable / robust rules |
| `method` | text |
| `recommended_n, target, target_met` | — |
| `sets[]` (N = 1…10) | `n, nodes[], greedy_nodes[], detected_pct, isolated_pct, by_size{"1","3","10": {detected_pct, isolated_pct}}, distinguishable_pct, cost_dt, robust{detected_pct, isolated_pct, by_size{"3","10"}}` |

The 3 / 6 / 10 sets are also in `farm/placement/out/sets.json` (`{sets: {"3": [...], "6": [...], "10": [...]}}`).

## `farm/results.json`

| Key | Content |
|---|---|
| `version, simulation, source` | — |
| `split` | worlds 0–6 train, 7–9 test |
| `sigma_bar` | — |
| `noise_cases` | `single`: one reading; `avg_60`: 1-minute average |
| `showcase_case` | `avg_60` |
| `methods` | `["m2", "m1", "fused"]` |
| `m1_note` | — |
| `fusion` | text |
| `metrics[case][n][method]` | groups `"all" "1" "3" "10" "3+10"`, each `{n, detected_pct, right_site_pct, within_one_hop_pct, right_branch_pct}`; test worlds only |
| `scenarios[]` (10 showcase test leaks) | `id, scenario_id, title, true{site, kind, branch, pipes[], x, y, size_pct, leak_lps}, open_sectors[], by_sensors{"3","6","10": {sensors[], detected, top_site, pipes{pipe_id: {m2, m1, fused}}}}` |

Pipe probabilities sum to about 1 per method. Values below 5e-4 are left out.

## `farm/drone.json`

| Key | Content |
|---|---|
| `version, simulation, source, rule` | — |
| `base` | `{node, x, y, note}` |
| `alt_m, speed_mps, spacing_m, battery_s` | — |
| `sunrise` | `{date, local, site}` |
| `next_steps` | text |
| `routes[]` | `scenario` (an id in `results.json`), `title, sensors_n, true_pipes[], true_pipe_in_route, prob_covered, pipes[]` (in flight order), `waypoints[[x, y], …]` (m, from base back to base), `length_m, flight_s, fits_one_battery, takeoff` |

## M3

Full description: `dashboard/m3/FORMAT.md`. Required keys:

- **`index.json`:** `version, simulation, label, methods{tr, mfp, echo, cnn}`, and
  `cases[]` with `id, file, title, story, pipe, x_true_m, error_m{…}, size_kb`.
- **Case file:** `version, simulation, id, title, story, pipe{…}, leak{…}, valve{…}, timing{…},
  frames{dt_s, t_s, x_m, H_m}, sensor{fs_hz, noise_sigma_m, t0_s, dt_s, H_m, model_H_m},
  tr{x_m, energy, x_est_m}, mfp{x_m, match, x_est_m}, estimates_m{…}, error_m{…}, model{…},
  wave_speed_identified_mps`.
