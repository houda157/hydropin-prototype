# Calibration (bench rev 1)

The pressure fits are now from the actual sensors + 20k/10k dividers. The flow
gain is still provisional and must be measured.

```
PT1, branch A: 0..6 bar, 0-10 V, 20k/10k
    V_sensor = V_ads * 3.0
    bar      = 0.0 + 0.6 * V_sensor

PT2, branch B: -1..1.6 bar, 0-10 V, 20k/10k
    V_sensor = V_ads * 3.0
    bar      = -1.0 + 0.26 * V_sensor

Flow main: 5 V pulse, 10k/20k -> 3.33 V at GPIO27
    flow_lpm = (pulses / dt_s) / 7.5 * FLOW_GAIN   # FLOW_GAIN provisional 1.5
```

These live in `hydropin/config.py` and `firmware/include/config.h`. They must
stay equal; `tests/test_firmware_config.py` guards the shared constants.
`data/calibration.json` is a read-only mirror of `hydropin/config.py` (the brief's format); regenerate
it after any change (command in `hydropin.config.calibration_dict`), `tests/test_calibration_json.py`
checks they match.

## Flow sensor

Datasheet class: `F (Hz) = 7.5 * Q (L/min)`, about 450 pulses per litre.

1. Fill a container of known volume (2 L is better than 1 L).
2. Count pulses while it fills, at the normal operating flow.
3. `pulses_per_litre = total_pulses / litres`.
4. Update `FLOW_K_PULSES_PER_LITRE` in both config files.
5. Compare raw datasheet flow with measured flow:
   `raw_lpm = (pulses / seconds) / 7.5`.
6. If raw is consistently off by a factor, that factor is `FLOW_GAIN`.

```powershell
python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
```

At 2 Hz one pulse is 0.4 L/min; the firmware counts over a 2 s window
(0.1 L/min resolution). Keep `FLOW_MEASURE_WINDOW_S` and `FLOW_WINDOW_MS` in sync.

## Pressure sensors

### PT1 (A0, 0..6 bar)
1. Apply 0, 2, 4, 6 bar with a gauge.
2. Record `raw.pressure_adc` at each point.
3. `V_ads = adc / 32767 * 4.096`, `V_sensor = V_ads * 3.0`.
4. Fit `bar = a * V_sensor + b`; expected `a = 0.6`, `b = 0`.
5. Update `PRESSURE_GAIN` and `PRESSURE_OFFSET_BAR` if the fit differs.

### PT2 (A1, -1..1.6 bar)
1. Apply -1, 0, 1.6 bar (or the closest gauge points).
2. Record `raw.pressure_b_adc`.
3. Fit `bar = a * V_sensor + b`; expected `a = 0.26`, `b = -1.0`.
4. Update `PRESSURE_B_GAIN` and `PRESSURE_B_OFFSET_BAR`.

```powershell
python -m tools.calibrate pressure --point 0:0 --point 8889:2 --point 17778:4 --point 26667:6
```

`/api/export.csv` already contains `raw_pressure_adc`, `raw_pressure_b_adc`,
`pressure_bar`, and `pressure_b_bar`; add a `reference_bar` column from the gauge
and pass the file with `--csv` instead of `--point`.

A sensor that idles above 0 V is **not** a 0..10 V sensor: use the fitted offset.

## Calibration log (fill this in)

| Date | Sensor | Reference | Old gain | New gain | Notes |
|---|---|---|---|---|---|
| | PT1 A0 | gauge 0..6 bar | 0.6 | | |
| | PT2 A1 | gauge -1..1.6 bar | 0.26 | | |
| | flow main | 2 L jug | 1.5 | | |

## What "good" looks like

- Flow error < 5% at the operating point after calibration.
- Pressure error < 0.05 bar across each sensor range.
- No drift when the pump heats up; re-check after 30 minutes.
- Baseline noise small enough that a 0.3 L/min leak is visible in a 10 s mean.
