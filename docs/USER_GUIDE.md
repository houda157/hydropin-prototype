# HydroPin – user guide: how to run it, use it and see everything

This guide covers the bench chain (ESP32 → laptop → website), the website's five tabs, Telegram
alerts, the bench-day tools, and the simulations (farm, placement, drone, M3).

- **Measured vs simulated:** everything marked **simulation** on the website is simulation. The
  bench chain runs on real data once the bench is connected.
- **Commands:** PowerShell, run from the repo folder (`TSYP_AOTN`), one at a time.

**Contents**

1. [What you will see](#1-what-you-will-see)
2. [One-time setup](#2-one-time-setup)
3. [Quick demo, no hardware](#3-quick-demo-no-hardware)
4. [Using the website, tab by tab](#4-using-the-website-tab-by-tab)
5. [Running a test on the bench](#5-running-a-test-on-the-bench-live-mode)
6. [Live with the real ESP32](#6-live-with-the-real-esp32)
7. [Telegram alerts](#7-telegram-alerts)
8. [Bench day: from the tests to the results](#8-bench-day-from-the-tests-to-the-results)
9. [Farm and M3 (simulation)](#9-farm-and-m3-simulation)
10. [Checking that everything works](#10-checking-that-everything-works)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What you will see

| Interface | Where | What it is for |
|---|---|---|
| **Dashboard (website)** | Laptop: http://localhost:8000. Public: GitHub Pages link | The main screen. 5 tabs: Bench, Scoreboard, Farm, M3, What's real |
| **Farm explorer** | Bottom of the Farm tab, or its own page: `farm/explorer/index.html` (laptop: http://localhost:8000/farm-explorer/) | Interactive virtual farm: leaks, sensor spots, optimiser |
| **Twin viewer** | Its own page: `simulator/demo/hydropin_viewer.html` (laptop: http://localhost:8000/twin/hydropin_viewer.html) | The team's digital twin (farm, M1, M2, M3, fusion) |
| **Telegram** | Your phone | Messages on LEAK, sensor fault, resolved |

The dashboard has two modes:
- **Live:** only when the page is served by the laptop. It follows the bench in real time and has
  the test buttons.
- **Replay:** recorded runs played back. This is the only mode on the public link (GitHub Pages
  cannot reach the laptop).

Behind the website is a REST API (`/api/...`) and a WebSocket (`/ws`). They are plumbing,
described in `contract/api.md`; users don't need them.

---

## 2. One-time setup

**Platform environment** (backend, simulator, tests):

```powershell
py -3.13 -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
pip install -r requirements.txt
```

**Laptop settings** (Telegram, MQTT, database). Copy the template, then edit `.env`:

```powershell
Copy-Item .env.example .env
```

`.env` is gitignored: never commit it. Values set in the shell win over the file.

**Simulation environment:** the farm and M3 scripts (WNTR, torch) use `.venv-sim`, installed from
`requirements-sim.txt`. You only need it to *regenerate* simulation data; viewing the website
does not need it.

---

## 3. Quick demo, no hardware

The simulator pretends to be the bench and sends its data straight to the laptop program.

**Terminal 1: the laptop program (backend + website).**

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. To open it on a phone on the same WiFi, use `http://<laptop IP>:8000`.

**Terminal 2: a fake leak on tap L2, in real time.**

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
python -m simulator.bench_rev1 --scenario leak_L2 --realtime --post http://localhost:8000
```

**What happens on the Bench tab:**
1. PUMP_OFF, then SETTLING (20 s, water settles), then LEARNING (30 s, it learns "normal"), then
   HEALTHY.
2. At about 80 s the tap "opens": WATCH, then **LEAK, branch B**. The L2/L3 area glows red;
   L/min and litres lost start counting.
3. When the tap "closes", the state goes back to HEALTHY.

**Other scenarios:**

| Scenario | What it shows |
|---|---|
| `baseline` | Normal running, no alarm |
| `leak_L1`, `leak_L2`, `leak_L3` | A leak on that tap (add `--leak-size small`, `medium` or `large`) |
| `unplug_PT1`, `unplug_PT2` | "Sensor fault, not a leak" |
| `pump_restart` | Pump off then on: it re-learns, no false alarm |
| `wifi_gap` | 8 s without data: OFFLINE, then back |
| `ripple`, `dropout` | Noisy readings, missing readings |

List them all:

```powershell
python -m simulator.bench_rev1 --list
```

A small leak (the hardest case):

```powershell
python -m simulator.bench_rev1 --scenario leak_L1 --leak-size small --realtime --post http://localhost:8000
```

---

## 4. Using the website, tab by tab

The strip at the top of every tab shows: data source (LIVE or REPLAY), state, P(leak), branch.

### Bench (the main screen)

| Part | What it shows |
|---|---|
| Bench drawing | Pump, flow meter F0, branch A (L1, PT1), branch B (L2, PT2, L3). The suspected tap glows red; a sensor with a problem is greyed out |
| Detector | Big state word (HEALTHY / WATCH / LEAK / PUMP_OFF / SETTLING / LEARNING / OFFLINE), the leak-chance bar, branch, leak in L/min, litres lost, normal flow, PT1 − PT2 |
| Methods | Score of each clue: **Flow** (more water than normal) and **M2** (pressures dropping in an unusual way). Greyed out when a sensor fault excludes it |
| Faults | Chips such as "PT2 unplugged". A fault is never reported as a leak |
| Location | Bars for L1, L2, L3. L2 and L3 share branch B and one sensor, so the promise is **the branch** |
| Charts | Pressures, flow vs normal flow, and leak chance over time. Vertical lines mark "tap opened" and "alarm" |
| At farm scale | A line that appears once the market lead fills in `dashboard/config.js` |

**State rules:**
- leak chance above 50 % → **WATCH**;
- above 90 % for 5 seconds → **LEAK**.

**Mode buttons:**
- **Live:** follows the laptop. Greyed out on the public link.
- **Replay:** pick a recorded run, then use play/pause, speed and the slider.

### Scoreboard

- **Banner:** "Simulation" or "Measured on the bench". Once the detector is trained, the headline
  uses **test runs only** (runs it never learned from).
- **Tiles:** leak runs, % reaching LEAK, % reaching WATCH or LEAK, right branch, right tap, median
  delay, false-alarm runs, false alarms per hour.
- **Tables:**
  - results per tap and per leak size;
  - **each method alone vs combined**;
  - **tap opened vs tap the detector guessed**, misses included;
  - **blind test** (all events, misses included);
  - every run with its result and its split (train/test).

### Farm (simulation)

The farm is a virtual 50 ha drip farm: 6 sectors, 2,070 simulated leaks.

**View "Sensor placement"**
- Move the slider from 1 to 10 sensors; the map shows the chosen spots.
- The panel shows:
  - % of 3 % leaks traced to the right branch (main pipe or sector);
  - % of 3 % and 1 % leaks detected;
  - the same check on 10 other farm versions;
  - the kit cost in DT (292 DT per sensor is an assumption).
- "best: N" is the number of sensors the tool recommends.

**View "Leak + drone"**
1. Pick one of 10 example leaks.
2. Choose 3 / 6 / 10 sensors and the method: **M2** (pattern matching), **M1** (graph neural
   network) or **Fused**.
3. The map shows:
   - pipes turning red by leak probability;
   - a dashed ring on the real leak;
   - with **drone** ticked, the flight route with a moving dot.
4. The panels show the real and the most likely leak spot, take-off time (sunrise), flight time,
   route length, and whether the leaking pipe is on the route.
5. The small table shows how M2, M1 and Fused score on farm versions they never trained on.

**Further down the tab:** the **farm explorer** (also opens full screen). The twin viewer is not linked
from the dashboard; open it on its own page (see section 1).

### M3 (simulation)

1. Pick one of 4 cases (leak far, middle, near, or a pipe with creep).
2. **Sensor chart:** the pressure recorded at the valve vs a pipe with no leak. The gap is the leak's
   echo.
3. **Location curves:** time reversal and matched-field. The peak is the leak position.
4. **Table:** each method's estimate (echo, time reversal, matched-field, CNN) and its error in
   metres.

### What's real

A table, line by line: what is measured on the bench, what runs on real data, and what is
simulation (farm, placement, M1, drone, M3).

### Farm explorer (its own page)

- Go through the leaks one by one ("leak tour").
- Click sensor spots to add or remove sensors and watch the numbers change.
- Press ▶ to let the optimiser choose.
- It uses the same rules as the placement tool, so the numbers match.

---

## 5. Running a test on the bench (live mode)

Only when the page is opened from the laptop.

1. **Start run.** Fill in:
   - label: `leak_L1`, `leak_L2`, `leak_L3` or `none`;
   - opening (small / large);
   - measured leak (cup + stopwatch) if known;
   - **blind** if someone else opens the tap;
   - notes.
2. Wait for **HEALTHY** (about 50 s after the pump starts).
3. Open the tap and press **Open L1** (or L2, L3) at the same moment. Close it and press **Tap closed**.
4. Use **Pump on / Pump off** when you switch the pump.
5. After **any valve change**, press **Valve moved**, then **Re-baseline**. Otherwise the change
   looks like a leak.
6. **Stop run.** The run becomes a replay; **Export CSV** downloads the raw data.

The detector **never** sees the label or the buttons. They are only used to score it afterwards.

Test protocol (36 staged runs, quiet run, faults, blind test): see `docs/test_protocol.md`.

---

## 6. Live with the real ESP32

1. **Install Mosquitto** on the laptop. Open ports 1883 (MQTT) and 8000 (website) in the Windows
   firewall (PowerShell as admin):

```powershell
New-NetFirewallRule -DisplayName "HydroPin MQTT" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
```

```powershell
New-NetFirewallRule -DisplayName "HydroPin web" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

2. **Start the broker:**

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -c broker\mosquitto.conf -v
```

3. **In `.env`**, set `HYDROPIN_MQTT=1` (and `HYDROPIN_MQTT_HOST` if the broker is on another
   machine). Then start the backend:

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

4. **ESP32:** copy the secrets file, then fill in the WiFi name, password and the laptop's IP:

```powershell
Copy-Item firmware\include\secrets.example.h firmware\include\secrets.h
```

   Flash it and watch its output. Run these from the `firmware` folder (`cd firmware` first):

```powershell
pio run -t upload
```

```powershell
pio device monitor -b 115200
```

   The board prints each frame as one JSON line. The dashboard should show **LIVE (bench)** with
   values every 0.5 s.

5. **If WiFi fails, use the USB cable.** Install pyserial, then run the bridge (change COM5 to the
   board's port):

```powershell
pip install pyserial
```

```powershell
python -m tools.serial_bridge --port COM5 --post http://localhost:8000
```

**Test MQTT without the board:** the simulator publishes to the broker instead of posting to the
backend.

```powershell
python -m simulator.bench_rev1 --scenario leak_L1 --realtime --publish
```

---

## 7. Telegram alerts

1. In Telegram, talk to **@BotFather**, send `/newbot` and copy the token.
2. Send any message to your new bot. Then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `chat` → `id`
   number.
3. In `.env`, set `TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...` and `HYDROPIN_NOTIFY=1`.
4. Restart the backend and run the leak demo from section 3.

**Messages you get:**
- "HydroPin LEAK on branch B…";
- a message on each new sensor fault;
- "resolved" when the leak stops.

A Telegram problem never slows down the data: messages are sent in the background.

---

## 8. Bench day: from the tests to the results

After the test campaign, run these in order (database: `data/hydropin.db`).

1. **Sensor noise σ** from the longest quiet run (writes `data/noise.json`):

```powershell
python -m tools.noise --db data/hydropin.db
```

2. **Train the detector** on 70 % of the runs (blind runs always stay in the 30 % test part; writes
   `data/model.json`):

```powershell
python -m detection.train_bench --db data/hydropin.db
```

3. **Real replays and scoreboard** (the headline uses test runs only):

```powershell
python -m tools.export_replays --db data/hydropin.db
```

4. **Report charts** (written to `report/figures/bench_*.png`):

```powershell
.\.venv-sim\Scripts\python.exe -m detection.report_charts
```

5. **Twin vs real chart** (needs the twin's predictions in `twin/predictions.json`):

```powershell
.\.venv-sim\Scripts\python.exe -m twin.compare --db data/hydropin.db
```

The backend picks up `data/model.json` automatically on its next start.

**Rehearse all of it without the bench.** Write a fake campaign to a separate file (never to
`data/hydropin.db`); its runs are marked SIMULATED and stay labelled simulation:

```powershell
python -m tools.sim_campaign --db rehearsal.db
```

Then run the same commands with `--db rehearsal.db`.

---

## 9. Farm and M3 (simulation)

**Look without rebuilding anything:** the website's Farm and M3 tabs already have the data. The
farm explorer also opens by double-clicking `farm\explorer\index.html`.

**Regenerate the farm data** in this order (`.venv-sim`). Once the bench σ is measured, add
`--sigma-bar <σ>` to the first two commands.

1. Leak dataset:

```powershell
.\.venv-sim\Scripts\python.exe -m farm.leaks.generate
```

2. Sensor placement (`dashboard/farm/placement.json`):

```powershell
.\.venv-sim\Scripts\python.exe -m farm.placement.optimise
```

3. GNN, one per sensor set (torch):

```powershell
.\.venv-sim\Scripts\python.exe -m farm.methods.m1_gnn
```

4. M2 / M1 / fused results (`dashboard/farm/results.json`):

```powershell
.\.venv-sim\Scripts\python.exe -m farm.methods.results
```

5. Drone routes (`dashboard/farm/drone.json`):

```powershell
.\.venv-sim\Scripts\python.exe -m farm.drone.dispatch
```

6. Farm explorer data:

```powershell
.\.venv-sim\Scripts\python.exe -m farm.explorer.build_data
```

7. Report figures (software chain, placement, drone):

```powershell
.\.venv-sim\Scripts\python.exe -m tools.report_figures
```

**M3 dashboard files** (about 2 minutes):

```powershell
.\.venv-sim\Scripts\python.exe -m m3.export_dashboard
```

**Simulated bench replays and scoreboard:**

```powershell
python -m tools.export_replays --sim
```

All file formats: `contract/dashboard-data.md`.

---

## 10. Checking that everything works

Platform tests (backend, detector, simulator, tools, dashboard files):

```powershell
python -m pytest tests -q
```

Farm and M3 tests:

```powershell
.\.venv-sim\Scripts\python.exe -m pytest farm m3 -q
```

Digital twin tests (run from the `simulator` folder; about 4–13 minutes):

```powershell
python -m pytest tests -q -o addopts=""
```

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| "Live" button greyed out | The page isn't served by the laptop backend, or `/health` fails. Start `uvicorn` and open http://localhost:8000 |
| Dashboard shows OFFLINE | No data for 3 s. Check that the simulator/ESP32 is running, `HYDROPIN_MQTT=1` (for MQTT), the broker is up, and the firewall allows 1883 |
| Phone can't open the page | Use the laptop's IP, start uvicorn with `--host 0.0.0.0`, allow port 8000 in the firewall |
| False alarm right after moving a valve | Press **Valve moved** then **Re-baseline** after any valve change |
| Small leaks only reach WATCH | Expected: the flow meter sees 0.1 L/min steps. Use a bigger opening or a drilled cap |
| No Telegram message | Token and chat id in `.env`, `HYDROPIN_NOTIFY=1`, backend restarted, you sent the bot a message first |
| Serial bridge prints nothing | Wrong COM port, or the board is still booting. Check with `pio device monitor` first |
| Scoreboard says "Simulation" | Normal until `tools.export_replays --db data/hydropin.db` is run on the real campaign |
| Farm map empty | The `dashboard/farm/*.json` files are missing: run section 9 |
