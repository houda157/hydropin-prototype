"""Every JSON file the dashboard reads has the keys listed in contract/dashboard-data.md v1.1."""
import json
from pathlib import Path

import pytest

D = Path(__file__).resolve().parents[1] / "dashboard"


def load(rel):
    p = D / rel
    if not p.exists():
        pytest.skip(f"{rel} not exported")
    return json.loads(p.read_text(encoding="utf-8"))


def has(obj, keys, where):
    missing = [k for k in keys if k not in obj]
    assert not missing, f"{where}: missing {missing}"


def test_scoreboard_sim():
    b = load("scoreboard_sim.json")
    has(b, ["version", "simulation", "headline", "summary", "per_method", "confusion", "per_tap", "per_opening",
            "blind", "runs"], "scoreboard")
    assert b["simulation"] is True
    has(b["summary"], ["leak_runs", "detection_rate", "branch_accuracy", "median_delay_s", "false_alarms_per_hour"], "summary")
    has(b["per_method"], ["fused", "flow", "m2"], "per_method")


def test_replay_index():
    idx = load("replays/index.json")
    for r in idx["runs"]:
        has(r, ["id", "kind", "simulation", "label", "detected", "file"], r.get("id"))
        assert (D / "replays" / r["file"]).exists()


def test_farm_layout():
    l = load("farm/layout.json")
    has(l, ["farm", "nodes", "pipes", "sectors"], "layout")
    has(l["farm"], ["width_m", "length_m", "pump_node", "irrigation_shifts"], "layout.farm")
    has(l["nodes"][0], ["id", "x", "y", "kind", "sector", "branch", "candidate"], "node")
    has(l["sectors"][0], ["id", "bbox"], "sector")


def test_farm_placement():
    p = load("farm/placement.json")
    has(p, ["version", "simulation", "sigma_bar", "k", "cost_per_node_dt", "recommended_n", "sets"], "placement")
    assert p["simulation"] is True
    has(p["sets"][0], ["n", "nodes", "detected_pct", "isolated_pct", "by_size", "cost_dt"], "set")


def test_farm_results_and_drone_agree():
    r = load("farm/results.json")
    has(r, ["version", "simulation", "methods", "metrics", "scenarios", "showcase_case"], "results")
    sc = r["scenarios"][0]
    has(sc, ["id", "title", "true", "open_sectors", "by_sensors"], "scenario")
    has(sc["by_sensors"]["6"], ["sensors", "detected", "top_site", "pipes"], "by_sensors")
    d = load("farm/drone.json")
    has(d, ["version", "simulation", "base", "routes", "sunrise"], "drone")
    ids = {s["id"] for s in r["scenarios"]}
    for route in d["routes"]:
        assert route["scenario"] in ids
        has(route, ["sensors_n", "pipes", "waypoints", "length_m", "flight_s", "takeoff", "true_pipe_in_route"], "route")


def test_m3_files():
    idx = load("m3/index.json")
    has(idx, ["version", "simulation", "label", "methods", "cases"], "m3 index")
    for c in idx["cases"]:
        case = load(f"m3/{c['file']}")
        has(case, ["simulation", "pipe", "leak", "frames", "sensor", "tr", "estimates_m", "error_m"], c["file"])
        assert case["simulation"] is True
