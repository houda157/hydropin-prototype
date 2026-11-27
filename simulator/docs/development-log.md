# Development log

Everything built, tried and abandoned, in the order it was done. The log uses the build-step numbers; they map to the topics as follows:

| Step | Topic (results folder) |
|---|---|
| 0 | architecture, parameters, contracts |
| 1 | physics |
| 2 | hydraulics |
| 3 | sensors |
| 4 | pressure-waves |
| 5 | leak-echoes |
| 6 | m3-time-reversal |
| 7 | m2-pca |
| 8 | m1-gnn |
| 9 | sensor-placement |
| 10 | fusion |
| 11 | demo |
| 12 | prototype-bench |
| 12b | bench-waves |

## Step 0 – Architecture and skeleton (2026-11-17)
- Layered package `hydropin` (config/contracts → physics → network → steady → transient → sensors → methods → fusion/placement → viz).
- `config/params.yaml`: 55 entries (45 names, material properties per material) mirroring section 0 of the math note, each with unit, symbol, meaning, source, plausible range and a `verify` flag. `C_ELEC` left `null` (to source).
- `hydropin.config`: validated loader; out-of-range values and unknown values fail loudly; temperature tables interpolated, never extrapolated.
- `hydropin.contracts`: NetworkSpec, Scenario, SteadyResult, TransientResult, SensorSeries, MethodOutput, Decision, SensorMessage (MQTT).
- Tests: architecture layering, params ↔ math-note name coverage (both directions), contract validation.
- Status: waiting for team validation.

## Step 1 – Physics library (2026-11-17)
- Decisions D1–D5 of Step 0 accepted with the recommended options ("continue everything").
- `physics/`: friction (laminar, Blasius, Swamee–Jain, Colebrook reference, Darcy–Weisbach, Hazen–Williams, minor), emitters (non-PC and PC drippers, Christiansen, equivalent lateral, explicit lateral), leaks (orifice, emitter, FAVAD), pump/energy/cost, waves (c1, wave speed, air, Joukowsky, period, leak admittance/reflection, resolution, cavitation).
- `oracles/` package: checks defined once, used by pytest and by the report (31 checks, all pass).
- `viz/style.py` (validated CVD-safe palette, 2 px lines, ringed markers, hairline grid) and `viz/report.py`.
- Corrected two oracle *specifications* (not tolerances): 1.8 first tested Hazen–Williams at Re = 1500, where it is only 17 % low; moved to Re = 500, representative of the end of a lateral (65 % low). 1.29 used a leak admittance too large for the small-leak limit; reduced to 1e-12.
- Math note §2.3: PC dripper outside its range made explicit (orifice-like, continuous).
- Findings: Swamee–Jain ≤ 2.8 % from Colebrook; equivalent lateral within 0.5 % of the explicit lateral; a 100 m Ø16 lateral loses 2.85 m (–15 % dripper flow); M3 needs a valve closing in < 25–30 ms for < 5 m resolution.

## Step 2 – Networks and steady-state twin (2026-11-17)
- `network/generators.py`: bench placeholder and parametric demo farm (4 sectors × 3 blocks × 10 laterals of 80 m, 0.96 ha); YAML save/load. Specs and EPANET .inp files in `config/networks/`.
- `network/builder.py`: NetworkSpec → WNTR/EPANET (D-W, viscosity from temperature relative to EPANET's 1.0219e-6 m²/s reference, lateral-block emitters fitted on the equivalent-lateral law, 3-point pump curve).
- `steady/solver.py`: shifts (sector valves), leaks (pipe split + orifice emitter), clogging, roughness/elevation draws → SteadyResult.
- Found while building: WNTR stores D-W roughness in metres (written as mm in .inp); EPANET's reference viscosity is 1.0219e-6 m²/s, not 1.0e-6 (0.4 % head-loss error otherwise).
- `contracts.Node.outlet_coeff` added (optional field, allowed).
- 13 oracle checks pass. Finding: on a single line a 5 % leak drops all pressures by 71–80 cm, but the localising part is only ≈ 9 cm.

## Step 3 – Scenarios, virtual sensors, dataset (2026-11-17)
- `sensors/model.py` (low-rate, high-rate, flow meter, σ_tot, detectability), `steady/scenarios.py` (Monte Carlo sampler), `sensors/dataset.py` (4,000-sample dataset in `data/farm_dataset.npz`), `sensors/stream.py` (MQTT messages).
- New parameters `N_AVG`, `TEMP_COMP_RESIDUAL`, `SIGMA_Q` added to params.yaml and to the math note (§0.6, §2.7, §3.3), keeping the two-way name test green.
- Mistake caught: the three new parameters were first appended under `decision:` instead of `sensors:`; moved.
- Leaks are only sampled where water flows during the shift; lateral leaks are modelled at the block node.
- Findings: temperature compensation cuts σ_tot from 13 cm to 1.5 cm; smallest detectable leak by pressure ≈ 65–90 L/h (compensated); the flow balance alone is limited by model uncertainty (≈ 1,300 L/h); leak signatures are ≈ 60 cm common-mode and ≤ 29 cm differential.

## Steps 4–5 – Transient solver (2026-11-17)
- `transient/moc.py`: vectorised MOC (Courant-1 grid, per-pipe wave-speed adjustment, junctions/emitters/leaks/outlets, reservoir, pump, time-varying excitation valve, cavitation monitor), quasi-steady friction, Brunone–Vardy unsteady friction, generalised Kelvin–Voigt viscoelasticity (implicit in H_P via modified C', B').
- TSNet abandoned as oracle: 0.3.1 breaks under NumPy 2; in a NumPy-1 env (Python 3.11) it mis-initialises valve-to-reservoir (39 m) and crashes on valve-to-junction. Replaced by the exact analytical solution (error 1e-15 m) and grid convergence (order ≈ 1.9).
- Bug found by oracle 4.8: minor losses were missing in the MOC (farm drifted 13 cm in 3 s); fixed (< 1 mm).
- Bug found by oracle 5.4: unsteady friction used sgn(Q·∂Q/∂x) instead of the math-note form sgn(Q)|∂Q/∂x|, which made damping *weaker*; fixed to follow the math note.
- `physics/friction.friction_factor` now broadcasts per-element roughness/diameter.

## Step 6 – M3 time reversal (2026-11-17)
- `transient/frequency.py` (Laplace-domain line model, transfer matrices, viscoelastic wave speed) and `methods/m3_timereversal.py`.
- Iterations (all kept in the report): (1) plain frequency-domain match swamped by cm-level model mismatch; (2) adding sensor lag + whitening still dominated by the pulse itself; (3) final: time-domain matched filter on the Laplace-inverted model, gated pulse, first round trip only, 20 ms high-pass, wave speed identified from the data, N_p pulses averaged, SNR with a 1.5 mm model-mismatch floor.
- New params `SIGMA_HF`, `N_PULSES`; math note §5.9 made explicit.
- Result: 2 % leaks located to 0.25 m at 10–140 m; no false alarm; size within 17 %.

## Step 7 – M2 PCA/SVD (2026-11-17)
- `methods/features.py`, `methods/signatures.py`, `methods/m2_pca.py`.
- First attempt on absolute readings across random farm states: TPR 15 % at 5–10 % leaks (leak ≈ cleaner drippers along the pump curve). Dataset extended with a paired healthy baseline (same farm state, another day); features = change vs baseline.
- k chosen above the noise floor (not 95 % variance), alarm on SPE or T²; math note §4.1 updated.
- Result: 100 % detection of ≥ 1 % leaks, 1.8 % false alarms, right sector 99 % for ≥ 5 % leaks, median error 5 m.
- Bug caught: Python late-binding in a per-shift lambda used the last shift's sensor set.

## Step 8 – M1 graph neural network (2026-11-17)
- `methods/m1_gnn.py`: plain-PyTorch GCN (dense normalised adjacency, 21 nodes), edge + block heads, weighted BCE, early stopping, `fine_tune` with λ‖θ − θ_sim‖². PyTorch Geometric not needed.
- Result: 100 % detection of ≥ 1 % leaks at 0.5 % false alarms; localisation weaker than M2 (right sector 83 % vs 99 %, median 15 m vs 5 m). A tuned variant did not help: data-limited (≈ 35 leaks per location).

## Step 9 – Sensor placement (2026-11-17)
- `placement/optimizer.py`: Φ = coverage + isolation, greedy, exhaustive, genetic algorithm.
- Bug caught: zero signatures (sensors in closed sectors) scored perfect isolation; unseen leaks now score 0. Isolation made explicit in math note §7 (mean nearest-angle, same-place pairs ignored).
- Oracle 9.7 first expected 100 % coverage of 0.5 % leaks; the physics says 90 % is the ceiling even with a sensor on every junction. Corrected to "as good as every junction".

## Step 10 – Fusion and decision (2026-11-17)
- `fusion/decision.py`: quality gate (own gate + outlier with ≥ 3 methods), log-odds fusion, separate location weights (math note §6 updated), bootstrap band, log/watch/alert.
- Honest limit: the dataset (leaks ≥ 1 %) is separated perfectly, so calibration is only weakly tested; next dataset should go down to 0.1 %.

## Step 11 – Demo layer (2026-11-17)
- `scripts/step_11_viewer.py` → self-contained `hydropin_twin_viewer.html` + `mqtt_stream_sample.jsonl` (valid SensorMessage lines).

## Step 12 – Prototype board twin (2026-11-21)
- Source: 3rd-phase hardware list + sketch of 18 Nov 2026 (2 Swagelok S sensors, R365 pump, brass Hall flow sensor, ADS1115, 3 taps). The 16 Nov cost sheet describes a different board; not modelled.
- `physics/fittings.py`, `network/prototype.py`, `steady/board.py`, `sensors/board.py`; math note §0.7 and §10; 63 parameters in `prototype`.
- Contract change (additive): pipe materials `PVC_FLEX` (pump hose) and `SS316` (Swagelok tees).
- Bugs caught: valve centre nodes left unconnected (EPANET error 233); EPANET ignores 'Closed' on a check-valve pipe, so shut taps leaked; EPANET's 'Closed' keeps a tiny conductance (0.03 % mass-balance error) → shut valves are now removed from the model.
- Oracle 12.7 first compared in the transition zone of the hose (EPANET cubic vs our linear blend): moved to a fully laminar setting; residual 0.03 % = EPANET's g = 9.80665.
- Noise budget: the ripple first vanished exactly (150 Hz alias averaged over whole cycles); the ripple phase now follows the motor speed (supply wander), which is physical.
- Findings: L2 ≡ L3 with the current sensors; hand-cracked ½" taps leak ≥ 30 % of the flow; F0 firmware reads −28 % before calibration; P1 − P2 cancels the adapter wander.

## Step 12 update + Step 12b – flat board, 3D bench, board transients (2026-11-22)
- Board lies flat on the table (team decision, 22 Nov): PB_TILT = 0; sensors point up whatever the tilt (sensor_dz no longer × sin θ). Oracle 12.11 replaced (flat board: all fittings at z_B; 12.11b stem height).
- Viewer: "3D bench" tab (three.js bundled inline, scripts/viewer3d/): table, board, every fitting, valves turning with the sliders, sensors, pump, bucket, electronics, laptop dashboard; pipe colours, water speed and drips from the twin.
- transient/moc.py (backward compatible, Steps 4–6 tests unchanged): lumped valves solved exactly (stable when shut), pipe → emitter taps, pump exponent n and speed s(t), RampEvent.
- Bug caught: with the pump stopped, the Newton bracket capped the pump-node head at the reservoir level, pulling the board into suction; bracket now max(hs + s h0, S/W).
- transient/board.py + Step 12b: V1 slam, M3 pulse, L1 burst, pump power cut. Joukowsky at V1 matches to 0.03 %; time of flight L1 → P1 within one grid step.
- Viewer 3D tab: slow-motion pressure-wave player (pipes coloured along their length), P1/P2 chart with ADS1115 samples.


## Move into the prototype repository (2026-11-24)
- Simulation moved into `hydropin-prototype/simulator/`.
- Python package renamed `hydropin` → `hydropin_sim`, so it cannot clash with the repository's shared `hydropin/` package. All imports, the layer test and the docs were updated; behaviour unchanged (207 tests pass).
- Math, architecture, step-report and prototype-twin notes copied into `docs/` and converted from Obsidian to GitHub Markdown; `tests/test_params.py` now checks names against `docs/simulation-math.md`.
- `viz/report.py` writes GitHub Markdown (standard image links, links to `docs/`).
- The bench wiring schematic is in `reports/schematic/`. It shows one ESP32 using its built-in Wi-Fi (the two-ESP32 LoRa variant stays behind `LORA = False` in `scripts/schematic/bench_schematic.py`).

## Reorganised by topic (2026-11-24)
- Results, run scripts, oracles and tests renamed by topic instead of build step (`results/m2-pca/`, `run/m2_pca.py`, `oracles/m2_pca.py`, `tests/test_m2_pca.py`, …); each results page is the folder's `README.md`.
- Demo viewer moved to `demo/hydropin_viewer.html`; wiring schematic to `results/wiring/` (`run/wiring.py`).
- Package moved from `src/hydropin_sim/` to `hydropin_sim/`; results pages regenerated from the scripts.
