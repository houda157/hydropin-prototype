# hydropin: research, design and execution plan

One file for the whole story: what we are building, what data exists for the ML
goal, the communication/real-time plan, the ML plan, the simulation design, the
phased execution with validation gates, and an honest fault log.

Last updated: 2026-11-24. Everything below was run in this repository.

---

## 1. Goal

A 3-branch hydroponic bench with an ESP32, flow sensors and a manifold pressure
sensor. The bench must:

1. stream calibrated sensor values to a PC in real time,
2. detect a leak on branch L1/L2/L3 (and estimate its size),
3. learn a model that can separate healthy operation from leaks,
4. stay explainable and testable, not just "the neural net says so".

Bench assumption used throughout (rev 1 wiring):

```
main flow = one Hall sensor on GPIO27
PT1 = branch A pressure, 0..6 bar, ADS A0
PT2 = branch B pressure, -1..1.6 bar, ADS A1
no branch flow sensors yet
```

Calibration chain (pressure from datasheet + actual divider):

```
flow_lpm       = (pulses / window_s) / 7.5 * 1.5      # provisional, calibrate
PT1: V_sensor  = V_ads * 3.0; pressure_bar   = 0.0 + 0.6  * V_sensor
PT2: V_sensor  = V_ads * 3.0; pressure_b_bar = -1.0 + 0.26 * V_sensor
```

Both pressure dividers are 20k series + 10k shunt:
`V_ads = V_sensor * 10/30 = V_sensor/3.0`, so `V_sensor = V_ads * 3.0`.
At 10 V the ADS pin sees 3.333 V, inside `GAIN_ONE` (+/-4.096 V).
PT1 full scale is 6 bar (~26667 counts), not 15 bar. PT2 spans -1..1.6 bar.
The flow gain `1.5` is still provisional; calibrate it with a measured volume.

The same constants live in `hydropin/config.py` and `firmware/include/config.h`;
a test fails if they drift apart.

---

## 2. Where the project started and where it is now

The repository started as a **skeleton of stubs**: every Python/C++ file was a
one-line comment. `git log` had a single commit, "initial skeleton". Nothing
could run.

Now it has a working vertical slice:

| Area | State |
|---|---|
| Contract + shared parsing | JSON Schema, builder, validator, 11 tests |
| Simulator | 8 scenarios, real pulse/ADC quantization, dark Plotly HTML, terminal report |
| Detector M0 | normalized branch shares + CUSUM, branch attribution, size estimate |
| Evaluation | per-sample P/R/F1, delay, branch accuracy, false alarms/min, strict gates |
| ML | causal features, RandomForest multiclass, group-aware CV, saved bundle |
| Backend | FastAPI + SQLite + MQTT listener + REST + WebSocket + CSV export |
| Dashboard | Streamlit live charts, alarm banner, run start/stop, CSV link |
| Firmware | ESP32 PlatformIO project, ADS1115 PT1/PT2 + one flow ISR + MQTT JSON, compiled |
| Tests | 40 passed (`python -m pytest -q`) |

File map:

```
contract/      message.schema.json, api.md, labels.md, sample_run.csv
hydropin/      config.py (units/gains), messages.py (build/validate/flatten)
simulator/     scenarios.py, sim.py
detection/     baseline.py, detect.py, evaluate.py
ml/            features.py, train.py, predict.py
backend/       storage.py, ingest.py, live_detect.py, notify.py, api.py, main.py
dashboard/     app.py
firmware/      platformio.ini, include/config.h, src/{main,sensors,network}.cpp
docs/          wiring.md, test_protocol.md, RESEARCH_AND_PLAN.md
data/          calibration.md, raw runs, SQLite DB (gitignored)
models/        baseline.json, hydropin_rf.joblib + metadata (generated)
```

---

## 3. Research: data for the ML goal

### 3.1 Dataset landscape

| Dataset | What it contains | Rate / size | Fit to our bench | Link |
|---|---|---|---|---|
| **BattLeDIM / L-Town** | 2018/2019 SCADA: 3 flow, 33 pressure, 1 tank level, 82 AMR demands, leak records; EPANET model | 5 min, 2 years, ~550 MB | Best public flow+pressure leak benchmark; municipal scale, not hydroponic | https://zenodo.org/records/4017659 , https://battledim.ucy.ac.cy/ |
| **LeakDB** | 1000 scenarios on Net1 and Hanoi; pressures, demands, flows, per-timestep labels, scoring code | 30 min | Good for testing detection methods and scoring; not our topology | https://github.com/KIOS-Research/LeakDB , Zenodo 1313116 |
| **LeakG3PD** | Updated LeakDB, more realistic leak nodes, Net1/Net3/Hanoi | 30 min | Better leak realism for method validation | https://github.com/matheuspilotto/LeakG3PD |
| **AquaIntel** | Real Arduino Uno telemetry: YF-S201 flow, water level, soil moisture, DS18B20, labelled normal/fault | 3,886 rows | Closest **hardware** (same YF-S201); tiny, irrigation not leak-branch | https://ieee-dataport.org/documents/aquaintel-multi-sensor-iot-telemetry-smart-water-management-anomaly-detection , DOI 10.21227/tt8w-qh19 |
| **Mendeley drip irrigation** | HX710B pressure (upstream/downstream) + YF-S201 flow, ESP32 + ThingSpeak | 5 h, 911 filtered points | Very close sensor pair (pressure + flow); different hydraulic setup | https://data.mendeley.com/datasets/w9594tjkwp/1 , DOI 10.17632/w9594tjkwp.1 |
| **Hydroponic LSTM-AE study** | 7 days of 5 s temp/humidity/light/pH/EC, 120,960 records, reconstruction-error anomalies | 5 s | Method reference for high-frequency hydroponic anomaly detection; no flow/leak | https://dergipark.org.tr/en/pub/saucis/article/1858708 |
| **HydroFarm** | Hydroponic sensor dataset + plant images | - | Not leak-specific; useful if adding crop health later | https://doi.org/10.6084/m9.figshare.28340516.v1 |

### 3.2 What this means for us

There is **no public dataset of a 3-branch hydroponic manifold with exactly our
sensor layout and leak labels**. The closest are AquaIntel (same flow sensor,
wrong task) and the Mendeley drip dataset (same pressure+flow pair, wrong
topology). BattLeDIM/LeakDB are the right *method* benchmarks but a different
domain (municipal water networks, 5-30 min sampling, 33 pressure sensors).

Therefore:

1. **Generate our own labelled data** with the simulator now and the real bench
   next (see section 6.1).
2. Use LeakDB/BattLeDIM to **compare detection methods** and to pretrain/verify
   feature ideas, not to claim field accuracy.
3. Keep a **real held-out set** that is never used for training. Simulation
   metrics are not evidence of field performance.

### 3.3 Methods that fit flow + pressure leak detection

| Family | Examples | Why / caveat |
|---|---|---|
| Threshold / minimum night flow | LeakDB MNF baseline | Simple, interpretable; needs demand-free periods |
| Statistical process control | CUSUM, EWMA, Hotelling T² | Strong for slow/incipient leaks; we use CUSUM on shares |
| Unsupervised outlier detection | Isolation Forest, PCA reconstruction | Works with few labels; can drift |
| Reconstruction models | AE, VAE, LSTM-AE | LSTM-AE reported 97% (pressure) / 100% (flow) sensitivity on LeakDB; needs normal-only training data |
| Supervised classifiers | Random Forest, XGBoost/LightGBM, CNN | Strong when labels exist; class imbalance and run leakage are the traps |
| Detect + localize | two-stage residual + branch attribution, LILA, EPANET/WNTR inversion | Localization usually needs a hydraulic model; our branch sensors simplify it |

Key references:

- BattLeDIM results paper: https://doi.org/10.1061/(ASCE)WR.1943-5452.0001601
- LeakDB paper: https://ojs.library.queensu.ca/index.php/wdsa-ccw/article/download/12315/7911
- ML in water distribution networks review: https://arxiv.org/pdf/2410.12461v1.pdf
- LSTM-AE leak detection/localization: https://ideas.repec.org/a/spr/waterr/v37y2023i2d10.1007_s11269-022-03397-6.html
- Encoder-decoder comparison (L-Town + real Norway case): https://iwaponline.com/ws/article/24/8/2750/103665
- Attention AE: https://www.mdpi.com/2079-9292/12/22/4665
- Two-stage detection/localization: https://www.mdpi.com/2073-4441/15/15/2710
- LILA: https://ascelibrary.org/doi/10.1061/%28ASCE%29WR.1943-5452.0001535
- WNTR (hydraulic simulation): https://github.com/USEPA/WNTR
- WaterBenchmarkHub (LeakDB loader): https://waterfutures.github.io/WaterBenchmarkHub/benchmarks/KIOS-LeakDB.html
- YF-S201 calibration: https://www.ijtrd.com/papers/IJTRD17965.pdf
- ESP32 + YF-S201 wiring: https://lcdultrapro.com/parts/yf-s201-flow-sensor

### 3.4 Metrics that matter

- Per-sample precision / recall / F1 (class-imbalanced, so also PR-AUC).
- Detection delay from leak onset (seconds), reported per run.
- False alarms per minute on healthy/stress runs.
- Branch attribution accuracy.
- Leak-size error (L/min MAE).
- For ML: group-aware CV by run, then a real held-out set.

Accuracy alone is misleading: a "none" classifier gets high accuracy on a mostly
healthy dataset.

---

## 4. Communication and real-time acquisition plan

### 4.1 Topology

```
flow sensors --ISR--> ESP32 --WiFi/MQTT--> Mosquitto --> backend (paho)
                                                         |-> SQLite (WAL)
                                                         |-> detector
                                                         |-> WebSocket/REST
                                                         `-> Streamlit dashboard
```

### 4.2 Protocol

| Item | Decision |
|---|---|
| Telemetry topic | `hydropin/bench/<device>/telemetry` |
| Status topic | `hydropin/bench/<device>/status`, retained, LWT `offline` / `online` |
| QoS | Device publishes **0** (PubSubClient limitation); simulator 1; backend subscribes 1. Dedupe by `PRIMARY KEY(device, seq)`; a `seq` gap means loss. |
| Retained telemetry | no (stale values are dangerous) |
| Publish rate | 2 Hz (`PUBLISH_PERIOD_MS = 500`) |
| Payload | `contract/message.schema.json`, version `1.0` |
| Time | device NTP ISO-8601 + `ts_device_ms`; server adds `received_ts` |
| Broker (dev) | `broker/mosquitto.conf`, anonymous, local only |

### 4.3 Acquisition chain (the part that actually matters)

1. Flow pulses are counted in a minimal `IRAM_ATTR` ISR (`counter++` only).
2. Flow is **not** computed from 0.5 s of pulses: that gives 0.4 L/min per pulse.
   The firmware keeps a 2 s ring of four 0.5 s counts, so one pulse is
   0.1 L/min. Publish rate stays 2 Hz.
3. Pressure: ADS1115 single-ended, ±4.096 V, 128 SPS, average of 8 reads on
   A0 (PT1) and A1 (PT2). `V_sensor = adc/32767 * 4.096 * 3.0`;
   PT1 `bar = 0.6 * V_sensor`, PT2 `bar = -1.0 + 0.26 * V_sensor`.
4. Clamp to physical ranges (PT1 0..6 bar, PT2 -1..1.6 bar), flag `clipped`.
5. Build JSON with raw pulses/ADC + calibrated values (auditable).
6. Publish; on failure, log (offline buffering is a next step, not implemented).

### 4.4 Latency budget

| Stage | Budget |
|---|---|
| Flow measurement window | 2.0 s |
| Publish period | 0.5 s |
| LAN MQTT | < 0.1 s |
| Backend validate + insert | < 0.05 s |
| Detector update | < 1 ms |
| WebSocket push | 0.5 s |
| Dashboard refresh | 1.0 s |
| **Value on screen** | **~3-4 s** |
| Detector delay (medium leak) | ~4-5 s after onset |

The 2 s window dominates. That is the price of not lying about small flows.

### 4.5 Reliability and data quality

Implemented:

- MQTT reconnect with backoff, LWT status, `seq` + idempotent insert.
- Schema + physical-range validation (bad values are rejected with 422).
- `dropout` / `ripple` / `clipped` quality flags.
- SQLite WAL for concurrent dashboard/API reads.
- CSV export (calibrated values + raw pulses/ADC + quality flags) and a
  WebSocket feed.

Planned (not done):

- Offline ring buffer in NVS/SPIFFS and replay after reconnect.
- Gap detection from `seq`, interpolation for short dropouts.
- Median filter / sensor fault detection (stuck, spike, out-of-range).
- Backpressure policy when the broker or DB is slow.
- TLS + broker auth; `secrets.h` is gitignored but the dev broker is anonymous.

### 4.6 What was actually validated

- Unit/integration tests: 40 passed.
- **Real MQTT end-to-end** with the local Mosquitto service:
  - backend connected (`mqtt.connected = true`),
  - simulator published a 90 s L1 leak run,
  - **180/180 readings stored**,
  - **1 alert** created: branch `l1`, confidence `0.854`, estimated `0.161 L/min`
    at the rising edge (the estimate is low because the alarm fires while the 2 s
    window is still filling; it rises afterwards).
- REST, CSV export, WebSocket, run start/stop tested with FastAPI TestClient.
- Dashboard boots and serves HTTP 200.

---

## 5. ML plan

### 5.1 Data collection protocol (real bench)

Target: enough runs that a group split has every class in every fold.

- 3 baseline runs x 10 min, across pump states (normal, throttled).
- 27 leak runs: 3 branches x 3 sizes (small/medium/large) x 3 repeats.
  Each: 30 s clean, open valve, 60 s leak, close, 30 s clean.
- Stress runs labelled `none`: pump ripple, Wi-Fi dropout, pressure re-zero,
  pump start/stop.
- Keep a **real held-out day/session** that is never trained on.

### 5.2 Labels

`none`, `leak_L1`, `leak_L2`, `leak_L3` (see `contract/labels.md`). A label
starts at leak onset, not at file start. Stress runs are `none`.

### 5.3 Features (implemented, 63 features)

- Raw calibrated values: main/L1/L2/L3 flow, pressure.
- **Branch shares** `flow_c / sum(branches)` — the key drift-robust feature.
- Rolling mean and delta at 5/15/30 samples (2.5/7.5/15 s).
- Share deviation from a 60-sample causal median.
- 30-sample slopes.
- `main - sum(branches)` consistency residual.

All features are causal: a test changes future samples and asserts earlier
features do not move. Features are computed per run so a window never crosses a
run boundary.

### 5.4 Model ladder

| Stage | Model | Status |
|---|---|---|
| M0 | Rules: share residual + CUSUM + branch argmax | **done**, explainable, no training |
| M1 | Isolation Forest / PCA reconstruction (normal-only) | next |
| M2 | Random Forest multiclass (4 classes) | **done** |
| M3 | LSTM-AE / 1D-CNN sequence model | only with several hours of real data |

### 5.5 Validation protocol

- Split by **run**, never by sample. Neighbouring samples are nearly identical.
- Use `StratifiedGroupKFold` so every fold sees every class.
- Also evaluate on **unseen seeds** and later on **real held-out runs**.
- Report P/R/F1 per class, binary leak F1, detection delay, false alarms/min,
  branch accuracy, leak-size MAE.
- Keep the model bundle self-describing: features, classes, metrics, timestamp.

### 5.6 Deployment

- `joblib` bundle + JSON metadata (`models/hydropin_rf.joblib`, `.json`).
- Feature version and model version must travel together.
- Run in shadow mode first: compare ML vs M0 on real runs before letting it
  drive alarms.
- Fall back to M0 when the model is out of distribution or low confidence.
- Monitor input drift (shares, noise, dropout rate) and retrain on new labelled
  runs; never auto-retrain on unlabelled predictions.

### 5.7 Skeptic checklist

- Simulated 98% is not field performance.
- Class imbalance hides false alarms; always report FA/min.
- Label onset bugs inflate recall and delay (we hit exactly this, see section 8).
- Gain errors fake pressure drops; do not gate on pressure alone.
- Quantization limits small-leak detection; a single sample is not evidence.
- Sensor placement and plumbing can invalidate the "branch downstream" assumption.
- Public datasets are a different domain; do not mix their accuracy claims with ours.

### 5.8 Real-data runbook (implemented)

This is the concrete path from bench to model, not a promise:

1. **Calibrate before collecting labels.**
   ```powershell
   python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
python -m tools.calibrate pressure --point 0:0 --point 8889:2 --point 17778:4 --point 26667:6
# PT2: use raw_pressure_b_adc and the -1..1.6 bar gauge points
   ```
   Copy the printed constants into `hydropin/config.py` **and**
   `firmware/include/config.h`; the test suite fails if they drift.
2. **Collect with correct labels.** Start a run in the dashboard before the
   leak, then press **Mark leak onset** at the instant the valve opens. Live
   samples before onset stay `none`; samples after inherit the run label. This
   is stored in `runs.onset_ts` and applied by `backend/ingest.py`.
3. **Export** the run CSV from `/api/export.csv`.
4. **Validate** before training:
   ```powershell
   python -m tools.validate_dataset --dir data/real --strict
   ```
   It rejects wrong sample rate (must be ~2 Hz), missing columns, unknown
   labels, duplicates, NaNs, out-of-range values and large `seq` gaps; it warns
   about raw pulse/ADC drift.
5. **Fix a missed onset** post-hoc:
   ```powershell
   python -m tools.label_csv --csv data/real/leak_L1_01.csv --label leak_L1 --onset 2026-11-24T12:00:30Z
   ```
6. **Fit the baseline on real healthy runs only**, then evaluate:
   ```powershell
   python -m detection.baseline --csv data/real/baseline_01.csv --out models/baseline_real.json
   python -m detection.evaluate --dir data/real --strict
   ```
7. **Train on real runs with a separate real holdout**:
   ```powershell
   python -m ml.train --data-dir data/real --holdout-dir data/real_holdout `
     --out models/hydropin_rf_real.joblib
   ```
   Each class needs at least 2 independent runs for grouped CV; 5+ is better.
   The holdout directory is never used for fitting and its metrics are written
   into the model metadata.
8. **Do not mix** simulated and real rows in one training set without a
   `source` column and a deliberate experiment. The model bundle records
   `data_source` and the actual `classes` present, so a real model trained on
   only `none` + `leak_L2` still maps probabilities correctly.

Known real-data limits: firmware publishes QoS 0 and has no offline buffer, so
`seq` gaps are real data loss. The validator reports them; do not silently
interpolate across a gap. Re-calibrate after plumbing, pump or sensor changes.

---

## 6. Simulation plan (and what it does not model)

Implemented in `simulator/`:

- Branch demand + AR(1) random walk + slow sinusoidal drift.
- Abrupt leaks and incipient leaks with a ramp.
- Pressure from a simple pump curve + ripple.
- Independent sensor noise, 2 s pulse quantization, 16-bit ADC quantization.
- Dropout (stale sample + flag), pump ripple, and gain-error scenarios.
- Deterministic seeds, labels that switch at leak onset.
- Outputs: contract CSV, dark Plotly HTML, rich terminal summary, optional MQTT
  publish.

Not modelled (important):

- Hydraulic transients, valve dynamics, pump startup, pipe friction.
- Temperature drift, sensor aging, stuck/faulty sensors.
- Multi-leak scenarios, air pockets, cavitation.
- Real noise spectrum and electromagnetic interference.
- Sensor placement effects.

The simulator is a **test harness for the pipeline**, not a digital twin.

---

## 7. Phased execution and validation gates

| Phase | Deliverable | Gate | Result |
|---|---|---|---|
| 0 | Web research | datasets + methods + caveats | done (section 3) |
| 1 | Contract + shared code | schema tests, unit conversions | 11 passed |
| 2 | Simulator | all scenarios run, labels switch at onset, HTML/CSV produced | done |
| 3 | Detector M0 | recall >= 0.80, correct branch, FA <= 1/min | P=1.000, R=0.918, F1=0.957, 0 FA/min |
| 4 | ML | grouped CV macro F1 > 0.75, unseen seed generalisation | macro F1 0.982, unseen seeds ~0.98 |
| 5 | Backend | ingest/query/export/runs/WS tests + real MQTT | 3 tests + MQTT e2e 180/180, 1 alert |
| 6 | Dashboard | serves, live charts | HTTP 200 |
| 7 | Firmware | code complete; compiles for ESP32 | **compiled** (PlatformIO 6.2.0, espressif32 6.9.0); not flashed |
| 8 | Docs + full validation | 40 tests, e2e, this file | 40 passed |

### Measured detector results (simulator, 120 s runs)

| Run | Recall | Delay | Branch | FA/min |
|---|---|---|---|---|
| leak_L1 medium (seed 7) | 0.950 | 4.5 s | l1 correct | 0 |
| leak_L1 medium (seed 11) | 0.950 | 4.5 s | l1 correct | 0 |
| leak_L1 medium (seed 21) | 0.967 | 3.0 s | l1 correct | 0 |
| leak_L2 medium | 0.956 | 4.0 s | l2 correct | 0 |
| leak_L3 medium | 0.939 | 5.5 s | l3 correct | 0 |
| leak_L1 incipient | 0.765 | 23.5 s | l1 correct | 0 |
| baseline | - | - | - | 0 |
| ripple | - | - | - | 0 |
| dropout | - | - | - | 0 |
| calibration drift | - | - | - | 0 |

Micro over all 6 leak runs: **precision 1.000, recall 0.918, F1 0.957**
(TP=1010, FP=0, FN=90).

### Measured ML results (grouped CV, 56 runs, 13,440 samples)

- Accuracy 0.980, macro F1 0.982.
- Binary leak: precision 0.995, recall 0.969, F1 0.982.
- Per class F1: none 0.979, L1 0.972, L2 0.995, L3 0.980.
- Unseen seeds 5/6: accuracy ~0.98, macro F1 ~0.98; L1 recall ~0.90.
- Residual false alarms on some healthy runs: 2-10 samples out of 240.
- These are **simulation** numbers.

---

## 8. Fault log: what failed and what we corrected

| # | Symptom | Root cause | Fix | Evidence |
|---|---|---|---|---|
| 1 | Nothing runs | repo was one-line stubs | built the pipeline | `pytest` 40 passed |
| 2 | One pulse = 0.4 L/min at 2 Hz | pulse counting over one publish period | 2 s sliding flow window (0.1 L/min) | `test_pulse_quantization...` |
| 3 | Detector delay 34 s on an abrupt leak | simulator labelled the whole run as leak | label switches at `leak_start_s` | delay 4.5 s |
| 4 | False alarms: baseline 18/min, ripple 40/min, drift 97% | detector used absolute flow, which drifts | normalize to branch shares + CUSUM | 0 FA/min on all healthy runs |
| 5 | ML L2/L3 recall = 0 | too few runs per class + GroupKFold put them in one fold | all branches x all sizes + `StratifiedGroupKFold` | macro F1 0.982 |
| 6 | E2E harness "backend not up" | `Start-Process` ran outside the repo dir | pass `-WorkingDirectory`; use `curl.exe` for health | MQTT e2e 180/180 |
| 7 | Firmware would not compile | default platform pulled Arduino-ESP32 3.3.12, whose WiFi headers failed | pinned `espressif32@6.9.0` (Arduino-ESP32 2.0.17) | `pio run` SUCCESS, RAM 14.1%, flash 58.9% |
| 8 | Pressure math was wrong | doc assumed 22k/10k (3.2:1) and a 0..5 V sensor; rev 1 is 20k/10k (3.0:1) and 0-10 V sensors | corrected to 20k/10k; PT1 `bar=0.6*V_sensor`, PT2 `bar=-1+0.26*V_sensor` | `test_pressure_sensor_full_scale_is_6_bar` |
| 9 | Raw pulse fields 4x too small | `make_message` reconstructed them with the 0.5 s publish period | default is now the 2 s flow window; regression test asserts 3 L/min -> 30 pulses | `test_make_message_raw_pulses_use_the_2s_flow_window` |
| 10 | Real firmware samples were all labelled `none` | dashboard run label was stored only in `runs`, never applied to readings | added `runs.onset_ts`, `POST /api/runs/{id}/onset`, ingest override for live samples; offline `tools.label_csv` fallback | `test_live_labels_follow_marked_onset` |
| 11 | Pressure range accepted an impossible 16 bar | assumed a 0..5 V, 15 bar sensor | rev 1 is PT1 0..6 bar + PT2 -1..1.6 bar; ranges and firmware max corrected | `test_pressure_sensor_full_scale_is_6_bar` |
| 12 | QoS documented as 1 but firmware sends 0 | PubSubClient publish is QoS 0 | corrected contract/plan; dedupe by seq, validator reports gaps | `tools.validate_dataset` |
| 13 | Firmware had 4 flow inputs / 1 pressure | old bench assumption, not rev 1 wiring | rev 1 uses 1 flow (GPIO27) + PT1 A0 + PT2 A1; branch flows publish 0 | `firmware/src/sensors.cpp` |

This is the point of the phase gates: every one of these was found by testing,
not by assuming.

---

## 9. Risks and limitations

- **Simulation ≠ reality.** All detector/ML numbers are on simulated data.
- **No real calibration data yet.** The flow gain `1.5` is provisional; the PT1
  and PT2 pressure fits come from the 0-10 V datasheet ranges and 20k/10k
  dividers, but still need a gauge check.
- **Pressure hardware.** PT1 is 0..6 bar on A0, PT2 is -1..1.6 bar on A1, both
  through 20k/10k (ratio 3.0). A 4-20 mA PT2 variant needs a different input.
- **Branch-flow mismatch.** The detector/ML expect branch flow shares
  (L1/L2/L3); rev 1 has branch pressure sensors only, so live localisation is
  not validated until branch flow sensors are added or the models are retrained
  on PT1/PT2.
- **Firmware compiled, not flashed.** `pio run` succeeds (RAM 14.1%, flash
  58.9%) but the binary has not run on the ESP32; the ms timestamp and NTP path
  are still untested on hardware.
- **QoS 0 on the device, no offline buffering.** MQTT outages drop samples;
  `seq` gaps are real loss. The validator reports them but cannot recover them.
- **Real labelling is implemented, not yet exercised on hardware.**
  `runs.onset_ts` + `tools.label_csv` exist, but the workflow still needs a
  bench run.
- **One leak at a time.** Multi-leak is out of scope.
- **No TLS/auth.** Dev broker is anonymous; do not expose it.
- **Public datasets are a different domain.** Use them for methods, not accuracy.
- **Thresholds are tuned on simulation.** Re-tune on real runs with the FA budget.
- **Electrical safety.** Pump and water: separate supply, flyback diode, common
  ground at one point, no 5 V into ESP32 pins; flow pulses need the divider.

---

## 10. Next steps, in priority order

1. **Calibrate the real sensors** with `tools.calibrate` (2 L jug, pressure
   gauge), including the pressure offset; update both config files and re-run
   `test_firmware_config.py`.
2. **Collect real runs with onset labels**: 3 baseline x 10 min, 27 leak runs,
   stress runs. Press **Mark leak onset** at the valve; export and validate.
3. **Fit the real baseline** on healthy runs, re-evaluate M0 on real held-out
   runs, and tune `cusum_h`, `min_branch_z`, window size against the FA budget.
4. **Train on real runs** with `--data-dir` and a separate `--holdout-dir`;
   compare with simulation-only metrics. Add M1 (Isolation Forest / PCA) on the
   same split.
5. **Finish the firmware**: flash the compiled binary, verify the 2 Hz JSON and
   ms timestamps, add NTP sync guard + offline ring buffer.
6. **MQTT hardening**: auth/TLS, retained status, gap detection, alert cooldown,
   and either accept QoS 0 with buffering or move to a QoS 1-capable client.
7. **Dashboard polish**: replay a CSV through `/api/ingest`, alert history,
   export of the current window.
8. **Deployment**: Docker/systemd, DB backups, structured logs, health checks.

---

## 11. Reproduce everything

```powershell
python -m pip install -r requirements.txt
python -m pytest -q

# data
python -m simulator.sim --scenario baseline --duration 120 --seed 7
foreach ($s in 'leak_L1','leak_L2','leak_L3','leak_L1_incipient','ripple','dropout','calibration_drift') {
  python -m simulator.sim --scenario $s --duration 120 --seed 7 --quiet
}

# detector
python -m detection.baseline --csv data/raw/baseline_seed7.csv --out models/baseline.json
python -m detection.evaluate --dir data/raw --strict

# ML
python -m ml.train --seeds 1 2 3 4
python -m ml.predict --model models/hydropin_rf.joblib --csv data/raw/leak_L1_seed7.csv

# real-data toolchain
python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
python -m tools.calibrate pressure --point 1667:2.0 --point 3333:4.0 --point 5000:6.0
python -m tools.validate_dataset --dir data/real --strict
python -m tools.label_csv --csv data/real/leak_L1_01.csv --label leak_L1 --onset 2026-11-24T12:00:30Z
python -m ml.train --data-dir data/real --holdout-dir data/real_holdout --out models/hydropin_rf_real.joblib

# backend + dashboard
uvicorn backend.main:app
streamlit run dashboard/app.py

# real MQTT end-to-end (Mosquitto must be running)
$env:HYDROPIN_MQTT="1"; uvicorn backend.main:app --port 8016
python -m simulator.sim --scenario leak_L1 --duration 90 --seed 11 --publish --broker localhost --quiet

# firmware (compiled here; upload needs the board)
cd firmware
copy include\secrets.example.h include\secrets.h
pio run
pio run -t upload
pio device monitor -b 115200
```

---

## 12. Bottom line

The pipeline is real and tested end-to-end in simulation and over a real MQTT
broker. The explainable detector meets the gates (P=1.000, R=0.918, 0 false
alarms/min, 4-5 s delay on medium abrupt leaks). The ML model scores 0.98 macro
F1 with group-aware validation, but that is a **simulation** result and must be
re-proven on the bench. The divider math (20k/10k, ratio 3.0), raw-pulse window,
PT1/PT2 ranges and real-run onset labelling are now fixed and regression-tested.
The remaining open items are physical: calibrate the flow gain, gauge-check
PT1/PT2, flash the compiled firmware, and collect the first real labelled runs. Rev 1
has branch pressure sensors, not branch flow sensors, so live branch
localisation still needs either extra flow sensors or retraining on PT1/PT2.
