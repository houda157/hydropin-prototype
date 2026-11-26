import json

import numpy as np
import pytest

from farm.placement.optimise import (DASH, Dataset, evaluate, genetic, greedy, load_dataset, score,
                                     summarise, swaps)


@pytest.fixture(scope="module")
def ds():
    return load_dataset()


def toy():
    # 3 candidates: main, sector_1, sector_2; 3 leaks, one per branch; node 2 unpressurised for leak 1
    dP = np.array([[-0.05, -0.05, -0.05],
                   [-0.04, -0.09, -0.05],
                   [-0.04, 0.0, -0.10]])
    return Dataset(dP=dP, cand=["PS", "H1", "H2"], cand_branch=np.array(["main", "sector_1", "sector_2"]),
                   branch=np.array(["main", "sector_1", "sector_2"]), size=np.array([3.0, 3.0, 3.0]),
                   world=np.array([0, 0, 0]), sigma=0.01)


def test_toy_rules():
    t = toy()
    r = evaluate([0, 1, 2], t.dP, t.cand_branch, t.branch, t.sigma)
    assert r["detected"].all()
    # leak 0: PS has the largest extra drop (-0.05 vs mean -0.0433) -> main, right
    # leak 1: H2 reads 0 (closed) and is ignored; H1 drops most -> sector_1, right
    # leak 2: H2 drops most -> sector_2, right
    assert r["isolated"].tolist() == [True, True, True]
    one = evaluate([0], t.dP, t.cand_branch, t.branch, t.sigma)
    assert one["detected"].all() and one["isolated"].tolist() == [True, False, False]
    quiet = evaluate([0], t.dP, t.cand_branch, t.branch, sigma=0.02)   # 3 sigma = 0.06 > 0.05
    assert not quiet["detected"].any()


def test_detection_never_drops_when_adding_sensors(ds):
    rows = []
    prev = 0.0
    for c in range(len(ds.cand)):
        rows.append(c)
        d = evaluate(rows, ds.dP, ds.cand_branch, ds.branch, ds.sigma)["detected"].mean()
        assert d >= prev - 1e-12
        prev = d


def test_isolated_implies_detected(ds):
    r = evaluate(range(len(ds.cand)), ds.dP, ds.cand_branch, ds.branch, ds.sigma)
    assert not (r["isolated"] & ~r["detected"]).any()


def test_swaps_and_ga_never_worse_than_greedy(ds):
    g = greedy(3, ds)
    s = swaps(g, ds)
    assert score(s, ds) >= score(g, ds) - 1e-12
    ga = genetic(3, ds, [g, s], pop=12, gens=8)
    assert score(ga, ds) >= score(s, ds) - 1e-12
    assert len(set(ga)) == 3


def test_ga_reproducible(ds):
    a = genetic(4, ds, [greedy(4, ds)], pop=10, gens=5)
    b = genetic(4, ds, [greedy(4, ds)], pop=10, gens=5)
    assert a == b


def test_big_leaks_all_detected_by_one_sensor(ds):
    s = summarise([ds.cand.index("PS")], ds)
    assert s["by_size"]["10"]["detected_pct"] == 100.0


def test_exported_file(ds):
    if not DASH.exists():
        pytest.skip("run python -m farm.placement.optimise first")
    d = json.loads(DASH.read_text(encoding="utf-8"))
    assert d["simulation"] is True
    assert [s["n"] for s in d["sets"]] == list(range(1, 11))
    for s in d["sets"]:
        assert len(s["nodes"]) == s["n"] and set(s["nodes"]) <= set(d["candidates"])
        assert s["cost_dt"] == s["n"] * d["cost_per_node_dt"]
        assert 0 <= s["isolated_pct"] <= s["detected_pct"] <= 100
    assert 1 <= d["recommended_n"] <= 10
