# Test protocol

Goal: collect labelled, reproducible runs so the detector is judged on data it has not seen.
Every run gets a label from `contract/labels.md`. Commands and dashboard details:
`docs/USER_GUIDE.md` (sections 5, 6 and 8).

## 0. Pre-flight

1. Wire per `docs/wiring.md`, flash the firmware (`pio run -t upload`).
2. Open the serial monitor: `pressure_bar` (PT1), `pressure_b_bar` (PT2) and `flow_main_lpm` must
   be present, no NaN. This rev has one flow sensor and two pressure sensors; `flow_l1/l2/l3` are
   published as 0.
3. Start the broker and the backend, which also serves the dashboard (http://localhost:8000):

```powershell
mosquitto -c broker/mosquitto.conf
$env:HYDROPIN_MQTT="1"; uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

   Without admin rights, `amqtt -c broker/amqtt.yaml` replaces Mosquitto.
4. Confirm `/health` shows `mqtt.connected: true` and the Bench tab in **Live** mode shows F0, PT1
   and PT2.

## 1. Calibration (do this before any labelled run)

See `data/calibration.md`. Do not skip: `FLOW_GAIN` is still provisional, while the PT1/PT2
pressure fits come from the 0-10 V datasheet ranges and the actual 20k/10k dividers.

- Flow: run 2 L into a measuring jug, count pulses, then
  `python -m tools.calibrate flow --pulses <n> --litres 2.0 --seconds <s>`.
- PT1 (0..6 bar): compare against a gauge at 0, 2, 4, 6 bar, then
  `python -m tools.calibrate pressure --point <adc>:<bar> ...`.
- PT2 (-1..1.6 bar): same, at -1, 0, 1.6 bar; set `PRESSURE_B_*` from the fit.
- Fit both gain **and offset**; a sensor that idles above 0 V is not a 0..10 V sensor.

## 2. Quiet run and baseline runs (no leak)

1. Close all leak taps, run the pump at the normal operating point.
2. **Quiet run:** start a run labelled `none`, record **10 minutes** without touching anything,
   stop it. `python -m tools.noise --db data/hydropin.db` turns it into σ per sensor.
3. **Baseline runs:** 3 runs labelled `none`, 3 minutes each.
4. The detector learns its healthy baseline by itself after every pump start (SETTLING, then
   LEARNING). After any valve or plumbing change, press **Valve moved** then **Re-baseline**.

## 3. Leak runs

For each tap L1, L2, L3 and each size (small / medium / large):

1. **Start run** with the label (`leak_L1`, `leak_L2`, `leak_L3`) and the opening; add the measured
   leak (cup + stopwatch) if known.
2. Wait for **HEALTHY**, then open the tap and press **Open L1** (L2, L3) at the same instant. Samples before
   this stay `none`; samples after inherit the run label.
3. Hold the leak for 60 s, close it and press **Tap closed**, hold 30 s more, **Stop run**.
4. Repeat 3 times per condition. Randomise the order; do not always test L1 first (that biases the
   operator and the model).

Minimum matrix: 3 taps x 3 sizes x 3 repeats = 27 leak runs, plus 3 baseline runs, plus stress runs.
If time is short: 3 taps x 2 sizes x 2 repeats = 12 leak runs.

## 4. Stress runs (must be labelled `none`)

- Pump off / on.
- A valve change, followed by **Re-baseline**.
- Packet loss (disconnect Wi-Fi for about 10 s).
- Unplug a pressure sensor (it must show as a sensor fault, not a leak).

These are the runs that expose false alarms. A detector that is perfect on clean leaks and noisy
on stress runs is not deployable.

## 5. Blind test

3–5 runs where a teammate opens a tap the operator does not know; tick **blind** when starting the
run. Blind runs are always kept for testing and listed on the scoreboard, misses included.

## 6. Results and acceptance gates

```powershell
python -m tools.noise --db data/hydropin.db
python -m detection.train_bench --db data/hydropin.db
python -m tools.export_replays --db data/hydropin.db
```

`train_bench` splits the runs 70 / 30 (stratified by label, blind runs always in the test part)
and fits the fingerprints and the LEAK rule on the training part only. The export re-runs the
detector on every run and writes the scoreboard, with the headline on test runs only.

Targets, on test runs:
- detection of medium and large leaks >= 0.80,
- no false alarm on baseline and stress runs,
- correct branch on every detected leak,
- time to detect reported (target < 15 s for medium/large leaks).

Simulated scores are not evidence of bench performance; the scoreboard says which it is showing.
