import numpy as np
import pytest

from farm.model.build_farm import (build_network, load_params, pressurised_nodes,
                                   run_steady, sector_flow_m3s)
from farm.model.export_layout import layout_dict

# WNTR fits its 3-point pump curve exactly, so SciPy cannot estimate a covariance: harmless.
pytestmark = pytest.mark.filterwarnings("ignore:Covariance of the parameters")

P = load_params()
CONFIGS = P["irrigation"]["open_configs"]


@pytest.mark.parametrize("cfg", CONFIGS)
def test_each_shift_delivers_full_demand_within_pressure_band(cfg):
    wn, meta = build_network(P, open_sectors=cfg)
    r = run_steady(wn)
    live = pressurised_nodes(meta, cfg)
    manifolds = [n for n in live if meta.nodes[n]["kind"] in ("manifold", "submain_end")]
    pr = r["pressure_m"][manifolds]
    assert (pr >= P["hydraulics"]["required_pressure_m"]).all()
    assert (pr <= 30).all()
    expected = len(cfg) * sector_flow_m3s(P)
    assert r["flow"]["PUMP"] == pytest.approx(expected, rel=0.01)


def test_pump_operating_point_on_curve():
    wn, _ = build_network(P, open_sectors=CONFIGS[0])
    r = run_steady(wn)
    q = r["flow"]["PUMP"]
    head_gain = r["pressure_m"]["PS"] + wn.get_node("PS").elevation - P["pump"]["suction_head_m"]
    curve = wn.get_curve("PUMP_CURVE").points
    qs, hs = zip(*curve)
    # WNTR fits H = A - B q^C through the 3 points; the operating point lies between them
    assert min(hs) < head_gain < max(hs)
    assert 0 < q < max(qs)


def test_closed_sectors_carry_no_flow():
    cfg = CONFIGS[0]
    wn, meta = build_network(P, open_sectors=cfg)
    r = run_steady(wn)
    for s in meta.sectors:
        if s not in cfg:
            assert abs(r["flow"][f"V{s}"]) < 1e-9


def test_perturbed_world_differs_but_is_reproducible():
    a, _ = build_network(P, seed=1)
    b, _ = build_network(P, seed=1)
    c, _ = build_network(P, seed=2)
    assert a.get_link("MN1").roughness == b.get_link("MN1").roughness
    assert a.get_link("MN1").roughness != c.get_link("MN1").roughness


def test_layout_matches_model():
    lay = layout_dict(P)
    wn, meta = build_network(P)
    assert {n["id"] for n in lay["nodes"]} == set(wn.node_name_list)
    assert {p["id"] for p in lay["pipes"]} == set(wn.link_name_list)
    assert lay["simulation"] is True
    assert sum(n["candidate"] for n in lay["nodes"]) == len(meta.candidate_names) == 16
    assert len(lay["sectors"]) == 6


def test_mass_balance_with_leak():
    cfg = CONFIGS[0]
    wn, meta = build_network(P, open_sectors=cfg)
    wn.get_node("A1").add_leak(wn, area=5e-4, start_time=0)
    r = run_steady(wn)
    names = meta.junction_names
    total_out = r["demand"][names].sum() + r["leak_demand"][names].sum()
    assert r["flow"]["PUMP"] == pytest.approx(total_out, rel=1e-4)
    assert np.isclose(r["leak_demand"]["A1"] > 0, True)
