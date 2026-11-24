# m3/ – pressure-wave method (role 5) – SIMULATION ONLY

M3 runs in simulation only (team decision 21 Nov): the bench cannot produce fast waves.
Assumptions are in `params.yaml`.

| File | What |
|---|---|
| `moc.py` | Method-of-characteristics solver: reservoir → PE pipe → leak orifice → fast valve (sensor at the valve). Steady friction, no column separation. |
| `echo.py` | Simplest locator: leak echo time vs a leak-free reference, d = a·t/2. |
| `validate.py` | Validation numbers (`out/validation.json`) and `report/figures/m3_validation.png`. |
| `tests/` | Joukowsky jump, 4L/a period, friction damping, slow closure, steady state and mass balance, grid convergence, echo at 4 positions. |

```powershell
.venv-sim\Scripts\python -m pytest m3/tests
.venv-sim\Scripts\python -m m3.validate
```

Validated (noise-free) results: Joukowsky jump and the 4L/a period match to machine
precision; the echo places a 5 % leak at 100 m within 0.25 m at 2 kHz. The echo is small
(0.23 m against a 17.8 m surge), so noise matters.

Next: time reversal (fallback: matched-field processing), noise and wave-speed error
sweeps, the 1D CNN, and `dashboard/m3/*.json` exports. The mentor (Moez Louati) reviews
the results before the video.
