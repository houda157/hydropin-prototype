# Finish phase 3 (27 Nov) — team plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Most tasks here are done by people at the bench; the code tasks (6, 8, 9) are marked.

**Goal:** submit today a working prototype (public link), a report of 6 pages or less and a ~3 min video, with real bench data behind the scoreboard.

**Architecture:** ESP32 (Moetez's firmware, powered by the external 5 V) → Wi-Fi (iPhone hotspot) → MQTT broker on Israa's laptop (`amqtt`, port 1883) → backend (port 8001) → dashboard live + campaign → `tools.export_replays` → GitHub Pages from `main`. The farmer app is a separate page, built after its design is approved.

**Tech Stack:** PlatformIO (ESP32), amqtt (broker), FastAPI + SQLite backend, static dashboard, GitHub Actions Pages.

**Spec:** `CONTEXT.md` and `docs/roles/` (team brief and per-role "done when"), `docs/test_protocol.md` (campaign), `docs/USER_GUIDE.md` §5–8 (bench day commands), the farmer-app mockups in `.superpowers/brainstorm/` (not yet a design doc). The CONTEXT/roles/specs files are untracked: they are on Israa's laptop only.

## Global Constraints

- **One power source at a time on the ESP32.** The external 5 V feeds the ESP32 and the flow sensor. To plug USB (flash or monitor): external 5 V **OFF** first. With the external 5 V on: no USB cable.
- Data path is **Wi-Fi + MQTT**, not USB (because of the rule above).
- The ESP32 only sees **2.4 GHz** Wi-Fi: on the iPhone hotspot, turn **Maximize Compatibility** on.
- Broker address for the firmware: **`172.20.10.4`**, port **1883** (Israa's laptop on the hotspot, checked 27 Nov ~11:00; re-check with `ipconfig` if the laptop reconnects).
- Backend on **port 8001** (port 8000 is held by an old `python -m http.server` from 05:07). Dashboard: http://localhost:8001.
- Campaign database: `data/hydropin.db` (empty and clean at 11:00). Never write rehearsal or test data into it.
- Pressure divider is **20k + 10k, ×3.0** on both sensors (confirmed by Israa). The backend recomputes bar from raw ADC counts with ×3.0, so detection is right whatever the firmware divider.
- `firmware/` on `integration/main-v1` = Talel's branch version (commit `aa5dd4f`), so Moetez's firmware merges without conflicts.
- Honesty rule (CONTEXT §7): say what is measured and what is simulated; score only on runs the detector was not tuned on.
- No AI co-author lines in commits; push from team members' own accounts.

## Review Focus

- **Board reboots mid-campaign** (USB replug, brownout): frames must keep arriving (fixed in `7beff0b`; check once in Task 2).
- **No internet on the hotspot** (NTP fails, board sends 1970 timestamps): backend switches to laptop time (fixed in `7beff0b`); check the dashboard clock in Task 2.
- **Laptop IP changes** after a hotspot reconnect: the board can no longer reach the broker; `/health` shows `received` stuck. Re-run `ipconfig`, reflash if the IP moved.
- **Windows Firewall blocks port 1883** for `amqtt.exe`: the board connects to Wi-Fi but never to MQTT. Allow it on the prompt (private and public).
- **A valve moved between runs** without Re-baseline: looks like a leak. Press Valve change + Re-baseline after every valve change.

---

### Task 1: Firmware on the hotspot (Moetez, Talel)

- [ ] **Step 1:** External 5 V **OFF**. Plug the ESP32 into Moetez's laptop by USB.
- [ ] **Step 2:** In `firmware/include/secrets.h` (never committed): `WIFI_SSID` / `WIFI_PASSWORD` = the iPhone hotspot, `MQTT_HOST "172.20.10.4"`, `MQTT_PORT 1883`.
- [ ] **Step 3:** `pio run -t upload`, then `pio device monitor` at the firmware's baud rate. Expected: `[wifi] ip 172.20.10.x` then `[mqtt] connecting...ok` (needs Task 2 step 1 running). Unplug USB.
- [ ] **Step 4:** Push the firmware Moetez flashed to a branch (`fix/bench-firmware`) from his own account, so Task 6 can merge it.

### Task 2: Live values on the dashboard (Israa + Claude)

- [ ] **Step 1:** Broker and backend running on Israa's laptop (done at 11:00): `amqtt -c broker/amqtt.yaml`; `HYDROPIN_MQTT=1` backend on port 8001.
- [ ] **Step 2:** USB unplugged, external 5 V **ON**. Expected: `http://127.0.0.1:8001/health` → `mqtt.received` grows by 2 per second; dashboard Bench tab → Live shows F0, PT1, PT2.
- [ ] **Step 3:** Sanity: pump off → PT1 ≈ 0 bar, PT2 ≈ 0 bar, F0 = 0. Pump on → both pressures steady above 0, F0 > 0, state SETTLING → LEARNING → HEALTHY within ~50 s.
- [ ] **Step 4:** Reboot check: switch the external 5 V off and on once. Expected: frames resume within ~20 s.

### Task 3: Calibration and quiet run (Israa + Moetez, ~30 min)

- [ ] **Step 1:** Flow: pump into a measuring jug for 60 s, note litres and the pulse count from the dashboard / export. Claude runs `python -m tools.calibrate flow --pulses <n> --litres <L> --seconds 60`. The live L/min is computed **in the firmware**, so the new `FLOW_GAIN` goes in both `hydropin/config.py` and Moetez's `config.h`, and Moetez reflashes (external 5 V off first). Do it **before** Task 4 so every campaign run uses the same gain.
- [ ] **Step 2:** Quiet run: Start run label `none`, 10 min, nothing touched, Stop run. This is the noise run for `tools.noise`.

### Task 4: Leak campaign (Israa + one teammate, ~2.5 h)

Per run: Start run (label, opening small/medium/large, measured leak if known, blind if someone else opens) → wait HEALTHY → open the tap and press **Leak on** at the same instant → 60 s → close, press **Leak off** → 30 s → Stop run.

- [ ] **Step 1:** 3 baseline runs (`none`, 3 min each).
- [ ] **Step 2:** 27 leak runs: L1, L2, L3 × small/medium/large × 3, in a **random order**.
- [ ] **Step 3:** Stress runs labelled `none`: pump off/on, one valve change (+ Re-baseline), Wi-Fi off for 10 s.
- [ ] **Step 4:** 3–5 **blind** runs: a teammate opens a tap Israa does not know.
- [ ] If short of time, the minimum: 3 taps × 2 sizes × 2 repeats = 12 leak runs + 2 baseline + 2 stress + 3 blind (~1.2 h).

### Task 5: Real results (Claude, ~20 min) — code-free commands

- [ ] **Step 1:** `python -m tools.noise --db data/hydropin.db` → `data/noise.json`.
- [ ] **Step 2:** `python -m detection.train_bench --db data/hydropin.db` → `data/model.json` (blind runs stay in the test part).
- [ ] **Step 3:** `python -m tools.export_replays --db data/hydropin.db` → `dashboard/replays/` + `dashboard/scoreboard.json`. Expected: What's real tab says "measured"; scoreboard banner says "Measured on the bench".
- [ ] **Step 4:** Commit the exported files (not the database), push.

### Task 6: Merge Moetez's firmware (Claude) — code

- [ ] **Step 1:** Merge `fix/bench-firmware` into `integration/main-v1`. Expected: no conflict.
- [ ] **Step 2:** Remove the `xfail` mark on `test_pressure_divider_matches` in `tests/test_firmware_config.py`; run `python -m pytest tests -q`. Expected: all pass (divider ×3.0 on both sides). If his `DEVICE_ID`, period or window differ from `hydropin/config.py`, align `hydropin/config.py`.
- [ ] **Step 3:** Commit, push.

### Task 7: Go public (Houda for settings, Claude for the merge, ~30 min)

- [ ] **Step 1 (Houda, repo owner):** Settings → General → make `houda157/hydropin-prototype` **public**; Settings → Pages → Source: **GitHub Actions**.
- [ ] **Step 2 (Claude):** fast-forward `main` to `integration/main-v1`, push. Expected: the `pages` workflow runs green.
- [ ] **Step 3:** Open the Pages link on a phone: Bench replays, Scoreboard, Farm, M3, What's real, `/farm-explorer/`, `/twin/hydropin_viewer.html` all load.

### Task 8: Farmer app (Israa decides, Claude builds) — code, separate plan

- [ ] **Step 1 (Israa):** settle the open design points: normal-day Home with the farm view (irrigating / at rest), app language (Tunisian Arabic / Arabic / French), past alerts = option A (simple list, chosen).
- [ ] **Step 2 (Claude):** write the short design doc, get Israa's OK, then its own implementation plan (`docs/superpowers/plans/2026-11-27-farmer-app.md`) and build it as a page of the dashboard site fed by the farm simulation and the live bench state.

### Task 9: WhatsApp alerts (Claude + a spare SIM) — code, separate plan

- [ ] **Step 1 (team):** a spare phone number with WhatsApp (risk of ban: never a personal number).
- [ ] **Step 2 (Claude):** check OpenWA (open-wa.org) code and maintenance, run it on the laptop, send the LEAK / resolved messages from `backend/notify.py` next to Telegram. Telegram stays as backup.

### Task 10: Video, report, submit (whole team, Israa leads the pitch)

- [ ] **Step 1:** Report ≤ 6 pages: role sections (`report/sections/`), measured scoreboard from Task 5, what is simulated (farm, M3) said plainly.
- [ ] **Step 2:** Video ~3 min: bench leak live on the dashboard (real), scoreboard, farm + M3 (labelled simulation), farmer app, the Pages link.
- [ ] **Step 3:** Submit: link + repo + report + video. **Confirm the exact deadline time first** — it sets where to cut (cut order: Task 9, then Task 8 down to mockups, then the campaign down to the minimum matrix).

## Order and owners

| When | Bench (Israa, Moetez, Talel) | Laptop (Claude) | Others |
|---|---|---|---|
| now | Task 1 | broker + backend ready (done) | Houda: Task 7 step 1 |
| +30 min | Task 2, Task 3 | Task 3 calibration math, Task 6 when Moetez pushes | report sections (Talel, Eya, Kmar) |
| +1 h → +3.5 h | Task 4 | Task 8 / Task 9 in parallel | video script (Israa) |
| +3.5 h | — | Task 5, Task 7 step 2 | |
| last 3–4 h | filming | fixes only | Task 10 |
