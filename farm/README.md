# farm/ – simulated farm (role 5) – SIMULATION ONLY

WNTR model of a 50 ha Tunisian drip farm, plus a leak dataset for sensor placement
(role 2) and the GNN / farm M2 (role 4). Assumptions are all in `model/params.yaml`.

```powershell
py -3.13 -m venv .venv-sim
.venv-sim\Scripts\python -m pip install -r requirements-sim.txt
.venv-sim\Scripts\python -m farm.model.build_farm       # print pressures per shift
.venv-sim\Scripts\python -m farm.model.export_layout    # layout.json, farm.inp, perturbed/*.inp
.venv-sim\Scripts\python -m farm.model.plot_farm        # report/figures/farm_layout.png
.venv-sim\Scripts\python -m farm.leaks.generate         # leak dataset (~30 s)
.venv-sim\Scripts\python -m pytest farm/tests
```

| Folder | Owner | Content |
|---|---|---|
| `model/` | role 5 | farm model, parameters, layout, perturbed models |
| `leaks/` | role 5 | scenario grid, simulation, dataset in `leaks/out/` (format: `leaks/FORMAT.md`) |
| `placement/`, `drone/` | role 2 | sensor placement, drone dispatch |
