# HydroPin technical report – Overleaf project (first draft)

**Template:** IEEE Conference Template (`\documentclass[conference]{IEEEtran}`, two columns). This
is the usual format for a ≤ 6-page IEEE-style technical report. `IEEEtran.cls` ships with
Overleaf and TeX Live, so nothing else needs to be uploaded.

## Open it in Overleaf
1. Overleaf → **New Project → Upload Project** → choose `hydropin_report_overleaf.zip`.
   - Or: open Overleaf's "IEEE Conference Template", then replace its `main.tex` with this one
     and upload the `figures/` folder.
2. Compiler: pdfLaTeX (the default).
3. Everything still waiting for the real bench is in **red** (`\TODO{...}`). Search for `TODO`.

## What is in the draft
| Section | Content | Status |
|---|---|---|
| Abstract, I Introduction, II System overview | Problem, pipeline, contributions, software chain (Fig. 1) | done |
| III Laboratory bench | Bench layout, Table I sensors and calibration | **TODO:** bench photo, measured σ, flow K |
| IV Leak detection | Quality gate, pump states, flow + M2, fusion, location; simulated validation (Table II, Figs. 2–3) | done (simulation, labelled) |
| V Farm (simulation) | Virtual farm, sensor placement and cost, M2/M1/fusion, drone (Figs. 4–6, Table III) | done |
| VI M3 (simulation) | MOC solver, validation, four locators, accuracy (Figs. 7–8, Table IV) | done |
| VII Platform and dashboard | Contract, backend, dashboard, campaign tooling (Fig. 9) | done |
| VIII Bench results | Calibration, campaign, blind test, twin vs real | **TODO: real data** |
| IX What is real | Status table | update the bench row after the campaign |
| X Conclusion, references | — | References checked (27 Nov); **TODO:** confirm article number 111967 of the 2025 Waqar paper |

## Figures (`figures/`)
| File | Made with |
|---|---|
| `dash_*.png`, `farm_explorer.png` | Dashboard screenshots, headless Chrome at 2×, static site (replay mode) |
| `software_chain.png`, `farm_placement.png`, `farm_drone_route.png` | `python -m tools.report_figures` |
| `farm_layout.png` | `farm/model/plot_farm.py` |
| `farm_m1_m2_fused.png` | `python -m farm.methods.results` |
| `m3_*.png` | `m3/` scripts |

Spare figures, not used yet:
- `farmer_app.png`: the farmer app, demo leak in sector B, two phone screens. It shows the demo
  user name "Mr Moez".
- `farm_explorer.png` (old look, from before the re-skin), `farm_drone_route.png`,
  `farm_m1_m2_fused.png`, `m3_accuracy.png`, `m3_time_reversal.png`, `m3_viscoelastic.png`.

The dashboard screenshots were retaken on 27 Nov after the farmer-app re-skin was merged; the
Bench tab uses its 2D view, because the 3D view does not render in headless capture.

After the campaign, add `report/figures/bench_ttd_hist.png`, `bench_confusion.png` and
`bench_example_run.png`, made by `python -m detection.report_charts` from the **real**
scoreboard, to Section VIII.

## Page budget (≤ 6 pages)
The draft has not been compiled yet. It is about 3,800 words with 9 figures and 5 tables, so
expect it to run over 6 pages once Section VIII is filled. Cut in this order:
1. the Scoreboard screenshot (Fig. 9): Section VIII will show the real charts;
2. Fig. 3 (sensor fault), replaced by one sentence;
3. Fig. 4 (farm layout): the Farm tab screenshot (Fig. 6) already shows the farm;
4. the bullet lists in Sections IV-D and VII, turned into short sentences.
