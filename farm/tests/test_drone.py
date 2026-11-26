import json
import math

import pytest

from farm.drone.dispatch import DASH, plan_route, select_pipes, sunrise_local, waypoints_along


def test_select_pipes_covers_90_percent():
    chosen, cov = select_pipes({"a": 0.5, "b": 0.3, "c": 0.15, "d": 0.05})
    assert chosen == ["a", "b", "c"] and cov >= 0.9


def test_waypoint_spacing():
    w = waypoints_along((0, 0), (95, 0))
    assert w[0] == [0, 0] and w[-1] == [95, 0]
    assert max(math.dist(w[i], w[i + 1]) for i in range(len(w) - 1)) <= 10.0 + 1e-9


def test_route_starts_and_ends_at_base_and_flies_nearest_first():
    pipes = {"far": ((500, 0), (600, 0)), "near": ((10, 0), (50, 0))}
    r = plan_route(["far", "near"], pipes, (0, 0))
    assert r["pipes"] == ["near", "far"]
    assert r["waypoints"][0] == [0, 0] and r["waypoints"][-1] == [0, 0]
    assert math.isclose(r["length_m"], 1200.0)


def test_sunrise_is_plausible_for_tunisia_in_november():
    hh, mm = map(int, sunrise_local().split(":"))
    assert 6 * 60 + 30 <= hh * 60 + mm <= 7 * 60 + 30


def test_exported_drone_file():
    if not DASH.exists():
        pytest.skip("run python -m farm.drone.dispatch first")
    d = json.loads(DASH.read_text(encoding="utf-8"))
    assert d["simulation"] is True and d["routes"]
    for r in d["routes"]:
        assert r["prob_covered"] >= 0.9
        assert r["waypoints"][0] == r["waypoints"][-1] == [d["base"]["x"], d["base"]["y"]]
