# m3/ – pressure-wave method (role 5) – SIMULATION ONLY

M3 runs in simulation only (team decision 21 Nov): the bench cannot produce fast waves.
Assumptions are in `params.yaml` (150 m PE pipe, a = 350 m/s, 25 ms valve closure,
sensor at the valve, 2 kHz). Full data description: `docs/DATA_PIPELINE.md`.

| File | What |
|---|---|
| `moc.py` | Method-of-characteristics solver: reservoir → PE pipe → leak orifice → fast valve. Steady friction, optional **PE wall creep** (generalised Kelvin-Voigt), no column separation. |
| `locate.py` | Locators that need no healthy recording: **time reversal**, **matched-field** (fallback), **echo**, and **wave-speed identification** from the trace. |
| `cnn.py` | 1D CNN locator (domain-guided; uses the wave speed identified from the trace). |
| `echo.py` | Echo vs a leak-free *recording* (validation only). |
| `validate.py` | Solver validation → `out/validation.json`, `report/figures/m3_validation.png`. |
| `sweep.py` | Error vs noise and vs wave-speed error → `out/sweep.json`, `report/figures/m3_accuracy.png` (~6 min). |
| `ve_study.py` | What PE creep does to every locator → `out/ve_study.json`, `report/figures/m3_viscoelastic.png` (~6 min; `plot` redraws only). |
| `plot_focus.py` | Focusing curves → `report/figures/m3_time_reversal.png`. |
| `tests/` | 34 tests: solver physics, creep, every locator, the CNN. |

```powershell
.venv-sim\Scripts\python -m pytest m3/tests
.venv-sim\Scripts\python -m m3.validate
.venv-sim\Scripts\python -m m3.sweep
.venv-sim\Scripts\python -m m3.ve_study
.venv-sim\Scripts\python -m m3.plot_focus
```

## How time reversal works here
1. **Residual rate**: d/dt (measured − intact-pipe model), low-passed at 60 Hz. Constant
   offsets (such as the surge height, which scales with `a`) drop out.
2. **Back-propagate**: inject the time-reversed residual at the sensor end of the
   linearised model.
3. **Imaging**: at each position, correlate the back-propagated field with the incident
   field the closure sent through that point. They line up only where the leak re-radiated
   the wave → `|E(x)|` peaks at the leak.

This is the zero-lag imaging-condition form of time reversal, on the first round trip.
**Confirm with the mentor that it matches ref [2].**

## Results (simulation, 5 % leak, 6 positions × 3 noise draws)

**Elastic pipe** (`out/sweep.json`, `m3_accuracy.png`), mean error:

| | σ = 0.02 m | σ = 0.1 m | σ = 0.2 m | model `a` 5 % wrong |
|---|---|---|---|---|
| Time reversal, assumed `a` | 0.08 m | 0.35 m | 8.2 m | 3.1 m |
| Time reversal, `a` identified from the trace | 0.27 m | 0.44 m | 8.2 m | **0.27 m** |
| Matched-field | 0.0 m | 0.22 m | 8.8 m | 3.2 m |
| Echo | 0.9 m | 19 m | 34 m | 3.7 m |
| **CNN** (`a` identified) | 0.99 m | 1.1 m | **1.8 m** | **0.99 m** |

- Solver: the Joukowsky jump and the 4L/a period are exact; it converges as the grid is refined.
- With an assumed `a`, the error ≈ (a error) × (distance from the sensor). **Identifying `a`
  from the reservoir return in the same trace** (within 0.5 %) removes that error.
- The **CNN** (trained on 6,750 simulated pipes, tested on 1,500 it never saw,
  `out/cnn_eval.json`): 0.65 m at low noise and 1.5 m at σ = 0.1 m in the covered zone, 99 %
  of leaks within 5 m. It is the most robust to heavy noise; time reversal and matched-field
  are the most precise at normal noise.

**PE pipe with wall creep** (`out/ve_study.json`, `m3_viscoelastic.png`; illustrative creep values):
- Creep damps and smooths the wave: after 5 s the swing is 17.6 m instead of 29.1 m, and the
  echo of a 5 % leak is about 20 % smaller.
- **A model that ignores creep fails** (all methods, about 57–64 m error). The creep changes
  the whole trace by up to 1.8 m, about 10× the echo, so every method "finds" the mismatch next
  to the sensor.
- **A creep-aware model works again:** time reversal 0.14–0.56 m, matched-field 0.0–0.39 m
  (σ = 0.02–0.1 m).
- Creep must be known to about **±10 %** (time reversal stays < 0.7 m from −10 % to +20 %;
  far leaks fail beyond that). In practice: **calibrate creep once per pipe** (a leak-free valve
  test at installation, or lab tests of the pipe), as in the published PE studies.

### CNN
```powershell
.venv-sim\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-sim\Scripts\python -m m3.cnn data     # 9,000 simulated traces, ~4 min (96 MB, not committed)
.venv-sim\Scripts\python -m m3.cnn train    # 40 epochs on CPU, ~10 min -> out/cnn.pt, out/cnn_eval.json
```

## Limits to state in the report
- Blind zones: about a·Tc/2 ≈ 4 m next to the sensor. With an assumed `a`, about 12 % of L at the far
  (reservoir) end; it shrinks once `a` is identified.
- One sensor, one straight pipe. No junctions, no trapped air.
- Creep parameters are **illustrative** (3 elements, τ = 0.05 / 0.5 / 1.5 s, total 3 × 10⁻¹⁰ 1/Pa).
  The CNN was trained on elastic pipes only, so it needs retraining with creep.
- Leaks are known-size orifices (the leak size does not move the focus); noise is white Gaussian.

Next: `dashboard/m3/*.json` exports (pressure along the pipe over time, sensor trace,
focusing curve, estimates); mentor review (time-reversal formulation and creep values).
