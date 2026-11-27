# Dashboard re-skin to the farmer app's look – design

Branch: `dashboard_ui_improvement` · Date: 2026-11-27 · Size: small change (short design)

## Intent
Make every part of HydroPin feel like one product. The prototype dashboard (`dashboard/`) still uses
the orange "studio" look; the farmer's mobile app mockups set the project's visual language. Re-skin
the dashboard's 5 tabs (Bench, Scoreboard, Farm, M3, What's real) to that language.

## Goals
- The app's palette, type and shapes on every tab, light and dark.
- Colour carries meaning as in the app: green = all is well, red = leak only, blue = water/pipes.
- A status card at the top of the Bench tab in the app's style ("Everything is fine" / "Leak in branch B").
- Long technical notes folded behind "Details", like the app.

## Non-goals
- No backend change (`backend/`, API, WebSocket, data files, `contract/`): UI only.
- No new data, panels, metrics or features; no change to what any number means.
- Kmar's farm explorer and Houda's twin viewer keep their look for now (follow-up branch, option C).

## Anti-goals (a failure even if it works)
- Generic "AI" styling: gradients, glows, drop-shadow stacks, emoji, decorative icons with no label.
- Red used for anything but a leak (today: panel markers, primary buttons, "sim" tags).
- Any element id, form field or button that `app.js` uses renamed or removed (it would break live mode).

## Approaches
- A. Colours and fonts only: quick, but still reads as the old dashboard in green.
- **B. Full visual re-skin, same screens and data (chosen).** A + shapes, sentence-case
  headings, labelled line icons on tabs, Bench status card, Details toggles.
- C. B + farm explorer + twin viewer: full harmony, but two more pages owned by others; later branch.

## Decisions
**Tokens** (sampled from the mockup image; Tailwind green/red scale):

| Token | Light | Use |
|---|---|---|
| page bg | `#e9efea` | behind the cards |
| surface | `#f0fdf4` | panels (the app's screen colour) |
| card | `#ffffff` | inner cards, inputs, buttons |
| ok-soft | `#d9f0e1` | "all is well" status card |
| primary / ok | `#15803d` | primary buttons, active tab, good values |
| ink | `#0c1814` | text |
| muted | `#5b6b63` | secondary text (my call: darker than the mockup's grey for contrast ≥ 4.5:1) |
| line | `#d0dad3` | borders |
| leak | `#dc2626` | LEAK state, leak bars, leak halo only |
| leak-soft | `#eee9e1` | leak status card |
| water | `#2563eb` | pipes in the bench drawing, PT1/F0 series |
| watch | `#b45309` | WATCH state (my call: the app has no "watch" state; amber, never red) |
| sim | `#475569` on `#e2e8f0` | "Simulation" chips and banners (my call: neutral slate, not red) |

Dark mode stays (my call): the same roles on a deep green base (`#0f1a15` bg, `#15231c` surface).

**Type:** Inter only (drop Archivo). Headings sentence case, 600. Small labels sentence case, no
letter-spacing caps. Numbers tabular.

**Shapes:** cards 14 px radius, buttons and inputs 10 px, pills fully rounded; 1 px borders; no shadows.

**Tabs:** each tab gets a 1.5 px line icon above or beside its label (house = Bench, bars = Scoreboard,
map = Farm, wave = M3, info = What's real), active tab in primary green. "sim" marker → slate chip.

**Bench status card** (new, top of the Bench tab), from the detector state already in each frame:

| State | Card | Text |
|---|---|---|
| HEALTHY | green | "Everything is fine" · "No leak on the bench" |
| WATCH | amber | "Watching a possible leak" · "Branch X, P(leak) NN %" |
| LEAK | red | "Leak in branch X" · "About N L/min lost" |
| PUMP_OFF / SETTLING / LEARNING | neutral | "Pump off" / "Settling" / "Learning normal" |
| OFFLINE or no data | neutral | "Waiting for bench data" · "Start the ESP32 or the simulator" |

**Details:** the explanatory `.note` paragraphs (Methods, Where, Scoreboard, Farm, M3) move into
`<details><summary>Details</summary>` blocks, closed by default. Live values stay visible.

**Header:** keep the cells (Source, State, P(leak), Branch), restyled; the orange tag becomes a
green wordmark.

## Files
- `dashboard/style.css`: rewritten tokens and components.
- `dashboard/index.html`: tab icons, status card markup, `<details>` wrappers, font link. All ids kept.
- `dashboard/app.js`: status-card render from the existing frame; any colour that should follow the
  new roles (state colours, P(leak) bar, schematic sensor strokes). No logic or data change.

## Left to the builder
Exact spacing, icon paths (simple 24×24 strokes), chart line widths, responsive breakpoints.

## Done when
- All 5 tabs render in the new look, light and dark, with no console errors.
- Live mode still works end to end with `simulator.bench_rev1 --scenario leak_L2` (state, charts,
  status card go HEALTHY → LEAK → HEALTHY).
- `python -m pytest tests -q` still passes; `git diff --stat` shows no file outside `dashboard/` and `docs/`.
