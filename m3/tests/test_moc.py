"""M3 solver validation (role 5 brief: validate before anything else)."""
import numpy as np
import pytest

from m3.echo import echo_distance
from m3.moc import joukowsky_head, leak_cda_for_fraction, load_setup, simulate, steady_state

BASE = load_setup()


def _plateau(r, s, t_from, t_to):
    m = (r.t > t_from) & (r.t < t_to)
    return r.H_valve[m]


def test_joukowsky_jump_instantaneous_frictionless():
    s = BASE.with_(f=0.0, Tc=0.0, x_leak=None)
    r = simulate(s)
    T2 = 2 * s.L / s.a
    dh = _plateau(r, s, s.t_close + 0.02, s.t_close + T2 - 0.02).mean() - r.H0
    assert dh == pytest.approx(joukowsky_head(s), rel=0.01)


def test_wave_period_is_4L_over_a():
    s = BASE.with_(f=0.0, Tc=0.0, duration=6.0)
    r = simulate(s)
    sig = r.H_valve - r.H0
    after = r.t > s.t_close + s.dt
    sign = np.sign(sig[after])
    t_after = r.t[after]
    flips = t_after[1:][np.diff(sign) != 0]
    half_periods = np.diff(flips)
    period = 2 * half_periods.mean()
    assert period == pytest.approx(4 * s.L / s.a, rel=0.01)


def test_frictionless_wave_keeps_amplitude_friction_damps_it():
    lossless = simulate(BASE.with_(f=0.0, Tc=0.0, duration=6.0))
    lossy = simulate(BASE.with_(f=0.05, Tc=0.0, duration=6.0))
    late = lossless.t > 5.0
    assert np.ptp(lossless.H_valve[late]) == pytest.approx(2 * joukowsky_head(BASE), rel=0.01)
    assert np.ptp(lossy.H_valve[late]) < 0.9 * np.ptp(lossless.H_valve[late])


def test_slow_closure_gives_smaller_surge_than_2L_over_a_rule():
    # closure slower than 2L/a: the peak is below Joukowsky
    s = BASE.with_(f=0.0, Tc=3 * 2 * BASE.L / BASE.a, duration=4.0)
    r = simulate(s)
    assert r.H_valve.max() - r.H0 < 0.6 * joukowsky_head(s)


def test_steady_state_holds_without_valve_motion_and_conserves_mass():
    x = 100.0
    s = BASE.with_(x_leak=x, leak_cda=leak_cda_for_fraction(BASE, 0.05, x), t_close=10.0, duration=0.5)
    st = steady_state(s)
    assert st.Qu[st.i_leak] - st.Qd[st.i_leak] == pytest.approx(st.q_leak, rel=1e-9)
    assert st.q_leak == pytest.approx(0.05 * s.Q0, rel=1e-6)
    r = simulate(s)
    assert np.abs(r.H_valve - r.H0).max() < 1e-9
    assert np.abs(r.q_leak - st.q_leak).max() < 1e-12


def test_grid_convergence():
    s = BASE.with_(x_leak=80.0, leak_cda=leak_cda_for_fraction(BASE, 0.05, 80.0))
    coarse = simulate(s)
    fine = simulate(s.with_(N=2 * s.N))
    t, hc = coarse.sampled(2000)
    _, hf = fine.sampled(2000)
    assert np.abs(hc - hf).max() < 0.02 * joukowsky_head(s)


def test_no_column_separation_at_default_settings():
    assert simulate(BASE).min_head > 0


@pytest.mark.parametrize("x_leak", [20.0, 60.0, 100.0, 140.0])
def test_echo_locates_leak_within_one_metre_at_2khz(x_leak):
    ref = simulate(BASE)
    s = BASE.with_(x_leak=x_leak, leak_cda=leak_cda_for_fraction(BASE, 0.05, x_leak))
    r = simulate(s)
    t, h = r.sampled(2000)
    _, h_ref = ref.sampled(2000)
    e = echo_distance(t, h, h_ref, s.a, s.t_close, L=s.L)
    assert BASE.L - e["distance_m"] == pytest.approx(x_leak, abs=1.0)
