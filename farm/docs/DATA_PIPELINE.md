# Farm data pipeline – how the leak data is made, what it contains, how it is used

**Everything in this document is simulation.** No data here comes from a real farm or from
the bench. Every value is set in `farm/model/params.yaml` or in the code named below.
`farm/leaks/FORMAT.md` is the short reference for consumers; this document explains every step.

```
farm/model/params.yaml
      │
      ▼
build_farm.build_network(params, seed, open_sectors) ──► WNTR model of the farm
      │                                    │
      │                                    ├──► export_layout.py ──► layout.json (+ dashboard/farm/layout.json)
      │                                    │                         farm.inp, perturbed/farm_p00…p09.inp
      │                                    └──► plot_farm.py ──────► report/figures/farm_layout.png
      ▼
leaks/scenarios.build_grid() ──► 30 worlds × 69 scenarios = 2,070 scenarios
      │
      ▼
leaks/simulate.simulate_world()  (one process per world, 15 in parallel)
      │   healthy run + nominal-twin run + one run per leak
      ▼
leaks/generate.py ──► farm/leaks/out/  (scenarios.csv, dP.npy, healthy.npy, gnn/…, meta.json)
      │
      ├──► sensor placement (dP.npy, candidates.json, perturbed/*.inp)
      ├──► GNN M1 + farm M2 (gnn/*, healthy.npy)
      └──► Farm tab map (layout.json)
```

---

## 1. The physics model

### 1.1 Tool

**WNTR 1.5.0** (Python, Sandia National Laboratories; uses the EPANET network format),
run with its own `WNTRSimulator`, which supports leaks. Each run is **one steady state**
(`wn.options.time.duration = 0`). WNTR solves, at every junction and pipe:
- **mass balance:** inflow = outflow + demand + leak;
- **head loss:** Hazen-Williams (`headloss: H-W`);
- **pump:** the head-flow curve;
- **pressure-dependent demand (PDD):** a dripper gets its full flow at ≥ 12 m of pressure,
  less below that (`required_pressure_m` 12, `minimum_pressure_m` 0, exponent 0.5);
- **leak:** Q = Cd·A·√(2 g h) with Cd = 0.75 and h = the pressure head at the leak.

All WNTR units are SI (m, m³/s; pressure in m of water). **Outputs are converted to bar**
with 1 m = 0.0980665 bar (`M_TO_BAR`), and flows to L/s.

### 1.2 The farm (`build_farm.describe_farm()` + `build_network()`)

```
    E5 ─ A5 ─ B5═H5─M3─H6═B6 ─ A6 ─ E6      row 3 (north), y = 595.8 m
                    │
    E3 ─ A3 ─ B3═H3─M2─H4═B4 ─ A4 ─ E4      row 2, y = 357.5 m
                    │
    E1 ─ A1 ─ B1═H1─M1─H2═B2 ─ A2 ─ E2      row 1 (south), y = 119.2 m
                    │
                   PS  pump outlet (350, 0)
                    │  PUMP
                   R0  farm basin (350, −30)
```
Main road at x = 350 m. West sectors are odd (1, 3, 5), east sectors are even (2, 4, 6).

**Nodes (29):**

| Id | Kind | Position | Role |
|---|---|---|---|
| R0 | reservoir | (350, −30) | basin, fixed head 98.0 m |
| PS | pump_out | (350, 0) | pump outlet |
| M1–M3 | main | (350, y_row) | main junctions (valve boxes) |
| H{s} | sector_head | 6 m from the main | before the sector valve: **always pressurised** |
| B{s} | valve_out | 8 m from the main | after the sector valve |
| A{s} | manifold | 120 m from the main | half the sector demand |
| E{s} | submain_end | 290 m from the main | half the sector demand, end of the sub-main |

**Links (28):**

| Id | From → to | Length | Inner Ø | HW C | Notes |
|---|---|---|---|---|---|
| PUMP | R0 → PS | – | – | – | 3-point head curve: (0, 39.9 m), (70 L/s, 30 m), (140 L/s, 0) |
| MN1 | PS → M1 | 119.17 m | 0.235 m | 145 | PVC 250 main |
| MN2, MN3 | M1 → M2, M2 → M3 | 238.33 m | 0.235 m | 145 | main |
| L{s} | M → H{s} | 6 m | 0.150 m | 145 | short link to the sector head |
| V{s} | H{s} → B{s} | 2 m | 0.150 m | 145 | **the sector valve** (minor loss 2.0); open or closed |
| S{s}a | B{s} → A{s} | 112 m | 0.150 m | 145 | sub-main 1, PVC 160 |
| S{s}b | A{s} → E{s} | 170 m | 0.110 m | 140 | sub-main 2, PE 125 |

**Elevation** of every node = 100 + 0.004·y + 0.0015·(x − 350) m (gentle slope to the north
and east).

**Demand:** sector flow = (50 ha / 6) × 1.5 mm/h = **34.72 L/s**, split 50 % at A{s} and 50 %
at E{s}. Two sectors open → 69.4 L/s.

**Sector configuration** (`set_sector_config`): the valves of the open sectors are `Open`;
the others are `Closed` and their H/B/A/E demands are set to 0. Three shifts
(`open_configs`): **config 0 = sectors {1, 2}, config 1 = {3, 4}, config 2 = {5, 6}**.

**Checked result** (`python -m farm.model.build_farm`): every shift delivers 69.4 L/s, the
pump outlet sits at 28.2 m (2.76 bar), and open manifolds get 12.2–23.8 m.

### 1.3 "Real farm" vs "twin": the perturbation (`build_network(seed=…)`)

`seed=None` gives the **nominal model = the digital twin**. An integer seed makes a
**world**: a plausible real farm that differs from the twin. With
`rng = numpy.random.default_rng(seed)`, the draws are, in this order:
1. **clogging:** one factor per sector (sectors 1…6), Uniform(0.8, 1.0), which multiplies
   that sector's demand;
2. **elevation error:** one per junction (in node order), + Normal(0, 0.5 m);
3. **roughness:** one per pipe (in link order, pump excluded), HW C × Normal(1, 0.05).

The reservoir and the pump curve are not perturbed.

---

## 2. The scenario grid (`leaks/scenarios.py`)

### 2.1 Leak sites (`leak_sites(meta, open_sectors)`)

- **Node sites:** every junction that is pressurised under the shift. That is PS, M1–M3,
  all six H{s} (before their valve), and B/A/E of the two open sectors = **16 nodes**.
- **Pipe sites:** the midpoint of every main and sub-main pipe on the pressurised side:
  MN1–MN3, plus S{s}a and S{s}b of the two open sectors = **7 pipes**. L{s} (6 m) and V{s}
  (the valve) are not leak sites; node leaks at their ends cover them.
- **Skipped:** sites behind a closed valve (B/A/E and S{s}a/b of the 4 closed sectors) = 20 per
  shift, **60 in total**. They lose no water while the sector is off.

→ **23 sites per shift.**

### 2.2 Worlds and scenario order (`build_grid`)

```
for config c in 0, 1, 2:
    for k in 0 … 9:                         # n_seeds = 10
        world: world_id = running index (0…29), seed = 20261124 + 1000·c + k
        for each of the 23 sites (16 nodes in node order, then 7 pipes in link order):
            for size in 1 %, 3 %, 10 %:
                scenario_id = running index (0…2069)
```
3 × 10 × 23 × 3 = **2,070 scenarios**. Scenario ids are stable for the same params.

---

## 3. Simulating one world (`leaks/simulate.simulate_world()`)

For each world (parallel `multiprocessing.Pool`, 15 workers):

1. **Healthy world run:** build the world (its seed and shift) and run it. This gives:
   - `p_h`: pressure at the 28 junctions (bar);
   - `healthy_pump`: pump flow;
   - `demand_h`: total delivered demand.
2. **Twin run:** build the **nominal** model (no seed) with the same shift and run it →
   `p_twin` (bar).
3. **Healthy samples:** 20 noisy copies, `p_h + Normal(0, σ)`, using
   `default_rng([20261124, 7, world_id])`. Their mean is the **baseline** (what a
   monitoring system would measure before any leak).
4. **For each scenario of the world:**
   1. **Target leak flow:** `q_target` = size % × `demand_h`. Example: 1 % ≈ 0.69 L/s,
      10 % ≈ 6.9 L/s.
   2. **Where:**
      - node site: rebuild the world and use that junction; h = its healthy pressure head;
      - pipe site: rebuild the world and split the pipe at its midpoint with
        `wntr.morph.split_pipe(wn, P, P_2, LK_P)`, giving a new junction `LK_P`;
        h = mean healthy head of the pipe's two end nodes; position = the midpoint.
   3. **Hole size:** `area` = q_target / (0.75 × √(2 g max(h, 0.1))) m².
   4. **Run:** `add_leak(area, Cd = 0.75, start_time = 0)`, then run. This gives:
      - `p_leak` at the 28 original junctions (the split node `LK_P` is not included);
      - the realised leak flow;
      - the pump flow.
   5. **Sensor noise:** `noise` = Normal(0, σ) on each of the 28 values, using
      `default_rng([20261124, 11, scenario_id])`; `measured = p_leak + noise`.
   6. **The three residuals:**
      - `dP` = p_leak − p_h: the true leak fingerprint, no noise;
      - `X` = measured − baseline: what a sensor system sees after baselining on its own
        healthy data (like the bench);
      - `X_twin` = measured − p_twin: compared with the uncalibrated twin, so it includes
        the model-reality gap.

σ = `sigma_bar` = **0.01 bar, a placeholder** until the bench noise is measured. Re-run with
`python -m farm.leaks.generate --sigma-bar <value>`.

**Note:** the realised leak flow is 81–100 % of the target, because the leak lowers the
pressure that drives it. Under PDD the drippers also draw slightly less, so the pump flow
rises by **less** than the leak flow.

---

## 4. The output files (`leaks/generate.py` → `farm/leaks/out/`)

**Orders used everywhere:**
- **node order** (28 junctions; `meta.json:node_order`; also `gnn/graph.json` nodes):
  `PS, M1, H1, B1, A1, E1, H2, B2, A2, E2, M2, H3, B3, A3, E3, H4, B4, A4, E4, M3, H5, B5, A5, E5, H6, B6, A6, E6`
- **candidate order** (16 sensor sites; `meta.json:candidate_order`; rows of `dP.npy`):
  `PS, M1, H1, E1, H2, E2, M2, H3, E3, H4, E4, M3, H5, E5, H6, E6`
- **scenario order:** by `scenario_id` (0…2069), the order of section 2.2.

### 4.1 `scenarios.csv`: one row per scenario (2,070 rows)

| Column | Type | Meaning |
|---|---|---|
| `scenario_id` | int | 0…2069, row index in every per-scenario array |
| `world_id` | int | 0…29 (10 worlds per shift) |
| `config_id` | int | 0, 1, 2 (shift) |
| `open_sectors` | str | `"1;2"`, `"3;4"` or `"5;6"` |
| `world_seed` | int | seed of the perturbation (20261124 + 1000·c + k) |
| `leak_kind` | str | `node` or `pipe` |
| `leak_at` | str | junction id (node leak) or pipe id (pipe leak, at its midpoint) |
| `branch` | str | `main` or `sector_<s>`: **the label for "which branch"** |
| `sector` | int / empty | 1…6, empty for the main |
| `x`, `y` | float, m | leak position |
| `size_pct` | float | 1, 3 or 10 |
| `q_target_lps` | float | target leak flow (L/s) |
| `area_m2` | float | orifice area used |
| `leak_lps` | float | realised leak flow (L/s) |
| `pump_lps` | float | pump flow with the leak |
| `healthy_pump_lps` | float | pump flow of the same world without the leak |

### 4.2 Arrays

| File | Shape, type | Content (bar) |
|---|---|---|
| `dP.npy` | [16 × 2070] float32 | `dP` at the 16 candidate sites; **row = candidate, column = scenario** |
| `dP_all.npy` | [2070 × 28] float32 | `dP` at all junctions; row = scenario |
| `healthy.npy` | [600 × 28] float32 | 20 noisy healthy samples per world, worlds in order 0…29 |
| `healthy_index.csv` | 600 rows | `sample, world_id, config_id` for each row of `healthy.npy` |
| `gnn/X.npy` | [2070 × 28] float32 | `X` = measured − baseline (noisy) |
| `gnn/X_twin.npy` | [2070 × 28] float32 | `X_twin` = measured − nominal twin (noisy, model gap; std ≈ 0.15 bar) |
| `gnn/X_clean.npy` | [2070 × 28] float32 | `dP`, identical to `dP_all.npy` |
| `gnn/y_node.npy` | [2070] int64 | node index of a node leak, −1 for a pipe leak |
| `gnn/y_pipe.json` | list of 2070 str | pipe id of a pipe leak, `""` for a node leak |
| `gnn/sector_open.npy` | [2070 × 28] bool | true if the node is on the main or in an open sector |

Nodes behind a closed valve read 0 in every array.

### 4.3 JSON files

- **`candidates.json`:** list of 16 objects `{row, id, node_index, kind, branch, sector, x, y}`.
  `row` = row in `dP.npy`, `node_index` = column in the [·× 28] arrays.
- **`gnn/graph.json`:** `nodes` = 28 objects `{index, id, x, y, elev (nominal), kind, sector,
  branch, candidate}`; `edges` = 27 objects `{id, source, target, kind, sector, branch,
  length, diameter}` (every link except the pump). `source`/`target` are node indices.
  Sector-valve edges (`kind = sector_valve`) are closed when their sector is off; see
  `sector_open.npy`.
- **`meta.json`:** `format_version` (1.0), `simulation` (true), `generated_utc`,
  `wntr_version`, `runtime_s` (30.2), `units`, `sigma_bar`, `sigma_note`, `n_scenarios` (2070),
  `n_worlds` (30), `n_sites_skipped_not_pressurised` (60), `sizes_pct`, `node_order`,
  `candidate_order`, `params_version`.

### 4.4 Model files (`export_layout.py`)

- **`farm/model/layout.json`** (copied to `dashboard/farm/layout.json`): `version` 1.0,
  `simulation` true, `label`, `units`, `farm` (area, size, pump and source node, shifts),
  `nodes[]` `{id, x, y, elev, kind, sector, branch, candidate}`, `pipes[]` `{id, from, to,
  kind, sector, branch, leak_candidate, length, diameter}`, `sectors[]` `{id, name, row, side,
  nodes, bbox, design_flow_lps}`.
- **`farm/model/farm.inp`:** the nominal model, all sectors open (EPANET format).
- **`farm/model/perturbed/farm_p00…p09.inp`:** 10 extra worlds, seeds 20361124 + k
  (= base + 100000 + k, never used in the dataset), all sectors open.

---

## 5. How the data is used

| Consumer | Reads | Exactly what it does with it |
|---|---|---|
| **Sensor placement** (`farm/placement/`) | `dP.npy`, `candidates.json`, `scenarios.csv` (`branch`, `open_sectors`), `meta.json` (σ) | A set of sensors **detects** scenario s if \|dP[i, s]\| > k·σ (k = 3) at one of them. It **isolates** s if, once the common drop is removed, the sensor with the largest extra drop is on the leak's branch (a sensor in a closed sector counts as main pipe). Greedy, then swaps, then a genetic search over the 16 candidates → `dashboard/farm/placement.json` |
| Placement robustness | the perturbed-model seeds (`farm/model/perturbed/*.inp`) | Re-simulates the leaks on 10 farm versions the placement never saw and reports the same scores |
| **GNN (M1)** (`farm/methods/m1_gnn.py`) | `gnn/graph.json`, `gnn/X.npy` (or `X_clean.npy` + noise), `gnn/sector_open.npy`, `scenarios.csv` | Node features = residual at the chosen sensor nodes (0 elsewhere), the same with the common mode removed, has-sensor flag, `sector_open`, elevation; edges from `graph.json`; target = leak site (junction or pipe); **split by world** (versions 0–6 train, 7–9 test) |
| **Farm M2** (`farm/methods/m2.py`) | `gnn/X.npy`, `scenarios.csv` | Common mode removed; one fingerprint per leak site from the training worlds; likelihood of each site for a test residual |
| Sensor sets | the 3-, 6- and 10-sensor sets from the placement tool | M2, M1 and their fusion are trained and scored with those sensor nodes only → `dashboard/farm/results.json`, then the drone routes (`farm/drone/`) |
| **Farm tab** | `dashboard/farm/layout.json` | Draws the map (nodes, pipes, sectors) and marks the candidate sites |
| Report | `report/figures/farm_layout.png`, `params.yaml` | The one farm figure; the list of assumptions |
| Tests (`farm/tests/`) | the model + a `--quick` run | Pressure band, full demand, mass balance, leaks lower every pressure, file shapes |

**What the data already shows** (σ = 0.01 bar, k = 3):
- every leak lowers all pressures by about the same amount: a 1 % leak gives about −0.02 bar at
  the pump outlet. Location is in the small differences between sites;
- leaks seen by at least one candidate at 3σ: 1 % → 23 %, 3 % → 100 %, 10 % → 100 %.

---

## 6. Re-making everything

```powershell
.venv-sim\Scripts\python -m farm.model.build_farm       # check pressures per shift
.venv-sim\Scripts\python -m farm.model.export_layout    # layout.json, farm.inp, perturbed/*.inp
.venv-sim\Scripts\python -m farm.model.plot_farm        # report figure
.venv-sim\Scripts\python -m farm.leaks.generate         # the dataset (~30 s)
.venv-sim\Scripts\python -m pytest farm/tests
```
All randomness uses fixed seeds, so re-running gives the same files.

## 7. Limits of this data (say them in the report)

- **The farm is invented:** layout, pipe sizes, pump, slope and irrigation rate are all
  assumptions (`params.yaml`).
- **Drippers are lumped:** 2 demand points per sector, so no leak inside a lateral is
  modelled. This matches the product scope: laterals are detected per sector, not located.
- **No pressure regulators,** which real sectors often have; they would hide upstream changes.
- **Steady state only:** one snapshot per scenario, no time series, no pump start/stop.
- **σ is a placeholder** (0.01 bar), and the noise is white Gaussian with no drift.
