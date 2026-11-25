# Farm Leak Explorer – SIMULATION

An interactive map of the virtual farm and its 2,070 simulated leaks.

**Open it:** double-click `index.html` (any modern browser, no install, no server).

| Tab | What you can do | What it shows |
|---|---|---|
| **1 · Explore a leak** | Choose the irrigation shift, click a leak spot on the map, choose the size (1 / 3 / 10 %) and the farm version | Pipes and sensor spots coloured by pressure drop. **Total drop**: almost everything drops (there *is* a leak). **Location clue**: only the extra drop beyond the average, which lights up the leaking area (*where* it is) |
| **2 · Place sensors** | Click the squares to place sensors, or let the computer choose 1–10 | How many of the 2,070 leaks those sensors notice (3σ rule), how often they point to the right field, the kit cost, and the farm's blind spots |

**Why it matters:** this is a small version of Role 2's sensor-placement question (how few sensors still
catch the leaks, which sets the kit price), and it shows the core physics: a leak lowers every pressure,
and only small differences between sensors say where it is.

**Simplifications:** "right field" uses a simple rule (the sensor that drops most beyond the others'
average); the computer's choice is greedy picking + swaps. Role 2's real tool (greedy + genetic search,
re-tested on the 10 perturbed farm models) will refine the numbers, not the trends. Costs: 217 DT per
sensor node + 75 DT per tapping point (master document).

**Update the data** after regenerating the leaks (e.g. with Role 1's measured σ):

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
