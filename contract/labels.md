# Labels

Allowed run labels: `none`, `leak_L1`, `leak_L2`, `leak_L3`.

| Label | Meaning |
|---|---|
| `none` | healthy run: no leak, including ripple/dropout/calibration-drift stress runs |
| `leak_L1` | leak on branch L1 (downstream of the L1 flow sensor) |
| `leak_L2` | leak on branch L2 |
| `leak_L3` | leak on branch L3 |

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
