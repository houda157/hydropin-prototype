import json

import numpy as np
import pandas as pd
import pytest

from farm.leaks import generate
from farm.leaks.scenarios import build_grid
from farm.leaks.simulate import simulate_world
from farm.model.build_farm import load_params

pytestmark = pytest.mark.filterwarnings("ignore:Covariance of the parameters")

P = load_params()


@pytest.fixture(scope="module")
def world0():
    worlds, rows = build_grid(P, n_seeds=1, sizes=[1, 10], configs=[0])
    return simulate_world(P, worlds[0], rows, sigma_bar=0.01, n_healthy=20)


def test_every_leak_lowers_pressure_everywhere_pressurised(world0):
    live = np.abs(world0["p_healthy"]) > 1e-9          # nodes behind closed valves read 0
    for rec, d in zip(world0["records"], world0["dP"]):
        assert (d[live] < 0).all(), rec["leak_at"]
        assert rec["pump_lps"] > rec["healthy_pump_lps"]


def test_realised_leak_close_to_target(world0):
    ratio = np.array([r["leak_lps"] / r["q_target_lps"] for r in world0["records"]])
    assert (ratio > 0.7).all() and (ratio <= 1.0 + 1e-6).all()


def test_bigger_leak_bigger_signature(world0):
    recs = world0["records"]
    by_site = {}
    for rec, d in zip(recs, world0["dP"]):
        by_site.setdefault((rec["leak_kind"], rec["leak_at"]), {})[rec["size_pct"]] = np.abs(d).max()
    for site, v in by_site.items():
        assert v[10.0] > 5 * v[1.0], site


def test_quick_generate_writes_consistent_files(tmp_path):
    generate.main(["--quick", "--out", str(tmp_path), "--workers", "1"])
    meta = json.loads((tmp_path / "meta.json").read_text())
    s = pd.read_csv(tmp_path / "scenarios.csv")
    S, N, C = len(s), len(meta["node_order"]), len(meta["candidate_order"])
    assert meta["n_scenarios"] == S > 0 and meta["simulation"] is True
    assert np.load(tmp_path / "dP.npy").shape == (C, S)
    for f in ("X", "X_twin", "X_clean"):
        assert np.load(tmp_path / "gnn" / f"{f}.npy").shape == (S, N)
    assert np.load(tmp_path / "gnn" / "sector_open.npy").shape == (S, N)
    y_node = np.load(tmp_path / "gnn" / "y_node.npy")
    y_pipe = json.loads((tmp_path / "gnn" / "y_pipe.json").read_text())
    assert len(y_node) == len(y_pipe) == S
    assert all((n >= 0) != bool(p) for n, p in zip(y_node, y_pipe))   # exactly one label each
    g = json.loads((tmp_path / "gnn" / "graph.json").read_text())
    assert [n["id"] for n in g["nodes"]] == meta["node_order"]
    assert s.scenario_id.is_monotonic_increasing
