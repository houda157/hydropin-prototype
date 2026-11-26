"""Replay files and run scoring for the rev 1 bench (same code for simulated and real runs).

A replay is one run: metadata + ground-truth events + the detector's processed frames.
Format (contract/api.md, "Replay file"):

    {"version": "1.0", "id": "...", "simulation": true|false, "source": "simulator|bench",
     "label": "none|leak_L1|leak_L2|leak_L3", "meta": {...}, "events": [{"t_s", "type", "tap"}],
     "frames": [{processed frame + "t_s"}]}

Scoring uses the events (never the detector). A leak run counts as detected when the detector reaches
LEAK after ``leak_on``; the delay is from ``leak_on`` to the first LEAK frame; the branch is the one
reported on that frame. Any WATCH/LEAK before ``leak_on`` (or in a ``none`` run) is a false alarm.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .bench_detector import TAP_BRANCH

KEEP = ("ts", "pt1_bar", "pt2_bar", "dp_bar", "flow_lpm", "flow_base_lpm", "state", "p_leak", "methods",
        "faults", "branch", "loc", "leak_lpm", "lost_l")


def _sec(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()


def build_replay(frames: list[dict], events: list[dict], *, run_id: str, label: str, simulation: bool,
                 source: str, meta: dict | None = None) -> dict[str, Any]:
    """``events`` may carry ``t_s`` (seconds from the first frame) or an ISO ``ts``."""
    if not frames:
        raise ValueError("no frames")
    t0 = _sec(frames[0]["ts"])
    out_frames = []
    for f in frames:
        g = {k: f.get(k) for k in KEEP}
        g["t_s"] = round(_sec(f["ts"]) - t0, 2)
        out_frames.append(g)
    ev = []
    for e in events:
        t = e["t_s"] if "t_s" in e else _sec(e["ts"]) - t0
        ev.append({"t_s": round(float(t), 2), "type": e["type"], "tap": e.get("tap")})
    return {"version": "1.0", "id": str(run_id), "simulation": bool(simulation), "source": source,
            "label": label, "meta": meta or {}, "events": sorted(ev, key=lambda x: x["t_s"]),
            "frames": out_frames}


def score_replay(replay: dict) -> dict[str, Any]:
    frames = replay["frames"]
    label = replay["label"]
    tap = label.split("_", 1)[1] if label.startswith("leak_") else None
    on = next((e["t_s"] for e in replay["events"] if e["type"] == "leak_on"), None)
    off = next((e["t_s"] for e in replay["events"] if e["type"] == "leak_off"), None)
    alarm = ("WATCH", "LEAK")
    fa = [f for f in frames if f["state"] in alarm and (on is None or f["t_s"] < on)]
    false_alarm = bool(fa)
    res: dict[str, Any] = {"id": replay["id"], "label": label, "simulation": replay["simulation"],
                           "false_alarm": false_alarm, "faults": sorted({x for f in frames for x in f["faults"]})}
    if tap is None or on is None:
        res.update(detected=None, watched=None, delay_s=None, branch=None, branch_ok=None, tap_top=None,
                   opening=replay["meta"].get("opening"))
        return res
    res["opening"] = replay["meta"].get("opening")
    res["watched"] = any(f["state"] in alarm and f["t_s"] >= on and (off is None or f["t_s"] <= off + 10)
                         for f in frames)
    hit = next((f for f in frames if f["state"] == "LEAK" and f["t_s"] >= on and (off is None or f["t_s"] <= off + 10)),
               None)
    res["detected"] = hit is not None
    res["delay_s"] = round(hit["t_s"] - on, 1) if hit else None
    res["branch"] = hit["branch"] if hit else None
    res["branch_ok"] = (hit["branch"] == TAP_BRANCH[tap]) if hit else False
    res["tap_top"] = max(hit["loc"], key=hit["loc"].get) if hit and hit.get("loc") else None
    res["leak_lpm"] = hit["leak_lpm"] if hit else None
    res["measured_leak_lpm"] = replay["meta"].get("measured_leak_lpm")
    return res


def scoreboard(results: list[dict], *, simulation: bool, notes: str = "") -> dict[str, Any]:
    leaks = [r for r in results if r["detected"] is not None]
    clean = [r for r in results if r["detected"] is None]
    det = [r for r in leaks if r["detected"]]
    delays = sorted(r["delay_s"] for r in det)
    per_tap: dict[str, dict] = {}
    for r in leaks:
        t = r["label"].split("_", 1)[1]
        d = per_tap.setdefault(t, {"runs": 0, "detected": 0, "branch_ok": 0})
        d["runs"] += 1
        d["detected"] += int(bool(r["detected"]))
        d["branch_ok"] += int(bool(r["branch_ok"]))
    per_opening: dict[str, dict] = {}
    for r in leaks:
        d = per_opening.setdefault(str(r.get("opening")), {"runs": 0, "detected": 0, "watched": 0})
        d["runs"] += 1
        d["detected"] += int(bool(r["detected"]))
        d["watched"] += int(bool(r.get("watched")))
    return {
        "version": "1.0",
        "simulation": simulation,
        "notes": notes,
        "summary": {
            "leak_runs": len(leaks),
            "detected": len(det),
            "detection_rate": round(len(det) / len(leaks), 3) if leaks else None,
            "watch_or_leak_rate": round(sum(bool(r.get("watched")) for r in leaks) / len(leaks), 3) if leaks else None,
            "branch_accuracy": round(sum(r["branch_ok"] for r in det) / len(det), 3) if det else None,
            "median_delay_s": delays[len(delays) // 2] if delays else None,
            "clean_runs": len(clean),
            "false_alarm_runs": sum(r["false_alarm"] for r in results),
        },
        "per_tap": per_tap,
        "per_opening": per_opening,
        "runs": results,
    }
