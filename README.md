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

## Bench rev 1 demo (F0 + PT1 + PT2, taps L1-L3)

The bench as built has one flow meter (F0) and two pressure sensors (PT1 on branch A, PT2 on
branch B). This chain runs next to the 4-flow pieces above without changing them:

```powershell
# backend + static dashboard (http://localhost:8000): live mode, replays, scoreboard, farm, M3
uvicorn backend.main:app
$env:HYDROPIN_MQTT="1"; uvicorn backend.main:app        # with the broker / real ESP32

# no bench at hand: stream a simulated run into the backend (scenarios: --list)
python -m simulator.bench_rev1 --scenario leak_L2 --realtime --post http://localhost:8000
python -m simulator.bench_rev1 --scenario baseline --realtime --publish       # over MQTT

# replays + scoreboard for the static site (GitHub Pages)
python -m tools.export_replays --sim                    # simulated, labelled "simulation"
python -m tools.export_replays --db data/hydropin.db    # the recorded bench campaign
```

- `detection/bench_detector.py`: quality gate -> pump states -> `flow` + `m2` -> log-odds fusion ->
  `HEALTHY | WATCH | LEAK` (+ `PUMP_OFF`, `SETTLING`, `LEARNING`, `OFFLINE`), branch A/B, per-tap
  probabilities, leak size, litres lost. Same code live, in scoring and in the replay export; it
  never reads labels or events. Thresholds: `BenchConfig` (or `data/bench_detector.json`).
- Campaign in the dashboard: **Start run** (label, opening, measured leak, blind) -> press the event
  buttons when you open/close a tap, move a valve or switch the pump -> **Re-baseline** after any
  valve change -> **Stop run**. Each run is then a replay: `GET /api/runs/{id}/replay`.
- GitHub Pages: `.github/workflows/pages.yml` publishes `dashboard/` (+ the farm explorer and the
  twin viewer) on every push to `main`. Pages has replay mode only; live mode needs the laptop.

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
- `firmware/` ESP32 PlatformIO project (ADS1115 PT1/PT2 + main flow ISR + MQTT)
- `hydropin/` shared Python: config, units, message parsing
- `simulator/` digital twin `hydropin_sim/` (physics, sensors, M1/M2/M3, prototype bench; see simulator/README.md)
  + bench data generator `sim.py` / `scenarios.py` (scenarios, quantization, dropout)
  + rev 1 bench simulator `bench_rev1.py` (F0 + PT1 + PT2, taps L1-L3, stress and fault scenarios)
- `detection/` explainable M0 detector (normalized shares + CUSUM) and evaluation;
  rev 1 bench detector `bench_detector.py` and replay/scoring `replay.py`
- `ml/` features, training, prediction (scikit-learn)
- `backend/` FastAPI + SQLite + MQTT listener + REST/WebSocket; serves the static dashboard at `/`
- `dashboard/` static dashboard (`index.html`, live + replay, no build step; published on Pages),
  its data (`replays/`, `scoreboard*.json`, `farm/`, `m3/`) and the older Streamlit `app.py`
- `farm/`, `m3/` virtual farm + leak dataset, M3 pressure-wave method (simulation; see their READMEs)
- `tools/` real-data validator, onset labeller, calibration fitter, replay/scoreboard export
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

The firmware compiles for `esp32dev` with PlatformIO 6.2.0 and
`espressif32@6.9.0` (RAM 14.1%, flash 58.9%). It has **not** been flashed or run
on hardware yet.

```powershell
cd firmware
copy include\secrets.example.h include\secrets.h   # then edit Wi-Fi + broker
pio run
pio run -t upload
pio device monitor -b 115200
```
