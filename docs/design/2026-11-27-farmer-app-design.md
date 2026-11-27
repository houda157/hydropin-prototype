# HydroPin farmer app — design

Date: 27 Nov 2026 · Status: implemented (`dashboard/app/`)

## Why

The jury sees the prototype through a link and a ~3 min video. The dashboard (`dashboard/index.html`)
is a lab console for the team and the jury. The farmer app shows what HydroPin is as a **product**:
what a farmer sees when a buried pipe leaks, from the alert to the repair and the money saved. It
must look like a real app, run from a link on any phone, and use the real bench data when the laptop
backend is running.

## Goals

- An installable mobile web app (PWA): opens from a link, "Add to home screen" gives a full-screen app with an icon.
- **Live mode** on the laptop: reads the backend (`/api/state`) for the **test bench, presented as what it is: a farm network in miniature, "HydroPin test bench · 2 sectors"** (branch A = Sector A, branch B = Sector B). Leak alerts, irrigating / at rest, repair confirmed by the sensors. In the video: a tap opened on the real bench → "Leak in Sector B" on the phone.
- **Demo mode** on GitHub Pages (no backend): a scripted farm day (normal → leak → repair), always labelled "Demo farm".
- Language chosen by the user: Français, العربية (right to left), English.
- The leak story of the approved mockups (kept outside the repository).

## Non-goals

- WhatsApp sending (separate plan: OpenWA in the backend). The app only shows the alert text style.
- Accounts, login, several farms, payments. "Mr Moez" is fixed demo data.
- Native app stores (no Flutter / React Native).
- Drone (dropped: too expensive).

## Anti-goals (failure even if it works)

- Showing simulated data without saying so (team honesty rule, CONTEXT §7).
- A farmer screen full of numbers. One sentence and one main button per screen; numbers only behind **Details**, except money.
- Inventing money figures: if the farm figures are not filled in, money shows "—", never a made-up value.

## Approaches considered

| | A. PWA in `dashboard/app/`, no build step (**chosen**) | B. React + Vite PWA | C. Flutter / React Native |
|---|---|---|---|
| Jury access | a link; installable | a link | APK, no iPhone |
| Fit | same no-build approach as the dashboard, same Pages workflow, same backend origin | build step + workflow change | separate project |
| Time | 4–5 h | 6–8 h | 10 h+ |

Chosen: A.

**How live mode presents the bench** (the app is about farms, the prototype is a bench):

| | 1. The bench as a mini-farm (**chosen**) | 2. Demo only, no live mode | 3. Simulated farm, one sector driven by the bench |
|---|---|---|---|
| Honest | yes: labelled "test bench · 2 sectors" | yes | hard: real and simulated on one screen |
| Shows the real chain | yes: tap opened → phone alert | no: a mockup with nothing behind | yes, but confusing |
| Cost | as planned | ~1 h less | more, and hard to explain in 3 min |

Chosen: 1. The data path is the farm's (sensors → network → backend → app); only the size differs.

## What the user decided

- Installable mobile app (A), language configurable.
- Screens and order from the hi-fi mockups; past alerts as a simple list (option A).
- Normal-day Home shows the farm, with water flowing while irrigating and still water at rest.
- **Details shows how severe the leak is, not how sure we are.**
- Money saved must be explainable ("how did we get 8 DT?"): see the formula below, shown in plain words behind Details.

## Screens

Bottom tabs: Home · Map · Savings · Help (icon + label). Profile (avatar, top right) opens a sheet: language, data source (live / demo), farm name.

1. **Home**
   - Status card first: "Everything is fine" (green), "Leak in Sector B" (red, + "Show me where"), or "No news from your sensors" (grey, + "Call us").
   - The farm view: sectors, pump, pipes; animated water when irrigating; leak sector in red with a pin.
   - "Saved this season: N DT".
   - Past alerts: at most 3 lines (icon + short text + date), "See all".
2. **Where is it?**
   - Map with the pin and "you".
   - "The leak is probably here" + one line (sector).
   - Main button "Take me there"; second button "Call a technician".
   - Closed **Details**, plus "I fixed it".
3. **Details** (bottom sheet)
   - Severity: Small / Medium / Large + one line of advice.
   - Why, in plain words.
   - Lost so far: m³ and DT, marked "estimate".
   - Where exactly.
4. **Checking / Fixed**
   - After "I fixed it": "Checking… the sensors are confirming".
   - Once the bench is back to HEALTHY: "Fixed. Thank you!" + "You saved about N DT" + Details → "How we count".
5. **Map**: farm with sensor dots, "All N sensors working" / "1 sensor needs attention", closed "Sensors and pipes".
6. **Savings**: season total in DT, number of leaks found and fixed, bar chart by month, closed Details (m³, repair times), "Share the season report" (uses the browser's share sheet; falls back to copying the text).
7. **Help**: "Call HydroPin" (tel: link), "WhatsApp us" (wa.me link), next technician visit (demo text), closed "My plan · Monitor".

Visual system: earth green `#15803D`, red `#DC2626` only for a leak, warning `#A16207`, water `#1D5FA8`, background `#F0FDF4`, card `#FFFFFF`, text `#14532D`, muted `#475569`, border `#D7EFDF`. Inter (system-ui fallback). Line icons (2 px) with text labels, no emoji. Radius 16–20 px, touch targets ≥ 44 px, mobile first at 375 px.

## Data

### Live (served by the laptop backend at `/app/`)

The app polls `GET /api/state` every 2 s and lists leaks with `GET /api/leaks`.

| Backend | App |
|---|---|
| `frame.state` `PUMP_OFF` | at rest |
| `frame.state` `SETTLING`, `LEARNING`, `HEALTHY`, `WATCH` | irrigating, status "fine" (WATCH never alarms the farmer) |
| `frame.state` `LEAK` | leak; branch A/B → Sector A/B |
| `frame.state` `OFFLINE`, or no frame | "No news from your sensors" |

- Live mode draws a 2-sector farm: the bench's branches A and B.
  - Its name is "HydroPin test bench" (in place of "Mr Moez").
  - Its badge says "Test bench · 2 sectors".
- "Where exactly" comes from `frame.loc`. If one tap has ≥ 0.6, the text says "near tap L2" (or L1, L3); otherwise it names the sector only.

**New in the backend: leak episodes.** A table `leaks` and two endpoints:
- `GET /api/leaks?limit=20`, newest first:
  `{id, started_ts, ended_ts|null, branch, base_lpm, max_leak_lpm, lost_l, pump_stopped, user_fixed_ts|null, status}`.
  `status` is `open`, `checking` (user said fixed, sensors not yet back to normal) or `fixed`.
- `POST /api/leaks/{id}/fixed` records the farmer's "I fixed it". It is idempotent; an unknown id returns 404.

How an episode moves:
- It opens on the frame where the state becomes LEAK.
- While LEAK, it keeps the largest `leak_lpm`, the latest `lost_l` and `branch`.
- It closes (`ended_ts`) on the first HEALTHY frame after it, **unless the pump stopped (PUMP_OFF) during the episode**. After a pump restart the detector re-learns its baseline with the leak inside it, so HEALTHY no longer proves a repair. Such an episode stays open until the farmer taps "I fixed it"; it then shows "fixed (not confirmed by the sensors)".

### Demo (GitHub Pages, or no backend answers `/health`)

A scripted timeline in the app, labelled "Demo farm" on Home:
- a 4-sector farm, irrigating sectors A and B;
- a medium leak appears in Sector B 8 s after start;
- "I fixed it" goes to checking, then fixed 4 s later.

URL parameters for filming: `?demo=leak` starts on the leak, `?demo=fixed` on the fixed screen, `?lang=ar|fr|en` sets the language.

## Severity (replaces "how sure")

Severity comes from the share of the pumped water lost: `share = leak_lpm / base_lpm`.

| share | severity | advice |
|---|---|---|
| < 0.05 | Small | "Fix it this week." |
| 0.05 – < 0.15 | Medium | "Fix it today." |
| ≥ 0.15 | Large | "Fix it now: a lot of water is lost." |

- `base_lpm` ≤ 0 or missing → severity unknown (the row is hidden).
- The thresholds are farm-oriented and live in `dashboard/config.js` (`SEVERITY`).
- On the bench every staged leak is 10–33 % of a small flow, so bench leaks show as Medium or Large. That is true at farm scale too.

## Money saved (how "8 DT" is computed)

Parameters (market lead, in `dashboard/config.js` → `FARM_SCALE`, each with a source):

| parameter | meaning | demo placeholder until filled |
|---|---|---|
| `farm_flow_m3_per_h` | pump flow of the reference farm while irrigating | 200 |
| `irrigation_hours_per_day` | hours of irrigation per day | 8 |
| `days_to_notice_without_hydropin` | how long a buried leak runs before anyone sees it | 10 |
| `price_dt_per_m3` | water + pumping energy, DT per m³ | 0.25 |

For one leak:
- `farm_leak_m3_per_h = share × farm_flow_m3_per_h`
- `lost_m3` = water actually lost, scaled the same way from the bench: `lost_l / 1000 × farm_flow_m3_per_h / (base_lpm × 0.06)`. In demo mode it comes straight from the demo script.
- `would_lose_m3 = farm_leak_m3_per_h × irrigation_hours_per_day × days_to_notice_without_hydropin`
- `saved_m3 = max(0, would_lose_m3 − lost_m3)`
- `saved_dt = saved_m3 × price_dt_per_m3`

The season total is the sum over the season's leaks that are `fixed`.

Example with the placeholders:
- a 3 % leak loses 6 m³/h;
- fixed after 3 h of irrigation, so 18 m³ lost;
- unnoticed it would lose 6 × 8 × 10 = 480 m³;
- saved = 462 m³ × 0.25 = **115.5 DT**.

Behind Details → "How we count", the app shows this in one plain sentence with the numbers, marked "estimate".

**If any parameter is null:** money shows "—", and Details says "farm figures not set yet". On Pages the demo uses the placeholders above, labelled "estimate".

**In live mode (the bench)**, the litres lost on the bench are tiny, so money is always worded as a projection:
- "If this leak happened on a {area} ha farm: about {dt} DT", with `area` = `FARM_SCALE.area_ha`;
- "If this leak happened on a farm: about {dt} DT" when `area_ha` is null.

It uses the same formula, with the bench's share of water lost. If the other figures are null, it shows "—".

## Language

- `fr`, `ar`, `en`; default from the browser language, otherwise `fr`. Remembered in `localStorage` when allowed.
- Arabic sets `dir="rtl"`: layout mirrors (CSS logical properties), and direction icons (back, go) flip.
- Numbers use the `fr-TN`, `ar-TN` (Latin digits) or `en` locale.
- The Arabic strings are Modern Standard Arabic and still need a native proofread.

## Constraints

- No build step, no npm dependencies, vanilla ES modules.
- Served from `dashboard/app/` by the backend (same origin as `/api`) and by the existing Pages workflow (which copies `dashboard/`).
- Node 22 (`node --test`) for the app's logic tests; pytest for the backend.
- No AI co-author lines in commits.

## Left to the builder

- Exact copy within the tone above.
- Animation timings.
- The "See all" alerts list layout.
- The empty state of Savings.
- Service-worker cache list details.

## Open items

- Fill `FARM_SCALE`, with a source for each value.
- Proofread the Arabic strings.
- Confirm the HydroPin phone number for "Call HydroPin".
