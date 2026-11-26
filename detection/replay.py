"""Replay files and run scoring for the rev 1 bench (same code for simulated and real runs).

A replay is one run: metadata + ground-truth events + the detector's processed frames.
Format (contract/api.md, "Replay file"):

    {"version": "1.0", "id": "...", "simulation": true|false, "source": "simulator|bench",
     "label": "none|leak_L1|leak_L2|leak_L3", "meta": {...}, "events": [{"t_s", "type", "tap"}],
     "frames": [{processed frame + "t_s"}]}

Scoring uses the events (never the detector). A leak run counts as detected when the detector reaches
LEAK after ``leak_on``; the delay is from ``leak_on`` to the first LEAK frame; the branch is the one
reported on that frame. Any WATCH/LEAK before ``leak_on`` (or in a ``none`` run) is a false alarm.

Each method is also scored *alone*: it "fires" when its own score (sigmoid of its log-odds) stays
above tau2 for n consecutive samples, the same rule the fused result uses. False alarms per hour count
rising edges into LEAK (or a method firing) during healthy, monitored time (baseline learned, before
``leak_on``). Headline numbers use test-split runs only when a split exists (detection/train_bench.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .bench_detector import TAP_BRANCH, TAPS

METHODS = ("flow", "m2")
MONITORED = ("HEALTHY", "WATCH", "LEAK")

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


def _method_fires(frames: list[dict], m: str, tau2: float, n: int) -> list[bool]:
    """Per frame: has method m alone been above tau2 for n consecutive samples?"""
    out, run = [], 0
    for f in frames:
        md = (f.get("methods") or {}).get(m) or {}
        sc = md.get("score")
        ok = sc is not None and not md.get("excluded") and f["state"] in MONITORED
        run = run + 1 if ok and sc > tau2 else 0
        out.append(run >= n)
    return out


def _edges(flags: list[bool]) -> int:
    return sum(1 for i, x in enumerate(flags) if x and (i == 0 or not flags[i - 1]))


def score_replay(replay: dict, tau2: float = 0.9, n_consecutive: int = 10) -> dict[str, Any]:
    frames = replay["frames"]
    label = replay["label"]
    meta = replay.get("meta") or {}
    tap = label.split("_", 1)[1] if label.startswith("leak_") else None
    on = next((e["t_s"] for e in replay["events"] if e["type"] == "leak_on"), None)
    off = next((e["t_s"] for e in replay["events"] if e["type"] == "leak_off"), None)
    alarm = ("WATCH", "LEAK")
    fa = [f for f in frames if f["state"] in alarm and (on is None or f["t_s"] < on)]
    false_alarm = bool(fa)
    # healthy monitored time before the leak (or the whole run): false alarms per hour
    pre = [f for f in frames if on is None or f["t_s"] < on]
    healthy_s = 0.0
    for a, b in zip(pre, pre[1:]):
        if a["state"] in MONITORED and b["t_s"] - a["t_s"] < 3.0:
            healthy_s += b["t_s"] - a["t_s"]
    fires = {m: _method_fires(frames, m, tau2, n_consecutive) for m in METHODS}
    k_pre = len(pre)
    res: dict[str, Any] = {"id": replay["id"], "label": label, "simulation": replay["simulation"],
                           "split": meta.get("split"), "blind": bool(meta.get("blind")),
                           "false_alarm": false_alarm, "faults": sorted({x for f in frames for x in f["faults"]}),
                           "healthy_s": round(healthy_s, 1),
                           "false_episodes": {"fused": _edges([f["state"] == "LEAK" for f in pre]),
                                              **{m: _edges(fires[m][:k_pre]) for m in METHODS}}}
    if tap is None or on is None:
        res.update(detected=None, watched=None, delay_s=None, branch=None, branch_ok=None, tap_top=None,
                   opening=meta.get("opening"), methods_alone=None)
        return res
    res["opening"] = meta.get("opening")
    alone = {}
    for m in METHODS:
        k = next((i for i, f in enumerate(frames) if fires[m][i] and f["t_s"] >= on
                  and (off is None or f["t_s"] <= off + 10)), None)
        alone[m] = {"detected": k is not None, "delay_s": round(frames[k]["t_s"] - on, 1) if k is not None else None}
    res["methods_alone"] = alone
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
    res["measured_leak_lpm"] = meta.get("measured_leak_lpm")
    return res


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def _summary(results: list[dict]) -> dict[str, Any]:
    leaks = [r for r in results if r["detected"] is not None]
    clean = [r for r in results if r["detected"] is None]
    det = [r for r in leaks if r["detected"]]
    hours = sum(r.get("healthy_s", 0.0) for r in results) / 3600.0
    fe = sum((r.get("false_episodes") or {}).get("fused", 0) for r in results)
    return {
        "leak_runs": len(leaks),
        "detected": len(det),
        "detection_rate": round(len(det) / len(leaks), 3) if leaks else None,
        "watch_or_leak_rate": round(sum(bool(r.get("watched")) for r in leaks) / len(leaks), 3) if leaks else None,
        "branch_accuracy": round(sum(r["branch_ok"] for r in det) / len(det), 3) if det else None,
        "tap_accuracy": round(sum(r["tap_top"] == r["label"].split("_", 1)[1] for r in det) / len(det), 3) if det else None,
        "median_delay_s": _median(r["delay_s"] for r in det),
        "clean_runs": len(clean),
        "false_alarm_runs": sum(r["false_alarm"] for r in results),
        "healthy_hours": round(hours, 3),
        "false_alarms_per_hour": round(fe / hours, 3) if hours > 0 else None,
    }


def _per_method(results: list[dict]) -> dict[str, Any]:
    leaks = [r for r in results if r["detected"] is not None]
    hours = sum(r.get("healthy_s", 0.0) for r in results) / 3600.0
    out = {}
    for m in ("fused",) + METHODS:
        if m == "fused":
            hits = [r for r in leaks if r["detected"]]
            delays = [r["delay_s"] for r in hits]
        else:
            hits = [r for r in leaks if (r.get("methods_alone") or {}).get(m, {}).get("detected")]
            delays = [r["methods_alone"][m]["delay_s"] for r in hits]
        fe = sum((r.get("false_episodes") or {}).get(m, 0) for r in results)
        out[m] = {"detection_rate": round(len(hits) / len(leaks), 3) if leaks else None,
                  "median_delay_s": _median(delays),
                  "false_alarms_per_hour": round(fe / hours, 3) if hours > 0 else None}
    return out


def _confusion(results: list[dict]) -> dict[str, Any]:
    taps = {t: {**{u: 0 for u in TAPS}, "missed": 0} for t in TAPS}
    branches = {b: {"A": 0, "B": 0, "missed": 0} for b in ("A", "B")}
    for r in results:
        if r["detected"] is None:
            continue
        t = r["label"].split("_", 1)[1]
        if not r["detected"]:
            taps[t]["missed"] += 1
            branches[TAP_BRANCH[t]]["missed"] += 1
            continue
        if r.get("tap_top") in TAPS:
            taps[t][r["tap_top"]] += 1
        if r.get("branch") in ("A", "B"):
            branches[TAP_BRANCH[t]][r["branch"]] += 1
    return {"taps": taps, "branches": branches, "rows": "true", "cols": "detector"}


def scoreboard(results: list[dict], *, simulation: bool, notes: str = "") -> dict[str, Any]:
    has_split = any(r.get("split") for r in results)
    head = [r for r in results if r.get("split") == "test"] if has_split else results
    leaks = [r for r in head if r["detected"] is not None]
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
    blind = [r for r in results if r.get("blind")]
    return {
        "version": "1.1",
        "simulation": simulation,
        "notes": notes,
        "headline": "test split only (runs the model never trained on)" if has_split else "all runs",
        "split_counts": {k: sum(r.get("split") == k for r in results) for k in ("train", "test")} if has_split else None,
        "summary": _summary(head),
        "summary_all_runs": _summary(results) if has_split else None,
        "per_method": _per_method(head),
        "confusion": _confusion(head),
        "per_tap": per_tap,
        "per_opening": per_opening,
        "blind": {"runs": len(blind), "summary": _summary(blind) if blind else None,
                  "events": [{"id": r["id"], "label": r["label"], "detected": r["detected"], "delay_s": r["delay_s"],
                              "branch": r["branch"], "false_alarm": r["false_alarm"]} for r in blind]},
        "runs": results,
    }
