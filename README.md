# hydropin-prototype

Real-time leak detection for a drip-irrigation test bench: ESP32 + one main flow sensor (F0) +
two branch pressure sensors (PT1 0..6 bar on branch A, PT2 -1..1.6 bar on branch B) -> MQTT ->
laptop backend -> dashboard. The detector is explainable (flow + M2 PCA/SVD on the two pressures
+ log-odds fusion) and says which branch leaks.

**Measured vs simulated:** the dashboard's "What's real" tab lists what was measured on the bench
and what is simulation. Until the bench campaign is exported, every result in this repo
(scoreboard, replays, farm, M3) comes from simulation and is labelled as such.

The design, methods and results are described in the technical report, delivered separately.

**How to run, use and see everything** (website tabs, bench tests, ESP32, Telegram, bench-day
commands, farm and M3, public link): **[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)**.

## Bench rev 1 (F0 + PT1 + PT2, taps L1-L3)

The bench as built has one flow meter (F0) and two pressure sensors (PT1 on branch A, PT2 on
branch B).

```powershell
python -m pip install -r requirements.txt

# backend + static dashboard (http://localhost:8000): live mode, replays, scoreboard, farm, M3
uvicorn backend.main:app
$env:HYDROPIN_MQTT="1"; uvicorn backend.main:app        # with the broker / real ESP32

# no bench at hand: stream a simulated run into the backend (scenarios: --list)
python -m simulator.bench_rev1 --scenario leak_L2 --realtime --post http://localhost:8000
python -m simulator.bench_rev1 --scenario baseline --realtime --publish       # over MQTT

# replays + scoreboard for the static site (GitHub Pages)
python -m tools.export_replays --sim                    # simulated, labelled "simulation"
python -m tools.export_replays --db data/hydropin.db    # the recorded bench campaign

# tests of the demo chain
python -m pytest tests -q
```

The research suites (`simulator/tests`, `m3/tests`, `farm/tests`) need `requirements-sim.txt`
(torch, WNTR); see the READMEs in those folders.

- `detection/bench_detector.py`: quality gate -> pump states -> `flow` + `m2` -> log-odds fusion ->
  `HEALTHY | WATCH | LEAK` (+ `PUMP_OFF`, `SETTLING`, `LEARNING`, `OFFLINE`), branch A/B, per-tap
  probabilities, leak size, litres lost. Same code live, in scoring and in the replay export; it
  never reads labels or events. Thresholds: `BenchConfig` (or `data/bench_detector.json`).
- Campaign in the dashboard: **Start run** (label, opening, measured leak, blind) -> press the event
  buttons when you open/close a tap, move a valve or switch the pump -> **Re-baseline** after any
  valve change -> **Stop run**. Each run is then a replay: `GET /api/runs/{id}/replay`.
- GitHub Pages: `.github/workflows/pages.yml` publishes `dashboard/` (+ the farm explorer and the
  twin viewer) on every push to `main`. Pages has replay mode only; live mode needs the laptop.

## Farmer app (the product, `dashboard/app/`)

What a farmer sees when a buried pipe leaks: the alert, where it is, how serious, the repair confirmed
by the sensors, and the money saved. Installable mobile web app (no build step), Français / العربية /
English. Design: `docs/design/2026-11-27-farmer-app-design.md`.

- **Live (the test bench):** open `http://localhost:8001/app/` (or `:8000`) while the backend runs. The
  bench is shown as what it is, "HydroPin test bench · 2 sectors" (branch A = Sector A, B = Sector B);
  money lines are projections ("If this leak happened on a 50 ha farm: about X DT").
- **Demo (GitHub Pages, no backend):** `<pages link>/app/`, always labelled "Demo farm".
- **For filming:** `?demo=leak` (starts on the leak), `?demo=fixed`, `?source=demo` (demo even on the
  laptop), `?lang=fr|ar|en`. Repair on the bench: `python -m simulator.bench_rev1 --scenario leak_L2
  --duration 220 --leak-stop 170 --realtime --post http://localhost:8001` (to a scratch backend, never
  into the campaign database).
- **Money saved** = (what the leak would lose unnoticed − what it lost) × price, from `FARM_SCALE` in
  `dashboard/config.js`: farm flow (m³/h), irrigation hours per day, days a buried leak runs before anyone
  sees it, price per m³. They are **example figures (placeholders)** until the market lead's figures; a
  null value shows "—". Severity: share of the pumped water lost (< 5 % small, < 15 % medium, else large).
- Backend support: `GET /api/leaks`, `POST /api/leaks/{id}/fixed` (leak episodes, `backend/leaks.py`).
- Tests: `node --test "dashboard/app/tests/*.test.js"` (Node 22) and `pytest tests`.

## Laptop settings (.env)

Copy `.env.example` to `.env` and fill it in: Telegram bot token and chat id
(`HYDROPIN_NOTIFY=1` to send), `HYDROPIN_MQTT=1` to listen to the ESP32 through the broker, and the
database path. The backend reads `.env` at start; variables set in the shell win. Never commit `.env`.

## Bench day: from the campaign to the scoreboard

```powershell
python -m tools.noise --db data/hydropin.db              # sigma from the longest quiet run -> data/noise.json
python -m detection.train_bench --db data/hydropin.db    # 70/30 split, blind = test -> data/model.json
python -m tools.export_replays --db data/hydropin.db     # replays + scoreboard.json (headline on test runs)
python -m detection.report_charts                        # report/figures/bench_*.png (.venv-sim)
python -m twin.compare --db data/hydropin.db             # twin vs real (needs twin/predictions.json)
python -m tools.serial_bridge --port COM5 --post http://localhost:8000   # USB fallback if WiFi fails
```

Rehearse all of it without the bench: `python -m tools.sim_campaign --db <scratch>.db` (runs are
marked SIMULATED and stay labelled simulation).

## Farm (simulation): placement, M1/M2, drone

Run in `.venv-sim`, in this order (once the bench sigma is measured, pass `--sigma-bar` to the first two):

```powershell
python -m farm.leaks.generate
python -m farm.placement.optimise      # dashboard/farm/placement.json + 3/6/10 sets
python -m farm.methods.m1_gnn          # GNN per sensor set (torch)
python -m farm.methods.results         # dashboard/farm/results.json + report chart
python -m farm.drone.dispatch          # dashboard/farm/drone.json
python -m farm.explorer.build_data
python -m tools.report_figures         # software chain, placement, drone figures
```

File formats: `contract/dashboard-data.md`.

## Real bench data

```powershell
# calibrate first (prints the constants to copy into both config files)
python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60
python -m tools.calibrate pressure --point 0:0 --point 8889:2 --point 17778:4 --point 26667:6

# training and scoring of the bench detector: see "Bench day" above
```

In the dashboard, start a run before the leak and press **Open L1/L2/L3** when the tap opens (and
**Tap closed** when it closes); only samples after that instant inherit the run label. The
`/api/export.csv` file includes raw pulses, raw pressure ADC and the `clipped` flag, so the
calibration fitter can run on exported runs too.

## Layout

- `contract/` shared message schema, labels and API (changed only together)
- `broker/` local MQTT broker config
- `firmware/` ESP32 PlatformIO project (ADS1115 PT1/PT2 + main flow ISR + MQTT)
- `hydropin/` shared Python: config, units, message parsing
- `simulator/` digital twin `hydropin_sim/` (physics, sensors, M1/M2/M3, prototype bench; see simulator/README.md)
  + rev 1 bench simulator `bench_rev1.py` (F0 + PT1 + PT2, taps L1-L3, stress and fault scenarios)
- `detection/` rev 1 bench detector `bench_detector.py`, replay/scoring `replay.py`, campaign
  training (`train_bench.py`), report charts
- `backend/` FastAPI + SQLite + MQTT listener + REST/WebSocket; serves the static dashboard at `/`
- `dashboard/` static dashboard (`index.html`, live + replay, no build step; published on Pages),
  its data (`replays/`, `scoreboard*.json`, `farm/`, `m3/`), the 3D bench (`bench3d/`) and the farmer app (`app/`)
- `farm/`, `m3/` virtual farm + leak dataset, M3 pressure-wave method (simulation; see their READMEs)
- `tools/` calibration fitter, noise σ, replay/scoreboard export, serial bridge, simulated campaign, report figures
- `data/` runs, database, calibration notes
- `docs/` user guide, wiring, test protocol, design notes (`docs/design/`)
- `twin/` twin-vs-real comparison

## Calibration warning

The flow gain `1.5` is **provisional**; verify it with a measured volume before
trusting any leak size. The pressure fits use the real rev 1 sensors:
**PT1 0..6 bar on A0**, **PT2 -1..1.6 bar on A1**, both through
**20k series + 10k shunt** (ratio 3.0, not 3.2). The bench has one main flow
sensor, not branch flow sensors, so live branch localisation is not validated
yet. See `data/calibration.md` and `python -m tools.calibrate --help`.

## Firmware

The firmware compiles for `esp32dev` with PlatformIO 6.2.0 and
`espressif32@6.9.0` (RAM 14.1%, flash 58.9%). It has **not** been flashed or run
on hardware yet.

```powershell
cd firmware
copy include\secrets.example.h include\secrets.h   # then edit Wi-Fi + broker
pio run
pio run -t upload
pio device monitor -b 115200
```
