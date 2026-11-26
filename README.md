# hydropin-prototype

Real-time leak detection for a hydroponic bench: ESP32 + main flow sensor +
two branch pressure sensors (PT1 0..6 bar, PT2 -1..1.6 bar) -> MQTT -> backend
-> dashboard, with an explainable detector and a trained ML model.

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
python -m tools.calibrate pressure --point 0:0 --point 8889:2 --point 17778:4 --point 26667:6

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
- `simulator/` digital twin `hydropin_sim/` (physics, sensors, M1/M2/M3, prototype bench; see simulator/README.md)
  + bench data generator `sim.py` / `scenarios.py` (scenarios, quantization, dropout)
- `detection/` explainable M0 detector (normalized shares + CUSUM) and evaluation
- `ml/` features, training, prediction (scikit-learn)
- `backend/` FastAPI + SQLite + MQTT listener + REST/WebSocket
- `dashboard/` live Streamlit dashboard
- `tools/` real-data validator, onset labeller, calibration fitter
- `data/` runs, database, calibration notes
- `docs/` wiring, test protocol, research + plan
- `models/` fitted baseline and trained model (generated)

## Calibration warning

The flow gain `1.5` is **provisional**; verify it with a measured volume before
trusting any leak size. The pressure fits use the real rev 1 sensors:
**PT1 0..6 bar on A0**, **PT2 -1..1.6 bar on A1**, both through
**20k series + 10k shunt** (ratio 3.0, not 3.2). The bench has one main flow
sensor, not branch flow sensors, so live branch localisation is not validated
yet. See `data/calibration.md` and `python -m tools.calibrate --help`.

## Firmware

PlatformIO is not installed in this environment, so the firmware has not been
compiled here.

```powershell
cd firmware
copy include\secrets.example.h include\secrets.h   # then edit Wi-Fi + broker
pio run -t upload
pio device monitor -b 115200
```
