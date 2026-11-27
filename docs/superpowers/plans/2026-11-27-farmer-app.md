# HydroPin Farmer App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An installable mobile web app at `dashboard/app/` that tells a farmer, in Français / العربية / English, whether a buried pipe leaks, where, how severe it is, and how much money the repair saved — live from the laptop backend, or as a labelled demo on GitHub Pages.

**Architecture:** Vanilla ES modules, no build. Pure logic in `dashboard/app/lib/` (tested with `node --test`), drawing in `farm.js`, two data sources with the same snapshot shape (`liveSource` polls the FastAPI backend, `demoSource` plays a script), screens rendered by `main.js` from a hash router. The backend gains leak episodes (`leaks` table, `GET /api/leaks`, `POST /api/leaks/{id}/fixed`).

**Tech Stack:** HTML/CSS/ES modules, Node 22 test runner, FastAPI + SQLite + pytest, Service Worker + Web App Manifest.

**Spec:** `docs/superpowers/specs/2026-11-27-farmer-app-design.md` (read it first; mockups: `.superpowers/brainstorm/138-1795757748/export/farmer-app-mockups.png`, live HTML `.superpowers/brainstorm/138-1795757748/content/farmer-app-hifi.html` — reuse its CSS and SVG).

## Global Constraints

- No build step, no npm packages; `dashboard/app/package.json` is `{"type": "module", "private": true}` only so Node treats `.js` as ES modules.
- The app lives in `dashboard/app/` and is reached at `/app/` (backend) and `<pages>/app/` (Pages, which copies `dashboard/`). All URLs inside the app are relative.
- Tokens: primary `#15803D`, danger `#DC2626` (leak only), warning `#A16207`, water `#1D5FA8`, background `#F0FDF4`, card `#FFFFFF`, text `#14532D`, muted `#475569`, border `#D7EFDF`. Font `Inter, system-ui, sans-serif`.
- One sentence + one primary button per screen; every number except money sits behind a closed **Details**; icons always with a text label; touch targets ≥ 44 px.
- Severity thresholds: `share < 0.05` small, `< 0.15` medium, otherwise large (`SEVERITY = {medium_from: 0.05, large_from: 0.15}` in `dashboard/config.js`).
- Money: `saved_m3 = max(0, share × farm_flow_m3_per_h × irrigation_hours_per_day × days_to_notice_without_hydropin − lost_m3)`, `saved_dt = saved_m3 × price_dt_per_m3`; bench `lost_m3 = lost_l / 1000 × farm_flow_m3_per_h / (base_lpm × 0.06)`; any null parameter → money `null`, shown "—".
- Demo placeholders (only in demo mode, labelled "estimate"): `farm_flow_m3_per_h 200, irrigation_hours_per_day 8, days_to_notice_without_hydropin 10, price_dt_per_m3 0.25`.
- Demo mode is always labelled "Demo farm" (farmer "Mr Moez", 4 sectors). Live mode is the test bench as a mini-farm: name "HydroPin test bench", badge "Test bench · 2 sectors", sectors A and B = bench branches A and B; its money lines are projections ("If this leak happened on a {area} ha farm: about {dt} DT").
- Languages `fr` (default), `ar` (RTL, `ar-TN` locale, Latin digits), `en`; key parity across the three.
- Tests: `node --test dashboard/app/tests/` and `.venv/Scripts/python -m pytest tests -q` must both pass after every task.
- Commits: no AI co-author lines.

## Review Focus

- **Backend goes quiet** (laptop asleep, board unplugged): the app must show "No news from your sensors", never a stale "Everything is fine" → Task 2 test `offline when state OFFLINE or frame null`.
- **Farm figures not filled in** (`FARM_SCALE` nulls, the case today): money shows "—", never `NaN` or `0 DT` → Task 2 test `money is null when a parameter is missing`.
- **Pump stopped during a leak**: the episode must not close itself as "fixed" on the next HEALTHY (baseline re-learned with the leak inside) → Task 1 test `test_pump_stop_keeps_episode_open`.
- **Missing translation / Arabic layout**: no raw key or wrong direction on screen → Task 3 tests `same keys and placeholders in fr, ar, en` and `isRtl`.
- **"I fixed it" tapped twice, or on an old leak**: idempotent, keeps the first time; unknown id → 404 → Task 1 test `test_fixed_is_idempotent_and_unknown_is_404`.

---

### Task 1: Leak episodes in the backend

**Files:**
- Modify: `backend/storage.py` (add `leaks` table to `SCHEMA`; add the functions below)
- Create: `backend/leaks.py`
- Modify: `backend/ingest.py` (call `track_leak` after `storage.insert_frame`)
- Modify: `backend/api.py` (two routes)
- Modify: `backend/main.py` (MIME types for `.js` and `.webmanifest`)
- Test: `tests/test_leaks.py`

**Interfaces:**
- Produces (storage): `open_leak(conn, started_ts: str, branch: str | None, base_lpm: float | None) -> int`; `update_leak(conn, leak_id: int, branch: str | None, leak_lpm: float, lost_l: float) -> None` (keeps the max `leak_lpm`, latest `lost_l`, latest non-null `branch`); `mark_pump_stopped(conn, leak_id: int) -> None`; `close_leak(conn, leak_id: int, ended_ts: str) -> None`; `get_open_leak(conn) -> dict | None` (newest row with `ended_ts IS NULL` and `user_fixed_ts IS NULL or pump_stopped = 0`); `mark_leak_fixed(conn, leak_id: int, ts: str) -> dict | None` (sets `user_fixed_ts` only if null; returns the row with `status`, `None` if unknown); `list_leaks(conn, limit: int = 20) -> list[dict]` newest first, each row plus `status`.
- Produces (status rule): `fixed` if `ended_ts` is set, or if `pump_stopped` and `user_fixed_ts` are both set; `checking` if `user_fixed_ts` set and not fixed; else `open`.
- Produces (leaks.py): `track_leak(conn, frame: dict) -> int | None` — stateless (the DB is the state): LEAK → open if none open, then `update_leak(frame["branch"], frame["leak_lpm"], frame["lost_l"])`; PUMP_OFF → `mark_pump_stopped` on the open one; HEALTHY → `close_leak` if open and not `pump_stopped`; other states → nothing. Returns the open/updated leak id or `None`.
- Produces (API): `GET /api/leaks?limit=20` → `list[dict]` with keys `id, started_ts, ended_ts, branch, base_lpm, max_leak_lpm, lost_l, pump_stopped, user_fixed_ts, status`; `POST /api/leaks/{leak_id}/fixed` → the row, 404 `{"detail": "leak not found"}` if unknown.

- [ ] **Step 1: Write the failing tests** in `tests/test_leaks.py`:

```python
def _frame(state, ts, branch="B", base=1.5, leak=0.3, lost=0.1):
    return {"ts": ts, "state": state, "branch": branch, "flow_base_lpm": base, "leak_lpm": leak, "lost_l": lost}

def test_episode_opens_on_leak_and_closes_on_healthy(tmp_path):
    # end to end: simulator leak on L1 that stops at 130 s, streamed through /api/ingest
    msgs = simulate(build("leak_L1", leak_stop_s=130.0, duration_s=200))
    # ... ingest all with TestClient(create_app(db_path=tmp_path/"b.db", baseline_path=None, start_mqtt=False, static_dir=None))
    leaks = client.get("/api/leaks").json()
    assert len(leaks) == 1
    assert leaks[0]["branch"] == "A" and leaks[0]["status"] == "fixed" and leaks[0]["ended_ts"]
    assert leaks[0]["max_leak_lpm"] > 0 and leaks[0]["base_lpm"] > 0

def test_fixed_goes_checking_then_fixed(tmp_path):   # storage level
    lid = open_leak(conn, "2026-11-27T06:12:00.000Z", "B", 1.5)
    assert mark_leak_fixed(conn, lid, "2026-11-27T09:00:00.000Z")["status"] == "checking"
    close_leak(conn, lid, "2026-11-27T09:00:05.000Z")
    assert list_leaks(conn)[0]["status"] == "fixed"

def test_pump_stop_keeps_episode_open(tmp_path):
    for f in [_frame("LEAK", "…06:12:00Z"), _frame("PUMP_OFF", "…06:20:00Z"), _frame("HEALTHY", "…07:00:00Z")]:
        track_leak(conn, f)
    row = list_leaks(conn)[0]
    assert row["status"] == "open" and row["ended_ts"] is None and row["pump_stopped"] == 1
    assert mark_leak_fixed(conn, row["id"], "…08:00:00Z")["status"] == "fixed"

def test_fixed_is_idempotent_and_unknown_is_404(tmp_path):
    # via API: first POST sets user_fixed_ts, second POST returns the same user_fixed_ts
    # POST /api/leaks/999/fixed -> 404

def test_open_episode_survives_backend_restart(tmp_path):
    # LEAK frame through app #1, then a new create_app on the same db, another LEAK frame
    # -> still exactly one row in /api/leaks
```

Use full ISO timestamps (`2026-11-27T06:12:00.000Z`) where the sketch writes `…`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_leaks.py -q` → FAIL (`ImportError` / 404 on `/api/leaks`).
- [ ] **Step 3: Implement** the storage functions, `backend/leaks.py`, the ingest hook (`if inserted and bench is not None:` block, right after `frame["id"] = …`), the two routes, and in `backend/main.py` `mimetypes.add_type("text/javascript", ".js")` and `mimetypes.add_type("application/manifest+json", ".webmanifest")` before the app is built (Windows can map `.js` to `text/plain`, which blocks ES modules).
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest tests -q` → all pass (the divider xfail stays xfail).
- [ ] **Step 5: Commit** `feat(backend): leak episodes (table, /api/leaks, fixed by the farmer)`.

### Task 2: App config and pure logic (severity, money, view)

**Files:**
- Modify: `dashboard/config.js` (add keys to `FARM_SCALE`; add `SEVERITY`, `DEMO_FARM_SCALE`)
- Create: `dashboard/app/package.json`, `dashboard/app/lib/severity.js`, `dashboard/app/lib/savings.js`, `dashboard/app/lib/status.js`
- Test: `dashboard/app/tests/logic.test.js`

**Interfaces:**
- Produces (`dashboard/config.js`): `FARM_SCALE` gains `farm_flow_m3_per_h: null, irrigation_hours_per_day: null, days_to_notice_without_hydropin: null` (existing keys kept); `export const SEVERITY = { medium_from: 0.05, large_from: 0.15 }`; `export const DEMO_FARM_SCALE = { farm_flow_m3_per_h: 200, irrigation_hours_per_day: 8, days_to_notice_without_hydropin: 10, price_dt_per_m3: 0.25 }`.
- Produces: `severity(leakLpm: number, baseLpm: number, thr = SEVERITY) -> "small" | "medium" | "large" | null`.
- Produces: `moneyReady(scale) -> boolean`; `benchLostM3(lostL, baseLpm, farmFlowM3PerH) -> number | null`; `leakMoney({ share, lostM3 }, scale) -> { leakM3PerH, wouldLoseM3, savedM3, savedDt } | null` (all four rounded to 2 decimals); `leakNumbers(leak, scale) -> { share: number | null, lostM3: number | null, status }` (`share = max_leak_lpm / base_lpm`; `lostM3 = leak.lost_m3` when present (demo), else `benchLostM3(leak.lost_l, leak.base_lpm, scale.farm_flow_m3_per_h)`); `seasonSavedDt(leaks: Array<{ share, lostM3, status }>, scale) -> number | null` (sum over `status === "fixed"`; `null` if not `moneyReady`).
- Produces (`dashboard/config.js`, also): `export const FARM_LOCATION = { lat: 36.80, lon: 10.18, placeholder: true }` (opens the maps app from "Take me there").
- Produces: `toView(stateResponse: {state, frame}, leaks: Array, sectors: string[]) -> View` where `View = { status: "ok" | "leak" | "offline", irrigating: boolean, sector: string | null, severity, share: number | null, whereTap: "L1" | "L2" | "L3" | null, leakId: number | null, leakStatus: "open" | "checking" | "fixed" | null, foundTs: string | null }`. Rules exactly as the spec's Data table; `whereTap` = the `frame.loc` key with value ≥ 0.6, else `null`; `leakId/leakStatus/foundTs` from the newest leak with status `open` or `checking`.

- [ ] **Step 1: Write the failing tests** (`node:test` + `node:assert/strict`):

```js
test("severity thresholds", () => {
  assert.equal(severity(0.04, 1), "small"); assert.equal(severity(0.05, 1), "medium");
  assert.equal(severity(0.149, 1), "medium"); assert.equal(severity(0.15, 1), "large");
  assert.equal(severity(0.3, 0), null); assert.equal(severity(0.3, null), null);
});
test("money: worked example of the spec", () => {
  const m = leakMoney({ share: 0.03, lostM3: 18 }, DEMO_FARM_SCALE);
  assert.equal(m.leakM3PerH, 6); assert.equal(m.wouldLoseM3, 480);
  assert.equal(m.savedM3, 462); assert.equal(m.savedDt, 115.5);
});
test("money is null when a parameter is missing", () => {
  assert.equal(leakMoney({ share: 0.03, lostM3: 18 }, { ...DEMO_FARM_SCALE, price_dt_per_m3: null }), null);
  assert.equal(seasonSavedDt([{ share: 0.03, lostM3: 18, status: "fixed" }], FARM_SCALE), null);
});
test("saved never negative", () => {
  assert.equal(leakMoney({ share: 0.001, lostM3: 999 }, DEMO_FARM_SCALE).savedM3, 0);
});
test("bench litres to farm m3", () => {   // 1.5 L/min bench = 0.09 m3/h ; farm 200 m3/h -> x 2222.2
  assert.equal(Math.round(benchLostM3(9, 1.5, 200)), 20);
});
test("leakNumbers: demo m3 first, bench scaling otherwise", () => {
  assert.deepEqual(leakNumbers({ max_leak_lpm: 8, base_lpm: 100, lost_m3: 3, status: "open" }, DEMO_FARM_SCALE),
                   { share: 0.08, lostM3: 3, status: "open" });
  assert.equal(Math.round(leakNumbers({ max_leak_lpm: 0.3, base_lpm: 1.5, lost_l: 9, status: "fixed" }, DEMO_FARM_SCALE).lostM3), 20);
});
test("offline when state OFFLINE or frame null", () => {
  assert.equal(toView({ state: "OFFLINE", frame: null }, [], ["A","B"]).status, "offline");
  assert.equal(toView({ state: "HEALTHY", frame: null }, [], ["A","B"]).status, "offline");
});
test("pump off = at rest, healthy/watch = fine and irrigating", () => { /* PUMP_OFF -> irrigating false; WATCH -> status ok */ });
test("leak view", () => {
  const v = toView({ state: "LEAK", frame: { state: "LEAK", branch: "B", flow_base_lpm: 1.5, leak_lpm: 0.3, loc: { L1: .1, L2: .7, L3: .2 } } },
                   [{ id: 4, status: "open", started_ts: "2026-11-27T06:12:00.000Z" }], ["A","B"]);
  assert.deepEqual([v.status, v.sector, v.severity, v.whereTap, v.leakId], ["leak", "B", "large", "L2", 4]);
});
```

- [ ] **Step 2: Run** `node --test dashboard/app/tests/` → FAIL (modules missing).
- [ ] **Step 3: Implement** the three modules and the config keys. Round with `Math.round(x * 100) / 100`.
- [ ] **Step 4: Run** `node --test dashboard/app/tests/` → PASS; `.venv/Scripts/python -m pytest tests/test_dashboard_data.py -q` → PASS (the dashboard still imports `FARM_SCALE`).
- [ ] **Step 5: Commit** `feat(app): severity, money-saved formula and view model (tested)`.

### Task 3: Strings and language

**Files:**
- Create: `dashboard/app/lib/strings.js`, `dashboard/app/lib/i18n.js`
- Test: `dashboard/app/tests/i18n.test.js`

**Interfaces:**
- Produces: `STRINGS = { fr: {...}, ar: {...}, en: {...} }`, flat keys. Required keys (copy in the spec's tone; `{x}` are placeholders): `tab.home tab.map tab.savings tab.help hello.morning hello.afternoon hello.evening badge.demo badge.live(="Test bench · 2 sectors") bench.name(="HydroPin test bench") money.if_farm({area},{dt}) money.if_farm_no_area({dt}) status.ok.title status.ok.sub status.leak.title({sector}) status.leak.sub({time}) status.offline.title status.offline.sub farm.irrigating({sectors}) farm.rest saved.season alerts.title alerts.see_all alerts.leak_fixed({sector},{date}) alerts.leak_open({sector}) btn.show_where btn.take_me btn.call_tech btn.fixed_it btn.back_home btn.call_us btn.whatsapp_us btn.share_report btn.add_photo where.title where.sector({sector}) where.near_tap({tap}) details.title details.severity sev.small sev.medium sev.large sev.advice.small sev.advice.medium sev.advice.large details.why details.why_text({sector}) details.lost details.where details.how_we_count money.how({perHour},{days},{hours},{saved},{price},{dt}) money.not_set money.estimate checking.title checking.sub fixed.title fixed.sub fixed.saved fixed.not_confirmed map.title map.sensors_ok({n}) map.sensors_pipes savings.title savings.season({year}) savings.count({n}) savings.details help.title help.next_visit help.plan profile.title profile.language profile.source currency`.
- Produces: `detectLang(navLang: string | undefined, stored: string | null) -> "fr" | "ar" | "en"` (stored wins if valid; else `navLang` prefix; else `"fr"`); `t(lang, key, vars = {}) -> string` (falls back to `fr`, then to the key; replaces `{name}`); `isRtl(lang) -> boolean`; `locale(lang) -> "fr-TN" | "ar-TN" | "en"`; `fmt(lang, n, digits = 0) -> string` via `Intl.NumberFormat(locale(lang), { maximumFractionDigits: digits, numberingSystem: "latn" })`; `loadLang(storage = globalThis.localStorage) -> string | null` and `saveLang(lang, storage = globalThis.localStorage) -> void`, both wrapped in try/catch.

- [ ] **Step 1: Write the failing tests:**

```js
test("same keys and placeholders in fr, ar, en", () => {
  const keys = (o) => Object.keys(o).sort();
  assert.deepEqual(keys(STRINGS.ar), keys(STRINGS.fr)); assert.deepEqual(keys(STRINGS.en), keys(STRINGS.fr));
  const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
  for (const k of keys(STRINGS.fr)) for (const l of ["ar", "en"]) assert.equal(ph(STRINGS[l][k]), ph(STRINGS.fr[k]), `${l}:${k}`);
  for (const l of ["fr","ar","en"]) for (const k of keys(STRINGS[l])) assert.ok(STRINGS[l][k].trim(), `${l}:${k} empty`);
});
test("t interpolates and falls back", () => {
  assert.equal(t("en", "status.leak.title", { sector: "B" }), "Leak in Sector B");
  assert.equal(t("en", "no.such.key"), "no.such.key");
});
test("detectLang", () => {
  assert.equal(detectLang("ar-TN", null), "ar"); assert.equal(detectLang("en-US", null), "en");
  assert.equal(detectLang("de-DE", null), "fr"); assert.equal(detectLang("en-US", "ar"), "ar");
  assert.equal(detectLang(undefined, "xx"), "fr");
});
test("isRtl", () => { assert.equal(isRtl("ar"), true); assert.equal(isRtl("fr"), false); });
test("storage that throws is survived", () => {
  const bad = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(loadLang(bad), null); assert.doesNotThrow(() => saveLang("ar", bad));
});
test("Arabic numbers use Latin digits", () => { assert.equal(fmt("ar", 86), "86"); });
```

- [ ] **Step 2: Run** `node --test dashboard/app/tests/` → FAIL.
- [ ] **Step 3: Implement.** English copy follows the mockups ("Everything is fine", "Leak in Sector {sector}", "The leak is probably here", "Fixed. Thank you!"…); French and Modern Standard Arabic translate it; mark the Arabic block with a comment `// proofread by Israa`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(app): fr / ar / en strings and language helpers`.

### Task 4: Farm drawings

**Files:**
- Create: `dashboard/app/farm.js`
- Test: `dashboard/app/tests/farm.test.js`

**Interfaces:**
- Produces: `farmSvg({ sectors: string[], irrigating: string[], leakSector: string | null, sensors: boolean }) -> string` — the isometric farm of `farmer-app-hifi.html` (function `farm()` there): one `<polygon data-sector="X">` per sector (4-sector layout for `["A","B","C","D"]`; for `["A","B"]` only the two top/right quadrants are drawn as a 2-sector field), pipes, pump, `class="flow"` paths only when `irrigating` is non-empty, a pin `data-pin` in `leakSector`, green sensor dots when `sensors`.
- Produces: `whereSvg({ tap: string | null }) -> string` — the top-down map of the mockup (`topmap()`), with the tap label when given.

- [ ] **Step 1: Write the failing tests:**

```js
test("sectors drawn", () => { assert.equal((farmSvg({ sectors: ["A","B"], irrigating: [], leakSector: null, sensors: false }).match(/data-sector=/g) || []).length, 2); });
test("water flows only when irrigating", () => {
  assert.ok(farmSvg({ sectors: ["A","B","C","D"], irrigating: ["A"], leakSector: null, sensors: false }).includes('class="flow"'));
  assert.ok(!farmSvg({ sectors: ["A","B","C","D"], irrigating: [], leakSector: null, sensors: false }).includes('class="flow"'));
});
test("pin only on a leak", () => {
  assert.ok(farmSvg({ sectors: ["A","B"], irrigating: ["A","B"], leakSector: "B", sensors: false }).includes("data-pin"));
  assert.ok(!farmSvg({ sectors: ["A","B"], irrigating: ["A","B"], leakSector: null, sensors: false }).includes("data-pin"));
});
```

- [ ] **Step 2–4:** run → FAIL, implement (port from the mockup, CSS animation class `flow` defined in Task 6's CSS), run → PASS.
- [ ] **Step 5: Commit** `feat(app): farm and leak-map drawings`.

### Task 5: Data sources (live and demo)

**Files:**
- Create: `dashboard/app/lib/source.js`, `dashboard/app/demo.js`
- Test: `dashboard/app/tests/source.test.js`

**Interfaces:**
- Consumes: Task 1 API, Task 2 `toView` input shapes.
- Produces: `Snapshot = { stateResponse: {state, frame}, leaks: Array, sectors: string[], kind: "live" | "demo", scale: object }` (`scale` = `FARM_SCALE` for live, `DEMO_FARM_SCALE` for demo). Demo leaks carry `lost_m3` directly; live leaks use `benchLostM3`.
- Produces: `detectSource(base = "..", fetchImpl = fetch) -> Promise<"live" | "demo">` (live iff `GET {base}/health` is 200 with `bench_detector: true`, within 2 s).
- Produces: `liveSource(base = "..", { fetchImpl = fetch, intervalMs = 2000 } = {}) -> Source` polling `{base}/api/state` and `{base}/api/leaks?limit=20`; on a fetch error it emits `stateResponse = { state: "OFFLINE", frame: null }` and keeps polling.
- Produces: `demoSource({ now = () => Date.now(), start = "normal" } = {}) -> Source` with `start ∈ "normal" | "leak" | "fixed"`. Script: t < 8 s HEALTHY, irrigating A and B, sectors A–D; t ≥ 8 s LEAK in B with `flow_base_lpm: 100, leak_lpm: 8` (share 0.08, medium), `loc {L2: 0.7}`, leak `{id: 1, status: "open", started_ts: "<today>T06:12:00", lost_m3: 3}`; after `markFixed(1)`: `checking` for 4 s, then `fixed` with `lost_m3: 4.6`, state HEALTHY. Two past fixed leaks in the leaks list for history ("Sector A, 25 Nov", "Sector C, 8 Nov").
- `Source = { kind, start(onSnapshot: (s: Snapshot) => void): void, stop(): void, markFixed(id: number): Promise<void> }`; `demoSource` also exposes `tick(): void` (recomputes and emits the snapshot from `now()`; the browser calls it every 500 ms via `setInterval` started in `start`).

- [ ] **Step 1: Write the failing tests:**

```js
test("demo timeline", () => {
  let t = 0; const s = demoSource({ now: () => t }); let snap; s.start((x) => (snap = x));
  s.tick();                    // demoSource exposes tick() for tests; the browser drives it with setInterval
  assert.equal(snap.stateResponse.state, "HEALTHY");
  t = 9000; s.tick(); assert.equal(snap.stateResponse.state, "LEAK");
  s.markFixed(1); s.tick(); assert.equal(snap.leaks.find((l) => l.id === 1).status, "checking");
  t = 14000; s.tick(); assert.equal(snap.leaks.find((l) => l.id === 1).status, "fixed");
  assert.equal(snap.kind, "demo");
});
test("demo can start on the leak", () => { /* start: "leak" -> first tick LEAK */ });
test("live source turns a failed fetch into OFFLINE", async () => {
  const s = liveSource("..", { fetchImpl: async () => { throw new Error("down"); }, intervalMs: 10 });
  const snap = await new Promise((res) => s.start(res)); s.stop();
  assert.equal(snap.stateResponse.state, "OFFLINE");
});
test("detectSource", async () => {
  const ok = async () => ({ ok: true, json: async () => ({ ok: true, bench_detector: true }) });
  assert.equal(await detectSource("..", ok), "live");
  assert.equal(await detectSource("..", async () => { throw new Error("x"); }), "demo");
});
```

- [ ] **Step 2–4:** run → FAIL, implement (`liveSource` emits after each poll; `demoSource.tick()` computes the snapshot from `now()`), run → PASS.
- [ ] **Step 5: Commit** `feat(app): live (backend) and demo data sources`.

### Task 6: App shell and screens

**Files:**
- Create: `dashboard/app/index.html`, `dashboard/app/app.css`, `dashboard/app/main.js`

**Interfaces:**
- Consumes: everything above.
- Produces (routes, hash based): `#/home` (default), `#/where`, `#/fixed`, `#/alerts`, `#/map`, `#/savings`, `#/help`; sheets `details` and `profile` open over the current route. URL params read once at start: `?demo=leak|fixed`, `?lang=fr|ar|en`, `?source=demo` (forces demo on the laptop, for filming).

- [ ] **Step 1: Build `app.css`** from the `<style>` of `farmer-app-hifi.html`. Two changes:
  - use logical properties (`margin-inline-start`, `padding-inline`, `inset-inline-end`), with `[dir="rtl"] .ic-dir { transform: scaleX(-1) }` on the back and "take me" icons;
  - keep `@media (prefers-reduced-motion: reduce)` off for `.flow` and `.pulse`.
- [ ] **Step 2: Build `index.html`**:
  - `<html lang dir>` set by JS;
  - viewport meta;
  - `theme-color #15803D`;
  - manifest link and apple-touch-icon (files come in Task 7);
  - Inter from Google Fonts;
  - the SVG icon `<symbol>` sprite from the mockup;
  - `<main id="screen">`, `<nav id="tabs">`, `<div id="sheet">`;
  - `<script type="module" src="main.js">`.
- [ ] **Step 3: Build `main.js`**:
  1. Boot:
     - language = `detectLang(navigator.language, loadLang())`, overridden by `?lang`;
     - source = `?source=demo` or `?demo=` → demo, else `detectSource()`;
     - start the source, keep the last `Snapshot`;
     - re-render on every snapshot and every `hashchange`.
  2. Each screen is a function `(snap, view, lang) -> string`, built with `t()` and `fmt()`, following the spec's Screens list:
     - **Home:** status card → farm (`farmSvg`) → saved → 3 past alerts.
     - **Where:** `whereSvg`, `where.title`, sector or `where.near_tap`, "Take me there", "Call a technician", Details, "I fixed it".
     - **Details sheet:**
       - severity pill + advice (hidden when `severity` is null);
       - why;
       - lost (m³ + DT + "estimate", or `money.not_set`);
       - where exactly;
       - "How we count" (`money.how`).
     - **Fixed:** checking while `leakStatus === "checking"`, then fixed + saved DT. `fixed.not_confirmed` if the leak had `pump_stopped`.
     - **Map, Savings, Help, Profile sheet:** language buttons call `saveLang` + re-render; source shown with its badge.
  3. Tap handlers:
     - "I fixed it" → `source.markFixed(view.leakId)` then `#/fixed`;
     - "Take me there" → `https://www.google.com/maps/search/?api=1&query={FARM_LOCATION.lat},{FARM_LOCATION.lon}` in a new tab (the phone opens its maps app);
     - "Call" → `tel:+21600000000` (placeholder, open item);
     - "WhatsApp us" → `https://wa.me/21600000000`;
     - "Share the report" → `navigator.share` if present, else copy the text.
  4. Live mode (`snap.kind === "live"`):
     - Home's title is `bench.name` instead of the "Mr Moez" greeting, and the badge `badge.live` is always visible.
     - Every money line uses `money.if_farm` (or `money.if_farm_no_area` when `FARM_SCALE.area_ha` is null), or "—" when `moneyReady` is false.
     - Demo mode keeps "Mr Moez", `badge.demo` and the plain money lines.
  5. Escape every interpolated value with an `esc()` helper.
- [ ] **Step 4: Verify in a browser.** Serve with the backend (`/app/`, port 8001 if running) or `python -m http.server` in `dashboard/`. Take Edge headless screenshots, 390×844, of:
  - `app/?source=demo&lang=en#/home` (normal day),
  - `?demo=leak&lang=en#/home`,
  - `?demo=leak&lang=en#/where`,
  - `?demo=fixed&lang=fr#/fixed`,
  - `?demo=leak&lang=ar#/home` (RTL),
  - `#/savings`, `#/map`, `#/help`.

  Use:
  `"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --hide-scrollbars --window-size=390,844 --virtual-time-budget=4000 --screenshot=<png> "<url>"`.

  Compare each screenshot with the mockups:
  - one primary button;
  - numbers only behind Details, except DT;
  - Arabic mirrored;
  - the "Demo farm" badge visible.
- [ ] **Step 5: Run** `node --test dashboard/app/tests/` and pytest → PASS. **Commit** `feat(app): farmer app screens (home, where, details, fixed, map, savings, help)`.

### Task 7: Installable (PWA)

**Files:**
- Create: `dashboard/app/manifest.webmanifest`, `dashboard/app/sw.js`, `dashboard/app/icons/icon.svg`, `dashboard/app/icons/icon-192.png`, `dashboard/app/icons/icon-512.png`, `dashboard/app/icons/apple-touch-icon.png` (180×180)
- Modify: `dashboard/app/main.js` (register the service worker)
- Test: `tests/test_farmer_app_files.py`

**Interfaces:**
- Produces: manifest `{"name": "HydroPin", "short_name": "HydroPin", "start_url": "./", "scope": "./", "display": "standalone", "background_color": "#F0FDF4", "theme_color": "#15803D", "icons": [192, 512 PNG, 512 with "purpose": "maskable"]}`; `sw.js` cache name `hydropin-app-v1`, cache-first for the app shell (index.html, app.css, main.js, farm.js, demo.js, lib/*.js, ../config.js, icons, manifest), network-only for anything under `/api`, `/health`, `/ws`.

- [ ] **Step 1: Write the failing test** `tests/test_farmer_app_files.py`:
  - with `TestClient(create_app(..., static_dir=default))`:
    - `GET /app/` is 200 and contains `manifest.webmanifest`;
    - `GET /app/manifest.webmanifest` parses as JSON with `display == "standalone"` and 2+ icons whose files return 200;
    - `GET /app/main.js` has a `content-type` starting with `text/javascript`;
    - `GET /app/sw.js` is 200.
  - Also assert `json.loads` of the manifest from disk has `start_url == "./"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Icon: green rounded square, white droplet, a small red pin. Render the PNGs from `icon.svg` with Edge headless (`--window-size=512,512 --screenshot`, then 192 and 180 the same way). Register the worker in `main.js`: `if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js")`.
- [ ] **Step 4: Run** pytest → PASS. Manual check: Edge on the laptop → `http://localhost:8001/app/` → the address bar shows "App available / Install".
- [ ] **Step 5: Commit** `feat(app): installable (manifest, service worker, icons)`.

### Task 8: Wire-up, demo for filming, docs

**Files:**
- Modify: `dashboard/index.html` (header link "Farmer app ↗" → `app/`)
- Modify: `simulator/bench_rev1.py` (CLI flag `--leak-stop SECONDS` → `build(..., leak_stop_s=...)`)
- Modify: `README.md` (section "Farmer app": URLs, `?demo=`, `?lang=`, where the money formula and its parameters live)
- Test: `tests/test_bench_rev1.py` (add one test)

- [ ] **Step 1: Write the failing test:** `main(["--scenario", "leak_L2", "--duration", "200", "--leak-stop", "150", "--out", str(tmp_path/"r.json")])`. The messages with `ts_device_ms >= 150000` have label `none`; those between 80 000 and 150 000 have `leak_L2`.
- [ ] **Step 2–4:** run → FAIL, add the flag, run → PASS.
- [ ] **Step 5: End-to-end check (live):**
  - a **second** backend on port **8765** with a scratch database (`HYDROPIN_DB=data/app_e2e.db`, no `HYDROPIN_MQTT`, deleted afterwards). Never post simulated data to the campaign backend on 8001 / `data/hydropin.db`: teammates are recording real runs there;
  - `python -m simulator.bench_rev1 --scenario leak_L2 --duration 220 --leak-stop 170 --realtime --speed 1 --post http://localhost:8765`;
  - open `http://localhost:8765/app/?lang=en`.

  Expected:
  - Home titled "HydroPin test bench" with the badge "Test bench · 2 sectors";
  - Home "Leak in Sector B" after ~1.5 min;
  - Where shows Sector B, and Details shows severity Large (bench share ~0.2) with money "—" (farm figures not set);
  - tap "I fixed it" → Checking;
  - after 170 s → Fixed;
  - `GET /api/leaks` → one leak, status `fixed`.
- [ ] **Step 6: Run** all tests (`node --test dashboard/app/tests/`, pytest). **Commit** `feat(app): link from the dashboard, --leak-stop for filming, README`.

---

## Self-review notes

- **Spec coverage:**
  - Screens 1–7 → Task 6;
  - live/demo → Tasks 1, 5;
  - severity → Task 2;
  - money → Tasks 2 and 6 ("How we count");
  - language/RTL → Tasks 3 and 6;
  - PWA → Task 7;
  - honesty badges → Tasks 5 and 6;
  - open items stay with Israa (FARM_SCALE values, Arabic proofreading, phone number).
- **Names used across tasks:**
  - `toView`, `severity`, `leakMoney`, `leakNumbers`, `seasonSavedDt`, `benchLostM3`, `moneyReady`, `FARM_LOCATION`;
  - `farmSvg`, `whereSvg`;
  - `detectSource`, `liveSource`, `demoSource`;
  - `t`, `fmt`, `detectLang`, `isRtl`, `locale`, `loadLang`, `saveLang`;
  - `track_leak` and the storage functions of Task 1.
