# M3 tab data – format v1.1 (proposal for `contract/dashboard-data.md`)

**Everything here is simulation** (M3 runs in simulation only, team decision 21 Nov). Show a
clear "Simulation" label on the M3 tab. Made by `python -m m3.export_dashboard` (~2 min).

## Files

| File | Content |
|---|---|
| `index.json` | list of cases, for the case picker |
| `m3_case_01.json` … `m3_case_04.json` | one showcase case each (~190 KB) |

| Case | Story |
|---|---|
| 01 | leak 115 m from the sensor: the echo returns after 0.66 s |
| 02 | leak 60 m from the sensor: echo after 0.34 s |
| 03 | leak 15 m from the sensor: echo after 86 ms |
| 04 | PE pipe with creep, located with the model calibrated on one leak-free test |

## `index.json`

`version`, `simulation: true`, `label`, `methods` (key → name: `tr` time reversal, `mfp` matched-field,
`echo` echo timing, `cnn` 1D CNN), `cases[]`: `id, file, title, story, pipe ("elastic" | "creep"),
x_true_m, error_m{tr, mfp, echo, cnn}, size_kb`.

## A case file

Positions are metres from the reservoir (x = 0). The valve and the sensor are at x = L = 150 m.
Heads are metres of water (10 m ≈ 1 bar).

| Field | Content | Suggested use on the M3 tab |
|---|---|---|
| `id, title, story` | text | case picker, caption |
| `pipe` | `kind, length_m, diameter_m, wave_speed_mps, reservoir_head_m, sensor_x_m, valve_x_m, creep_scale, note` | pipe drawing (reservoir left, valve + sensor right) |
| `leak` | `x_true_m, distance_from_sensor_m, fraction_of_flow, flow_lps` | true-leak marker |
| `valve` | `closure_start_s, closure_time_s, joukowsky_m` | "valve closes" moment, expected surge |
| `timing` | `echo_expected_s, reservoir_return_s` | markers on the sensor chart |
| `frames` | `dt_s` (0.005), `t_s[n]`, `x_m[121]`, `H_m[n][121]`: head along the pipe at each frame (n = 211, 0–1.05 s) | **wave animation**: draw `H_m[k]` vs `x_m`, step k every frame |
| `sensor` | `fs_hz` (2000), `noise_sigma_m`, `t0_s`, `dt_s`, `H_m[2600]` (noisy recording, 0–1.3 s), `model_H_m[2600]` (intact-pipe model) | **sensor trace** chart; the gap between the two lines is the leak's echo |
| `tr` | `x_m[151]`, `energy[151]` (0–1), `x_est_m` | **time-reversal "energy vs position" curve**, peak = estimate |
| `mfp` | `x_m[149]`, `match[149]` (0–1), `x_est_m` | optional second curve (matched-field) |
| `estimates_m` | `tr, mfp, echo, cnn` | estimate markers |
| `error_m` | same keys: \|estimate − true\| | "error: 0.2 m" badges |
| `model` | `kind` ("elastic, nominal" or "calibrated"), `wave_speed_mps, darcy_f, creep_scale, calibration{…}` | case 04: "calibrated on one leak-free valve test" |
| `wave_speed_identified_mps` | the wave speed read off the recording | info line |

## Suggested M3 tab (video 2:15–2:40)
1. Pipe drawing with the leak; press play → the wave runs from the valve to the reservoir (`frames`).
2. Below it, the sensor trace with markers for the closure, the expected echo and the reservoir return.
3. Then the time-reversal curve rising to a peak at the leak, with the true position and "error 0.0 m".
4. Case 04 adds: "real PE pipes absorb the wave; one calibration test fixes it".
