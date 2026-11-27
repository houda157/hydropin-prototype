# Farm Leak Explorer – SIMULATION

An interactive "studio" console of the virtual farm and its 2,070 simulated leaks: the farm as a
tilted 3D model with **pressure pillars** at the 16 possible sensor spots (height = pressure drop),
numbered readout panels, a live sensor list, and a playback timeline (**leak tour** / **sensor budget**).

**Open it:** double-click `index.html` (any modern browser, no install, no server).

| Tab | What you can do | What it shows |
|---|---|---|
| **Explore a leak** | Choose the irrigation shift, click a leak spot on the model (or press ▶ for a tour of every spot), choose the size (1 / 3 / 10 %) and the farm version | Pillars and pipes by pressure drop. **Total drop**: every pillar rises (there *is* a leak). **Location clue**: only the extra drop beyond the average, so the pillars near the leak stand out (*where* it is) |
| **Place sensors** | Click the grey stubs (or the list) to place sensors, let the optimiser choose 1–10, or press ▶ to sweep the budget | How many of the 2,070 leaks those sensors notice (3σ rule), how often they point to the right field, the kit cost, the farm's blind spots, and where extra sensors stop helping |

**Why it matters:** this is a small version of the sensor-placement question (how few sensors still
catch the leaks, which sets the kit price), and it shows the core physics: a leak lowers every pressure,
and only small differences between sensors say where it is.

**Simplifications:** "right field" uses a simple rule (the sensor that drops most beyond the others'
average); the computer's choice is greedy picking + swaps. The placement tool (`farm/placement/`, greedy + genetic search,
re-tested on the 10 perturbed farm models) refines the numbers, not the trends. Costs: 217 DT per
sensor node + 75 DT per tapping point (master document).

**Update the data** after regenerating the leaks (e.g. with the measured bench σ):

```powershell
.venv-sim\Scripts\python -m farm.leaks.generate --sigma-bar <value>
.venv-sim\Scripts\python -m farm.explorer.build_data
```

| File | Role |
|---|---|
| `index.html` | the page (plain HTML + JavaScript, fonts from Google Fonts when online) |
| `farm-data.js` | generated from `farm/model/layout.json` and `farm/leaks/out/` by `build_data.py` (do not edit) |
| `build_data.py` | rebuilds `farm-data.js` |

Online copy (private until shared): https://claude.ai/artifact/ReqP73G29q9ypVn7msBZ1K
