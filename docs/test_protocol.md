# Test protocol

Goal: collect labelled, reproducible runs so the detector and the ML model are
judged on data they have not seen. Every run gets a label from
`contract/labels.md`.

## 0. Pre-flight

1. Wire per `docs/wiring.md`, flash the firmware (`pio run -t upload`).
2. Open the serial monitor: pressure and four flows must be present, no NaN.
3. Start the broker and backend:

```powershell
mosquitto -c broker/mosquitto.conf
$env:HYDROPIN_MQTT="1"; uvicorn backend.main:app
```

4. Start the dashboard: `streamlit run dashboard/app.py`.
5. Confirm `/health` shows `mqtt.connected: true` and telemetry arrives.

## 1. Calibration (do this before any labelled run)

See `data/calibration.md`. Do not skip: the provisional `*1.5` and `*3` gains
are guesses until you check them.

- Flow: run 2 L into a measuring jug, count pulses, then
  `python -m tools.calibrate flow --pulses <n> --litres 2.0 --seconds <s>`.
- Pressure: compare against a mechanical gauge at 0.5, 1.0, 1.5, 2.0 bar, then
  `python -m tools.calibrate pressure --point <adc>:<bar> ...`. Fit both gain
  **and offset**; a sensor that idles at 0.5 V is not a 0..5 V sensor.

## 2. Baseline (no leak)

1. Close all leak valves, run the pump at the normal operating point.
2. Start a run labelled `none` in the dashboard, let it settle 60 s.
3. Record **10 minutes**. Stop the run.
4. Export CSV and fit the baseline:

```powershell
python -m detection.baseline --csv data/raw/bench_baseline.csv --out models/baseline.json
```

5. The baseline fit must not be reused after changing pump speed, plumbing or
   sensor gain. Re-fit after any mechanical change.

## 3. Leak runs

For each branch L1, L2, L3 and each size (small / medium / large):

1. Start a labelled run (`leak_L1`, `leak_L2`, `leak_L3`).
2. Let 30 s of clean baseline, then open the leak valve.
3. **Press Mark leak onset** (or `POST /api/runs/{id}/onset`) at the instant the
   valve opens. Samples before this stay `none`; samples after inherit the run
   label. Without this step every real sample stays `none`.
4. Hold the leak for 60 s, close it, hold 30 s more, stop.
5. Repeat 3 times per condition. Randomise the order; do not always test L1
   first (that biases the operator and the model).

Minimum matrix: 3 branches x 3 sizes x 3 repeats = 27 leak runs, plus 3 baseline
runs, plus stress runs.

## 4. Stress runs (must be labelled `none`)

- Pump ripple / valve throttling.
- Packet loss (disconnect Wi-Fi for a few seconds).
- Re-zero the pressure sensor (calibration drift).
- Start/stop the pump.

These are the runs that expose false alarms. A detector that is perfect on
clean leaks and noisy on stress runs is not deployable.

## 5. Acceptance gates

Validate the real CSVs before trusting any metric:

```powershell
python -m tools.validate_dataset --dir data/real --strict
```

It rejects the wrong sample rate, missing columns, unknown labels, duplicates,
NaNs, out-of-range values and seq gaps; it warns about raw pulse/ADC drift.
Fix a missed onset with:

```powershell
python -m tools.label_csv --csv data/real/leak_L1_01.csv --label leak_L1 --onset 2026-11-24T12:00:30Z
```

Then run the detector:

```powershell
python -m detection.evaluate --dir data/real --strict
```

- recall on leak runs >= 0.80,
- no more than 1 false alarm per minute on healthy runs,
- correct branch attribution on every detected leak,
- detection delay reported (target < 15 s for medium/large abrupt leaks).

For the ML model:

```powershell
# simulation (default)
python -m ml.train --seeds 1 2 3 4

# real data: group-aware CV, then a separate held-out real directory
python -m ml.train --data-dir data/real --holdout-dir data/real_holdout `
  --out models/hydropin_rf_real.joblib
python -m ml.predict --model models/hydropin_rf_real.joblib --csv data/real/<run>.csv
```

Every class needs at least **2 independent runs** for grouped CV, and 5+ is
better. Keep a held-out **real** run set (never used for training) and report
metrics on it. Simulated metrics are not evidence of field performance.
