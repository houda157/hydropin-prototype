# farm/ – simulated farm – SIMULATION ONLY

WNTR model of a 50 ha Tunisian drip farm, plus a leak dataset for sensor placement and for leak
localisation (GNN M1, farm M2). Assumptions are all in `model/params.yaml`.

```powershell
py -3.13 -m venv .venv-sim
.venv-sim\Scripts\python -m pip install -r requirements-sim.txt
.venv-sim\Scripts\python -m farm.model.build_farm       # print pressures per shift
.venv-sim\Scripts\python -m farm.model.export_layout    # layout.json, farm.inp, perturbed/*.inp
.venv-sim\Scripts\python -m farm.model.plot_farm        # report/figures/farm_layout.png
.venv-sim\Scripts\python -m farm.leaks.generate         # leak dataset (~30 s)
.venv-sim\Scripts\python -m farm.explorer.build_data    # data for the explorer page
.venv-sim\Scripts\python -m pytest farm/tests
```

**See it:** double-click `explorer/index.html` – an interactive map to explore any leak and test
sensor placements against all 2,070 leaks.

| Folder | Content |
|---|---|
| `model/` | farm model, parameters, layout, perturbed models |
| `leaks/` | scenario grid, simulation, dataset in `leaks/out/` (format: `leaks/FORMAT.md`) |
| `explorer/` | interactive map of the farm and its leaks (`index.html`) |
| `docs/` | `DATA_PIPELINE.md`: how the data is made, its fields, how it is used |
| `placement/` | sensor placement: greedy + swaps + genetic search, robustness on perturbed farms |
| `methods/` | leak localisation on the farm: M2 (fingerprints), M1 (GNN), fusion |
| `drone/` | simulated drone dispatch (sunrise route over the most likely pipes) |
