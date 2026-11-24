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

The export includes `dropout`, `ripple`, `clipped`, `raw_flow_*_pulses`, and
`raw_pressure_adc`, so `tools.validate_dataset` and `tools.calibrate` can run
directly on an exported real run.

## Telemetry message

See `contract/message.schema.json`. Example:

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
    "pressure_adc": 1667
  },
  "values": {
    "flow_main_lpm": 1.80,
    "flow_l1_lpm": 0.60,
    "flow_l2_lpm": 0.45,
    "flow_l3_lpm": 0.75,
    "pressure_bar": 2.00
  },
  "quality": {"dropout": false, "ripple": false, "clipped": false}
}
```

Units: flow in L/min (calibrated), pressure in bar (calibrated), raw pulses are
counts over the 2 s flow window, `pressure_adc` is ADS1115 counts. During the
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
