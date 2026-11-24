# Calibration

The two gains in this repo are **provisional bench values**, not physics:

```
flow_lpm     = (pulses / dt_s) / 7.5 * 1.5      # "flow * 3/2"
sensor_volts = (adc / 32767) * 4.096 * 3.2      # ADS + 22k/10k divider
pressure_bar = sensor_volts * 3.0 + offset      # "pressure * 3"; offset fit on bench
```

They live in `hydropin/config.py` and `firmware/include/config.h`. They must
stay equal; `tests/test_contract.py` and the firmware constants are the contract.

## Flow sensor (YF-S201 class)

Datasheet: `F (Hz) = 7.5 * Q (L/min)`, about 450 pulses per litre.

1. Fill a container of known volume (2 L is better than 1 L).
2. Count pulses while it fills, at the normal operating flow.
3. `pulses_per_litre = total_pulses / litres`.
4. Update `FLOW_K_PULSES_PER_LITRE` in both config files.
5. Compute the raw datasheet flow and compare with the measured flow:
   `raw_lpm = (pulses / seconds) / 7.5`.
6. If the raw value is consistently off by a factor, that factor is
   `FLOW_GAIN`. Do not hide a plumbing/calibration error behind a gain.

The tool prints both choices (keep nominal K and change gain, or set K to the
measured pulses/L and use gain 1.0):

```powershell
python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
```

At 2 Hz a single pulse is 0.4 L/min, so the firmware counts pulses over a 2 s
window (0.1 L/min resolution). Keep `FLOW_MEASURE_WINDOW_S` and
`FLOW_WINDOW_MS` in sync.

## Pressure sensor

1. Power the sensor, read `raw.pressure_adc` at atmospheric pressure.
2. Apply a known pressure with a gauge at 0.5, 1.0, 1.5, 2.0 bar.
3. `sensor_volts = adc / 32767 * 4.096 * 3.2` (22k series / 10k shunt divider).
4. Fit `bar = a * sensor_volts + b`. Compare with the assumed `bar = 3.0 * V`.
5. Update `PRESSURE_GAIN` and `PRESSURE_OFFSET_BAR` in both config files.
6. Record the supply voltage; most of these sensors are ratiometric.

```powershell
python -m tools.calibrate pressure --point 1667:2.0 --point 3333:4.0 --point 5000:6.0
```

The fit is least squares; two points are the minimum, four or more are better.
A sensor that idles at 0.5 V is **not** a 0..5 V sensor: use the fitted offset.
`/api/export.csv` already contains `raw_pressure_adc`; add a `reference_bar`
column from the gauge and pass the file with `--csv` instead of `--point`.

## Calibration log (fill this in)

| Date | Sensor | Reference | Old gain | New gain | Notes |
|---|---|---|---|---|---|
| | flow main | 2 L jug | 1.5 | | |
| | flow L1 | 2 L jug | 1.5 | | |
| | flow L2 | 2 L jug | 1.5 | | |
| | flow L3 | 2 L jug | 1.5 | | |
| | pressure | gauge | 3.0 | | |

## What "good" looks like

- Flow error < 5% at the operating point after calibration.
- Pressure error < 0.05 bar across the working range.
- No drift when the pump heats up; re-check after 30 minutes.
- Baseline noise small enough that a 0.3 L/min leak is visible in a 10 s mean.
