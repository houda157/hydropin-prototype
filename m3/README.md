# m3/ – pressure-wave method (role 5) – SIMULATION ONLY

M3 runs in simulation only (team decision 21 Nov): the bench cannot produce fast waves.
Assumptions are in `params.yaml` (150 m PE pipe, a = 350 m/s, 25 ms valve closure,
sensor at the valve, 2 kHz).

| File | What |
|---|---|
| `moc.py` | Method-of-characteristics solver: reservoir → PE pipe → leak orifice → fast valve. Steady friction, no column separation. |
| `locate.py` | Locators that need no healthy recording: **time reversal**, **matched-field** (fallback), **echo**, and **wave-speed identification** from the trace. |
| `echo.py` | Echo vs a leak-free *recording* (validation only). |
| `validate.py` | Solver validation → `out/validation.json`, `report/figures/m3_validation.png`. |
| `sweep.py` | Error vs noise and vs wave-speed error → `out/sweep.json`, `report/figures/m3_accuracy.png` (~5 min). |
| `plot_focus.py` | Focusing curves → `report/figures/m3_time_reversal.png`. |
| `tests/` | 23 tests: solver physics, and every locator. |

```powershell
.venv-sim\Scripts\python -m pytest m3/tests
.venv-sim\Scripts\python -m m3.validate
.venv-sim\Scripts\python -m m3.sweep
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
- Solver: the Joukowsky jump and the 4L/a period are exact; it converges as the grid is refined.
- Noise: time reversal mean error < 0.5 m up to σ = 0.1 m of head, and matched-field < 0.25 m.
  Both fail at σ = 0.2 m, which is about the echo's height (0.23 m).
- Wave speed: with an assumed `a`, the error ≈ (a error) × (distance from the sensor):
  about 3 m at ±5 %, about 6 m at −10 %. **Identifying `a` from the reservoir return in the
  same trace** (within 0.5 %) keeps time reversal at 0.27 m across ±10 %.

## Limits to state in the report
- Blind zones: about a·Tc/2 ≈ 4 m next to the sensor. With an assumed `a`, about 12 % of L at the far
  (reservoir) end; it shrinks once `a` is identified.
- One sensor, one straight pipe, steady friction only. No junctions, no trapped air,
  and no PE viscoelastic damping, which would weaken the echoes (risk 2 in the blueprint).
- Leaks are known-size orifices; the leak size does not move the focus.

Next: 1D CNN on the same simulated traces, compared on the same sweep; `dashboard/m3/*.json`
exports (pressure along the pipe over time, sensor trace, focusing curve, estimates); mentor review.
