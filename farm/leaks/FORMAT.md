# Farm leak dataset – format v1.0 (draft, to agree with roles 2 and 4)

**Everything here is simulation** (WNTR model of a 50 ha drip farm; assumptions in
`farm/model/params.yaml`). Regenerate with `python -m farm.leaks.generate` (about 30 s).

## Units and conventions
- Pressure in **bar** (gauge), flow in **L/s**, coordinates in **m**.
- `node_order` (in `meta.json`) = the 28 junctions of the farm. Every per-node array uses it.
  It is also the order of `gnn/graph.json` nodes.
- `candidate_order` (in `meta.json`) = the 16 candidate sensor sites (pump outlet, 3 main
  junctions, 6 sector heads upstream of the sector valves, 6 sub-main ends). It is the row
  order of `dP.npy`.
- A **world** = one irrigation shift (2 sectors open) plus one random draw of roughness,
  elevations and clogging: the "real farm". The **twin** = the nominal model.
- Scenario ids are stable for the same params and arguments.
- σ = `meta.json:sigma_bar`. It is a **placeholder (0.01 bar)** until role 1 measures the
  bench σ. Re-run with `--sigma-bar <value>`.

## Files (`farm/leaks/out/`)

| File | Shape / type | Content | Main user |
|---|---|---|---|
| `meta.json` | object | units, σ, counts, `node_order`, `candidate_order`, runtime | all |
| `scenarios.csv` | S rows | `scenario_id, world_id, config_id, open_sectors, world_seed, leak_kind (node/pipe), leak_at (node or pipe id), branch (main / sector_<s>), sector, x, y, size_pct, q_target_lps, area_m2, leak_lps (realised), pump_lps, healthy_pump_lps` | all |
| `candidates.json` | list | per candidate: `row, id, node_index, kind, branch, sector, x, y` | role 2 |
| `dP.npy` | float32 [16 × S] | **ΔP(i, s)**: leak pressure − healthy pressure in the same world, noise-free. Apply your own k·σ. | role 2 (placement) |
| `dP_all.npy` | float32 [S × 28] | same, at every junction | role 2 / 4 |
| `healthy.npy` | float32 [W·20 × 28] | noisy healthy samples (20 per world) | role 4 (farm M2) |
| `healthy_index.csv` | rows | `sample, world_id, config_id` for `healthy.npy` | role 4 |
| `gnn/graph.json` | object | nodes (`index, id, x, y, elev, kind, sector, branch, candidate`), edges (`id, source, target, kind, sector, branch, length, diameter`) | role 4 |
| `gnn/X.npy` | float32 [S × 28] | **residual vs measured healthy baseline**: leak pressure + noise − mean of the world's 20 healthy samples. This is the default GNN input; mask to your sensor nodes. | role 4 |
| `gnn/X_twin.npy` | float32 [S × 28] | residual vs the **uncalibrated nominal twin** (includes the model-reality gap, std about 0.15 bar). For robustness experiments only. | role 4 |
| `gnn/X_clean.npy` | float32 [S × 28] | noise-free ΔP (= `dP_all`) | role 4 |
| `gnn/y_node.npy` | int [S] | leak junction index, or −1 for a pipe leak | role 4 |
| `gnn/y_pipe.json` | list[str] | leak pipe id for pipe leaks, `""` for node leaks | role 4 |
| `gnn/sector_open.npy` | bool [S × 28] | node is in an open sector (or on the main) | role 4 |

## Grid (v1.0)
- 3 shifts ({1,2}, {3,4}, {5,6} open) × 10 worlds × 23 pressurised leak sites × sizes
  1 / 3 / 10 % of the open-sector flow = **2,070 scenarios**.
- Leak sites: every pressurised junction, plus the midpoint of every main and sub-main pipe.
  Sites behind a closed sector valve are skipped (60 site-shift pairs). A leak there loses
  no water while the sector is off.
- Perturbed models for the robustness check: `farm/model/perturbed/farm_p00…p09.inp`.
  They use other seeds than the dataset.
- The map for the dashboard is `farm/model/layout.json`, copied to `dashboard/farm/layout.json`.

## Physics notes for users
- Any leak lowers **every** pressure by about the same amount, because the pump slides
  down its curve. A 1 % leak gives about 0.02 bar everywhere. Location comes from the small
  differences between nodes; remove the common mode (as on the bench).
- With pressure-dependent demand, a leak also makes the drippers draw a bit less. The pump
  flow therefore rises by less than the leak flow.
- With σ = 0.01 bar and k = 3: 1 % leaks are seen by at least one candidate in about 23 %
  of scenarios, while 3 % and 10 % leaks are seen in 100 %.
