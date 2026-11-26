"""PE pipe-wall viscoelasticity (Kelvin-Voigt creep) in the MOC solver."""
import numpy as np
import pytest

from m3.moc import leak_cda_for_fraction, load_setup, simulate, steady_state

ELASTIC = load_setup(viscoelastic=False)
VE = load_setup(viscoelastic=True)


def test_params_switch():
    assert ELASTIC.ve_J == () and not ELASTIC.viscoelastic
    assert VE.viscoelastic and len(VE.ve_J) == len(VE.ve_tau)


def test_zero_compliance_is_the_elastic_solver():
    s = ELASTIC.with_(x_leak=80.0, leak_cda=leak_cda_for_fraction(ELASTIC, 0.05, 80.0))
    a = simulate(s)
    b = simulate(s.with_(ve_J=(0.0,), ve_tau=(0.01,)))
    assert np.array_equal(a.H_valve, b.H_valve)


def test_steady_state_unchanged_by_creep():
    s = VE.with_(x_leak=80.0, leak_cda=leak_cda_for_fraction(VE, 0.05, 80.0), t_close=10.0, duration=0.5)
    r = simulate(s)
    assert np.abs(r.H_valve - r.H0).max() < 1e-9
    assert np.abs(r.q_leak - steady_state(s).q_leak).max() < 1e-12


def test_creep_damps_the_wave_much_more_than_friction():
    e = simulate(ELASTIC.with_(duration=6.0))
    v = simulate(VE.with_(duration=6.0))
    first = (e.t > 0.1) & (e.t < 1.0)
    late = e.t > 5.0
    decay_e = np.ptp(e.H_valve[late]) / np.ptp(e.H_valve[first])   # friction only (~0.85)
    decay_v = np.ptp(v.H_valve[late]) / np.ptp(v.H_valve[first])   # friction + creep (~0.73)
    assert decay_v < decay_e - 0.08
    assert np.ptp(v.H_valve[late]) < 0.7 * np.ptp(e.H_valve[late])


def test_first_surge_slightly_lower_but_close_to_joukowsky():
    e = simulate(ELASTIC)
    v = simulate(VE)
    win = (e.t > 0.15) & (e.t < 0.3)
    de = e.H_valve[win].mean() - e.H0
    dv = v.H_valve[win].mean() - v.H0
    assert 0.85 * de < dv < de


def test_creep_grid_convergence():
    s = VE.with_(x_leak=80.0, leak_cda=leak_cda_for_fraction(VE, 0.05, 80.0))
    _, hc = simulate(s).sampled(2000)
    _, hf = simulate(s.with_(N=2 * s.N)).sampled(2000)
    assert np.abs(hc - hf).max() < 0.4     # m, on a ~17 m surge


def test_no_column_separation_with_creep():
    assert simulate(VE).min_head > 0
