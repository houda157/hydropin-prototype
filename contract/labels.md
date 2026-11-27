# Labels

Allowed run labels: `none`, `leak_L1`, `leak_L2`, `leak_L3`.

| Label | Meaning |
|---|---|
| `none` | healthy run: no leak, including ripple/dropout/calibration-drift stress runs |
| `leak_L1` | leak tap **L1**: branch A (PT1 side), before PT1 |
| `leak_L2` | leak tap **L2**: branch B (PT2 side), before PT2 |
| `leak_L3` | leak tap **L3**: branch B, after PT2 |

The bench as built (rev 1): one flow meter F0 at the source, PT1 on branch A, PT2 on
branch B, and three **leak taps** L1–L3 (CONTEXT §3). There are no per-branch flow
meters: what the detector can promise is the **branch** (A or B); L2 vs L3 is a stretch goal.

## Events (ground truth, never read by the detector)

| Event | When |
|---|---|
| `leak_on` | a tap is opened |
| `leak_off` | the tap is closed |
| `valve_change` | V1/V2 or R1/R2 moved: re-baseline needed |
| `pump_on` / `pump_off` | pump switched on / off |

Run metadata (with the label): `opening` (e.g. `small`, `large`, cap size), `measured_leak_lpm`
(cup + stopwatch), `blind` (true for the blind test: label filled in after), `notes`.
Storage and the `/api/events` endpoint: see `api.md`. The dashboard's event buttons post them.

Rules:

- A label applies from the moment the leak starts, not to the whole file. The
  simulator emits `none` before `leak_start_s`; real runs start the labelled run
  before opening the valve and press **Mark leak onset** at the valve. Samples
  before onset are `none`. A missed onset can be fixed with `tools.label_csv`.
- Stress runs (pump ripple, Wi-Fi dropout, recalibration) are `none`. They exist
  to catch false alarms; labelling them as leaks corrupts the evaluation.
- One leak at a time during data collection. Multi-leak scenarios are out of
  scope for this prototype.
- Record the leak size and repeat number in the run notes, not in the label.
