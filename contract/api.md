# API

Base URL: `http://localhost:8000` (uvicorn `backend.main:app`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | db path, detector loaded, MQTT state |
| POST | `/api/ingest` | validate + store one telemetry message (no MQTT needed) |
| GET | `/api/readings?limit=&since=&device=` | readings, ascending by `ts` |
| GET | `/api/alerts?limit=` | newest alerts first |
| GET | `/api/runs?limit=` | labelled runs |
| POST | `/api/runs` | `{"label": "none\|leak_L1\|leak_L2\|leak_L3", "notes": "..."}` |
| POST | `/api/runs/{id}/onset` | mark leak onset; optional `{"ts": "ISO-8601"}` (default now) |
| POST | `/api/runs/{id}/stop` | stop a run |
| GET | `/api/export.csv` | CSV export with calibrated values, quality flags, and raw pulses/ADC |
| WS | `/ws/live` | pushes new readings + latest alert every 0.5 s |

**Bench rev 1 (F0 + PT1 + PT2), detector `detection/bench_detector.py`:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | `{"state", "frame"}`: latest processed frame; `OFFLINE` when no message for 3 s |
| GET | `/api/frames?since_id=&limit=&run_id=` | processed frames (ascending); each has an `id` |
| POST | `/api/events` | `{"type", "tap"?, "ts"?, "notes"?}`; type in `leak_on, leak_off, valve_change, pump_on, pump_off`, tap in `L1..L3`; attached to the active run. A `leak_on` also sets the run's onset if not set |
| GET | `/api/events?run_id=` | events (newest first, or one run's in time order) |
| POST | `/api/baseline/reset` | re-learn the healthy baseline (after any valve change): SETTLING -> LEARNING -> HEALTHY |
| POST | `/api/runs` | also takes `opening`, `measured_leak_lpm`, `blind` (run metadata, `labels.md`) |
| POST | `/api/runs/{id}/meta` | fill in metadata later, e.g. the label of a blind run |
| GET | `/api/runs/{id}/replay` | one recorded run in the replay format below |
| WS | `/ws` | `{"type": "frames" \| "tick", "frames": [...], "state"}` every 0.5 s (last 240 frames on connect) |
| GET | `/` | static dashboard (`dashboard/index.html`); `/farm-explorer/`, `/twin/` simulation viewers |

### Processed frame

What the dashboard shows; pushed on `/ws`, stored in the `frames` table, the unit of a replay.

| Field | Meaning |
|---|---|
| `ts`, `device`, `seq`, `run_id` | from the message; `run_id` = active run or null |
| `pt1_bar`, `pt2_bar`, `dp_bar` | PT1 (branch A), PT2 (branch B), PT1 − PT2 |
| `flow_lpm`, `flow_base_lpm` | F0 and its learned baseline (null until learned) |
| `state` | `PUMP_OFF \| SETTLING \| LEARNING \| HEALTHY \| WATCH \| LEAK` (`OFFLINE` from `/api/state` and `/ws`) |
| `p_leak` | fused probability, 0..1 |
| `methods` | `{"flow": {...}, "m2": {...}}`, each `{"score" 0..1, "z", "quality" 0/1, "excluded"}` |
| `faults` | e.g. `PT1_unplugged`, `PT2_unplugged`, `PT1_stuck`, `PT2_out_of_range`, `PT1_suspect` (moving alone), `data_gap`, `PT2_missing` |
| `branch` | `"A"`, `"B"` or null (only in WATCH/LEAK, and only when M2 passes the gate) |
| `loc` | `{"L1", "L2", "L3"}` probabilities; L2 and L3 share branch B's |
| `leak_lpm`, `lost_l` | F0 above baseline (WATCH/LEAK), litres lost while in LEAK |

### Replay file (`dashboard/replays/<id>.json`, `GET /api/runs/{id}/replay`)

```json
{"version": "1.0", "id": "bench_run_12", "simulation": false, "source": "bench rev 1",
 "label": "leak_L1", "meta": {"opening": "0.5 mm cap", "measured_leak_lpm": 0.31, "blind": 0, "notes": "..."},
 "events": [{"t_s": 80.0, "type": "leak_on", "tap": "L1"}],
 "frames": [{"t_s": 0.0, "...": "processed frame fields"}]}
```

`dashboard/replays/index.json` lists them (`id, kind (sim|bench), simulation, label, opening, detected, delay_s, branch, false_alarm, file`).
`dashboard/scoreboard.json` (bench) / `scoreboard_sim.json` (simulation): `summary` (detection rate, WATCH-or-LEAK
rate, branch accuracy, median delay, false-alarm runs), `per_tap`, `per_opening`, `runs`. Built by
`python -m tools.export_replays`; scoring uses the events, never the detector.

The export includes `dropout`, `ripple`, `clipped`, `raw_flow_*_pulses`, and
`raw_pressure_adc`, so `tools.validate_dataset` and `tools.calibrate` can run
directly on an exported real run.

## Telemetry message (frozen for the demo, bench rev 1)

See `contract/message.schema.json`. On the bench as built only **`flow_main`** (F0),
**`pressure`** (PT1, branch A, 0–6 bar) and **`pressure_b`** (PT2, branch B, −1…1.6 bar) carry data.
`flow_l1/l2/l3` are **always 0**: kept in the schema so the current detector, ML and tests keep working;
they are removed together with the detector update for the 2-pressure bench. Example
(the branch flows below are from the older 4-flow simulator; on the real bench they are 0):

```json
{
  "schema": "1.0",
  "device": "esp32-bench-01",
  "seq": 42,
  "ts": "2026-11-24T12:00:00.500Z",
  "ts_device_ms": 21000,
  "label": "none",
  "scenario": "live",
  "raw": {
    "flow_main_pulses": 18,
    "flow_l1_pulses": 6,
    "flow_l2_pulses": 4,
    "flow_l3_pulses": 8,
    "pressure_adc": 8889,
    "pressure_b_adc": 0
  },
  "values": {
    "flow_main_lpm": 1.80,
    "flow_l1_lpm": 0.60,
    "flow_l2_lpm": 0.45,
    "flow_l3_lpm": 0.75,
    "pressure_bar": 2.00,
    "pressure_b_bar": -1.00
  },
  "quality": {"dropout": false, "ripple": false, "clipped": false}
}
```

Units: flow in L/min (calibrated), pressure in bar (calibrated), raw pulses are
counts over the 2 s flow window, `pressure_adc`/`pressure_b_adc` are ADS1115
counts. `pressure_b_bar` is optional and only sent by rev 1 firmware with PT2.
During the
first three samples after boot the flow window is only partially filled, so the
raw count is over a shorter interval; the calibrated value is still correct for
that interval.

## Transport reliability

- The ESP32 firmware uses PubSubClient, which publishes at **QoS 0**. The
  backend subscribes at QoS 1, so the effective delivery level is 0.
- The simulator publishes at QoS 1.
- Duplicate `(device, seq)` is dropped by the database, so QoS 1 redelivery is
  safe. A **gap in `seq`** means samples were lost (Wi-Fi, broker, reboot).
  Offline buffering on the device is not implemented yet; do not claim
  lossless delivery.
- For training/evaluation, reject or explicitly handle runs with large seq gaps
  (`python -m tools.validate_dataset --dir data/real`).

## Labelled real runs

1. `POST /api/runs` with the intended label (e.g. `leak_L1`) before opening the
   leak valve.
2. When the valve opens, `POST /api/runs/{id}/onset` (or press **Mark leak
   onset** in the dashboard).
3. Live firmware samples (`scenario="live"`) with `label="none"` at or after
   the onset inherit the run label. Samples before onset stay `none`.
   Simulator/replay messages keep whatever label they already carry.
4. `POST /api/runs/{id}/stop` when the run ends, then export the CSV.

If the onset was missed, fix the exported CSV offline with
`python -m tools.label_csv --csv ... --label leak_L1 --onset ...`.

## Ingest errors

- `422` for schema violations, out-of-range values or a bad label.
- Duplicate `(device, seq)` is accepted but returns `{"inserted": false}`.
