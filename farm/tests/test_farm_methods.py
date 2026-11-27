import json

import numpy as np
import pytest

from farm.methods.common import TEST_WORLDS, load, sensor_sets, site_to_link_probs
from farm.methods.m2 import FarmM2
from farm.methods.results import DASH, fuse


@pytest.fixture(scope="module")
def fd():
    return load(60)


def test_split_is_by_world(fd):
    w = fd.sc.world_id.to_numpy() % 10
    assert set(np.unique(w[fd.test])) == set(TEST_WORLDS)
    assert not (fd.train & fd.test).any() and (fd.train | fd.test).all()


def test_m2_probabilities(fd):
    try:
        sensors = sensor_sets()["6"]
    except FileNotFoundError:
        pytest.skip("placement sets missing")
    m2 = FarmM2(fd, sensors).fit()
    rows = np.where(fd.test)[0][:200]
    P = m2.predict(rows)
    assert np.allclose(P.sum(axis=1), 1.0)
    # only sites that exist in the scenario's shift get probability
    cfg = fd.sc.config_id.to_numpy()[rows]
    for i, c in enumerate(cfg):
        allowed = set(fd.sc[fd.sc.config_id == c].leak_at)
        assert {fd.sites[j] for j in np.nonzero(P[i])[0]} <= allowed


def test_m2_beats_chance_on_big_leaks(fd):
    try:
        sensors = sensor_sets()["10"]
    except FileNotFoundError:
        pytest.skip("placement sets missing")
    m2 = FarmM2(fd, sensors).fit()
    rows = np.where(fd.test & (fd.sc.size_pct.to_numpy() == 10))[0]
    pred = m2.predict(rows).argmax(axis=1)
    right = np.mean([fd.site_branch[fd.sites[p]] == fd.sc.branch.iloc[r] for p, r in zip(pred, rows)])
    # per shift a leak can be on the main, an open sector or a closed sector head: chance < 1/3
    assert right > 0.5


def test_fuse_normalises_and_respects_support():
    a = np.array([[0.7, 0.3, 0.0]])
    b = np.array([[0.2, 0.8, 0.0]])
    f = fuse(a, b)
    assert np.isclose(f.sum(), 1.0) and f[0, 2] == 0.0 and f[0, 1] > f[0, 0]


def test_link_probs_sum_to_one(fd):
    p = np.zeros(len(fd.sites))
    p[fd.sites.index("H1")] = 0.5
    p[fd.sites.index("MN1")] = 0.5
    lp = site_to_link_probs(p, fd)
    assert np.isclose(sum(lp.values()), 1.0) and lp["MN1"] >= 0.5


def test_exported_results():
    if not DASH.exists():
        pytest.skip("run python -m farm.methods.results first")
    d = json.loads(DASH.read_text(encoding="utf-8"))
    assert d["simulation"] is True and len(d["scenarios"]) == 10
    for s in d["scenarios"]:
        for n, b in s["by_sensors"].items():
            tot = sum(v.get("fused", 0.0) for v in b["pipes"].values())
            assert abs(tot - 1.0) < 0.02, (s["id"], n, tot)
