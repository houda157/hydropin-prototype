# m3/ – pressure-wave method (role 5) – SIMULATION ONLY

M3 runs in simulation only (team decision 21 Nov): the bench cannot produce fast waves.
Assumptions are in `params.yaml` (150 m PE pipe, a = 350 m/s, 25 ms valve closure,
sensor at the valve, 2 kHz). Full data description: `docs/DATA_PIPELINE.md`.

| File | What |
|---|---|
| `moc.py` | Method-of-characteristics solver: reservoir → PE pipe → leak orifice → fast valve. Steady friction, optional **PE wall creep** (generalised Kelvin-Voigt), no column separation. |
| `locate.py` | Locators that need no healthy recording: **time reversal**, **matched-field** (fallback), **echo**, and **wave-speed identification** from the trace. |
| `calibrate.py` | **Field calibration**: fit wave speed, friction and creep from ONE leak-free valve test; accuracy study and model-form test. |
| `cnn.py` | 1D CNN locator (domain-guided, 5 input channels; works with or without a calibration). |
| `echo.py` | Echo vs a leak-free *recording* (validation only). |
| `validate.py` | Solver validation → `out/validation.json`, `report/figures/m3_validation.png`. |
| `sweep.py` | Error vs noise and vs wave-speed error → `out/sweep.json`, `report/figures/m3_accuracy.png` (~8 min). |
| `ve_study.py` | Creep: 3 real pipes × every locator, with and without calibration → `out/ve_study.json`, `report/figures/m3_viscoelastic.png` (~6 min; `plot` redraws only). |
| `plot_focus.py` | Focusing curves → `report/figures/m3_time_reversal.png`. |
| `export_dashboard.py` | M3 tab data → `dashboard/m3/` (format: `dashboard/m3/FORMAT.md`). |
| `tests/` | 45 tests: solver physics, creep, calibration, every locator, the CNN, the dashboard files. |

```powershell
.venv-sim\Scripts\python -m pytest m3/tests
.venv-sim\Scripts\python -m m3.validate
.venv-sim\Scripts\python -m m3.calibrate
.venv-sim\Scripts\python -m m3.calibrate formtest
.venv-sim\Scripts\python -m m3.sweep
.venv-sim\Scripts\python -m m3.ve_study
.venv-sim\Scripts\python -m m3.plot_focus
```

## The recommended M3 procedure
1. **At installation, calibrate once:** close the valve on the leak-free pipe, record, run
   `calibrate.calibrate` → a pipe model with the right wave speed, friction and creep.
2. **Each test:** close the valve, record about 1.3 s at 2 kHz, run **time reversal** (or matched-field)
   with the calibrated model → leak position and an "energy vs position" curve.
3. **Cross-check** with the CNN (no calibration needed).

## How time reversal works here
1. **Residual rate**: d/dt (measured − intact-pipe model), low-passed at 60 Hz. Constant and slow
   offsets (surge height, creep or friction mismatch) drop out; the echo stays sharp.
2. **Back-propagate**: inject the time-reversed residual at the sensor end of the linearised model.
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
| **CNN**, no calibration | 0.92 m | 0.92 m | 2.8 m | **0.92 m** |
| **CNN**, calibrated | 0.72 m | 0.87 m | **1.9 m** | **0.72 m** |

- Solver: the Joukowsky jump and the 4L/a period are exact; it converges as the grid is refined.
- With an assumed `a`, the error ≈ (a error) × (distance from the sensor). **Identifying `a`
  from the reservoir return in the same trace** (within 0.5 %) removes that error.

**PE pipe with wall creep** (`out/ve_study.json`, `m3_viscoelastic.png`; illustrative creep values),
σ = 0.05 m:

| | elastic pipe | typical creep | creep of another shape |
|---|---|---|---|
| Time reversal, no calibration | 0.3 m | ❌ 57 m | ❌ 51 m |
| Time reversal, lab creep | ❌ 58 m | 0.3 m | ❌ 6.7 m |
| **Time reversal, calibrated** | **0.3 m** | **0.3 m** | **0.2 m** |
| **Matched-field, calibrated** | **0.1 m** | **0.2 m** | **0.1 m** |
| CNN, no calibration | 1.0 m | 0.9 m | 1.2 m |
| CNN, calibrated | 0.8 m | 0.9 m | ⚠️ 4.6 m |

- Creep damps and smooths the wave, and shrinks the echo by about 17–27 % (5 % leak at 90 m: 0.103 m → 0.075 m with typical creep).
- **Without calibration, model-based methods fail on creeping pipes:** creep changes the whole
  trace by up to 1.8 m, about 10× the echo. Without calibration the creep must be known to about ±10 %.
- **Calibration fixes time reversal and matched-field on all three pipes**, including one whose
  creep the model family cannot reproduce (fit off by 0.41 m RMS, yet location within 0.5 m).
- Calibration accuracy in simulation (`out/calibration.json`, 48 pipes, σ = 0.05 m): wave speed
  0.003 %, friction 0.4 %, creep 0.001 (worst case). Optimistic: the simulated pipes are in the model family.

**CNN v3** (`out/cnn_eval.json`: 9,000 training / 1,000 validation / 2,000 test pipes; elastic and
creeping, calibrated or not): about 1 m on every kind of pipe at low noise. At σ = 0.1 m: 1.2–1.5 m
for leaks ≥ 4 %, 3.3 m for 2–4 %, but 17.6 m for 1–2 % leaks, whose echo (~0.05 m) is lost in noise.

### CNN
```powershell
.venv-sim\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-sim\Scripts\python -m m3.cnn data        # 12,000 simulated pipes, ~10 min (125 MB, not committed)
.venv-sim\Scripts\python -m m3.cnn train 100   # 100 epochs on CPU, ~45 min -> out/cnn.pt, out/cnn_eval.json
```

## Limits to state in the report
- Blind zones: about a·Tc/2 ≈ 4 m next to the sensor; about 3–12 % of L at the far (reservoir) end.
- One sensor, one straight pipe. No junctions, no trapped air.
- Creep parameters are **illustrative** (3 elements, τ = 0.05 / 0.5 / 1.5 s, total 3 × 10⁻¹⁰ 1/Pa).
- The calibrated CNN was trained with synthetic calibration errors; on the "other shape" pipe the real
  calibration error is of another kind and it fails (4.6 m). Fix: real calibration on every training pipe (~7 h).
- Tiny leaks (1–2 %) need a quieter sensor, longer averaging or repeated tests.
- Leaks are known-size orifices; noise is white Gaussian.

## Dashboard files (M3 tab)
`python -m m3.export_dashboard` writes `dashboard/m3/index.json` and 4 showcase cases (wave animation,
sensor trace, time-reversal and matched-field curves, every method's estimate). Format and suggested
use: `dashboard/m3/FORMAT.md`. Mentor review: done (Moez approved).
