"""Plan a sunrise inspection flight over the pipes most likely to leak (simulation).

    python -m farm.drone.dispatch            # reads dashboard/farm/results.json + farm/model/layout.json

Blueprint rule (drone is optional, rule-based):
  1. take the pipes holding >= 90 % of the fused leak probability (most likely first);
  2. waypoints every 10 m along each of them, 30 m above ground (RGB + thermal camera);
  3. route from the base (the pump station, next to the farm gate) by nearest neighbour, each
     pipe flown end to end from its nearer end, then back to base;
  4. flight time at 8 m/s plus a 10 s hover per pipe for photos;
  5. take-off at sunrise, when the thermal contrast between wet and dry soil is best.

Output: dashboard/farm/drone.json, one route per showcase scenario and sensor-set size.
Labelled simulation; real flights through the vendor SDK / MAVLink are a next step.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "dashboard" / "farm" / "results.json"
LAYOUT = ROOT / "farm" / "model" / "layout.json"
DASH = ROOT / "dashboard" / "farm" / "drone.json"

PROB_COVER = 0.90
SPACING_M = 10.0
ALT_M = 30.0
SPEED_MPS = 8.0
HOVER_S_PER_PIPE = 10.0
BATTERY_S = 20 * 60               # typical small agricultural drone, assumption
BASE_NODE = "PS"
# Site for the sunrise time: Cap Bon, Tunisia (assumption; the farm itself is virtual)
LAT, LON, UTC_OFFSET_H = 36.8, 10.7, 1
FLIGHT_DATE = date(2026, 11, 27)


def sunrise_local(d: date = FLIGHT_DATE, lat: float = LAT, lon: float = LON, tz: float = UTC_OFFSET_H) -> str:
    """NOAA-style approximation (about +/- 2 min), returns HH:MM local time."""
    n = d.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    la = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
                                - math.tan(la) * math.tan(decl)))
    minutes = 720 - 4 * (lon + ha) - eqtime + tz * 60
    return f"{int(minutes // 60):02d}:{int(round(minutes % 60)):02d}"


def pipe_geometry(layout: dict) -> tuple[dict, dict]:
    nodes = {n["id"]: (float(n["x"]), float(n["y"])) for n in layout["nodes"]}
    pipes = {p["id"]: (nodes[p["from"]], nodes[p["to"]]) for p in layout["pipes"] if p["kind"] != "pump"}
    return nodes, pipes


def select_pipes(probs: dict[str, float], cover: float = PROB_COVER) -> tuple[list[str], float]:
    order = sorted(probs, key=lambda k: -probs[k])
    tot = sum(probs.values()) or 1.0
    chosen, acc = [], 0.0
    for p in order:
        if acc >= cover:
            break
        chosen.append(p)
        acc += probs[p] / tot
    return chosen, round(acc, 4)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def waypoints_along(a, b, spacing: float = SPACING_M) -> list[list[float]]:
    length = _dist(a, b)
    k = max(1, math.ceil(length / spacing))
    return [[round(a[0] + (b[0] - a[0]) * i / k, 1), round(a[1] + (b[1] - a[1]) * i / k, 1)] for i in range(k + 1)]


def plan_route(pipe_ids: list[str], pipes: dict, base) -> dict:
    todo, pos, wps, order = list(pipe_ids), base, [[round(base[0], 1), round(base[1], 1)]], []
    length = 0.0
    while todo:
        best = min(todo, key=lambda p: min(_dist(pos, pipes[p][0]), _dist(pos, pipes[p][1])))
        a, b = pipes[best]
        if _dist(pos, b) < _dist(pos, a):
            a, b = b, a
        length += _dist(pos, a) + _dist(a, b)
        wps.extend(waypoints_along(a, b))
        pos = b
        order.append(best)
        todo.remove(best)
    length += _dist(pos, base)
    wps.append([round(base[0], 1), round(base[1], 1)])
    flight = length / SPEED_MPS + HOVER_S_PER_PIPE * len(order)
    return {"pipes": order, "waypoints": wps, "length_m": round(length, 1), "flight_s": round(flight, 1)}


def main() -> None:
    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    nodes, pipes = pipe_geometry(layout)
    base = nodes[BASE_NODE]
    rise = sunrise_local()
    routes = []
    for s in res["scenarios"]:
        for n, b in s["by_sensors"].items():
            probs = {p: v.get("fused", 0.0) for p, v in b["pipes"].items() if p in pipes and v.get("fused", 0.0) > 0}
            if not b["detected"] or not probs:
                continue
            chosen, covered = select_pipes(probs)
            r = plan_route(chosen, pipes, base)
            routes.append({"scenario": s["id"], "title": s["title"], "sensors_n": int(n),
                           "true_pipes": s["true"]["pipes"],
                           "true_pipe_in_route": bool(set(s["true"]["pipes"]) & set(chosen)),
                           "prob_covered": covered, **r,
                           "fits_one_battery": r["flight_s"] <= BATTERY_S,
                           "takeoff": f"{FLIGHT_DATE.isoformat()} {rise} (sunrise)"})
    doc = {"version": "1.1", "simulation": True,
           "source": "farm/drone/dispatch.py on dashboard/farm/results.json (fused maps, 1-minute average case)",
           "rule": f"pipes holding >= {int(PROB_COVER * 100)} % of the fused probability; waypoints every "
                   f"{SPACING_M:g} m at {ALT_M:g} m; nearest-neighbour order from base; {SPEED_MPS:g} m/s "
                   f"+ {HOVER_S_PER_PIPE:g} s hover per pipe; take-off at sunrise",
           "base": {"node": BASE_NODE, "x": base[0], "y": base[1], "note": "pump station by the farm gate"},
           "alt_m": ALT_M, "speed_mps": SPEED_MPS, "spacing_m": SPACING_M, "battery_s": BATTERY_S,
           "sunrise": {"date": FLIGHT_DATE.isoformat(), "local": rise, "site": f"{LAT} N, {LON} E (assumption)"},
           "next_steps": "real flights through the vendor SDK / MAVLink; permits (market lead)",
           "routes": routes}
    DASH.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    six = [r for r in routes if r["sensors_n"] == 6]
    hit = sum(r["true_pipe_in_route"] for r in six)
    print(f"{len(routes)} routes, sunrise {rise}; 6 sensors: true pipe inside the route in {hit}/{len(six)}, "
          f"median flight {sorted(r['flight_s'] for r in six)[len(six) // 2] if six else 0:.0f} s -> "
          f"{DASH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
