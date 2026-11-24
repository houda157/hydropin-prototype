# hydropin-prototype

Real-time leak detection for a 3-branch hydroponic bench: ESP32 + flow sensors +
pressure sensor -> MQTT -> backend -> dashboard, with an explainable detector and
a trained ML model.

The full research, datasets, design decisions, plans and validation results are
in **[`docs/RESEARCH_AND_PLAN.md`](docs/RESEARCH_AND_PLAN.md)**.

## Quick start (no hardware)

```powershell
python -m pip install -r requirements.txt

# 1. generate a healthy baseline and a leak run
python -m simulator.sim --scenario baseline --duration 120 --seed 7
python -m simulator.sim --scenario leak_L1 --duration 120 --seed 7

# 2. fit the baseline and evaluate the detector on data/raw/*.csv
python -m detection.baseline --csv data/raw/baseline_seed7.csv --out models/baseline.json
python -m detection.evaluate --dir data/raw --strict

# 3. train and try the ML model
python -m ml.train --seeds 1 2 3 4
python -m ml.predict --model models/hydropin_rf.joblib --csv data/raw/leak_L1_seed7.csv

# 4. backend + dashboard
uvicorn backend.main:app
streamlit run dashboard/app.py

# 5. tests
python -m pytest -q
```

The simulator also emits a dark Plotly report:
`data/raw/<scenario>_seed<seed>.html`.

## Real bench data

```powershell
# calibrate first (prints the constants to copy into both config files)
python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
python -m tools.calibrate pressure --point 1667:2.0 --point 3333:4.0 --point 5000:6.0

# after collecting runs: validate, fix a missed onset, fit baseline, train
python -m tools.validate_dataset --dir data/real --strict
python -m tools.label_csv --csv data/real/leak_L1_01.csv --label leak_L1 --onset 2026-11-24T12:00:30Z
python -m detection.baseline --csv data/real/baseline_01.csv --out models/baseline_real.json
python -m detection.evaluate --dir data/real --strict
python -m ml.train --data-dir data/real --holdout-dir data/real_holdout --out models/hydropin_rf_real.joblib
```

In the dashboard, start a run before the leak and press **Mark leak onset** when
the valve opens; only samples after that instant inherit the run label. The
`/api/export.csv` file includes raw pulses, raw pressure ADC and the `clipped`
flag, so the validator and calibration fitter can run on exported runs too.

## Layout

- `contract/` shared message schema, labels and API (changed only together)
- `broker/` local MQTT broker config
- `firmware/` ESP32 PlatformIO project (ADS1115 + flow pulse ISRs + MQTT)
- `hydropin/` shared Python: config, units, message parsing
- `simulator/` physically-motivated bench data (scenarios, quantization, dropout)
- `detection/` explainable M0 detector (normalized shares + CUSUM) and evaluation
- `ml/` features, training, prediction (scikit-learn)
- `backend/` FastAPI + SQLite + MQTT listener + REST/WebSocket
- `dashboard/` live Streamlit dashboard
- `tools/` real-data validator, onset labeller, calibration fitter
- `data/` runs, database, calibration notes
- `docs/` wiring, test protocol, research + plan
- `models/` fitted baseline and trained model (generated)

## Calibration warning

The bench gains `flow * 3/2` and `pressure * 3` are **provisional**. Verify them
against a measured volume and a pressure gauge before trusting any leak size.
The pressure divider is **22k series + 10k shunt** (3.2:1); if the sensor idles
at 0.5 V, fit and set `PRESSURE_OFFSET_BAR`. See `data/calibration.md` and
`python -m tools.calibrate --help`.

## Firmware

PlatformIO is not installed in this environment, so the firmware has not been
compiled here.

```powershell
cd firmware
copy include\secrets.example.h include\secrets.h   # then edit Wi-Fi + broker
pio run -t upload
pio device monitor -b 115200
```
