"""Oracles – leak node, unsteady friction, viscoelasticity, cavitation (math note §5.3–5.7)."""

from __future__ import annotations

import copy
from functools import lru_cache

import numpy as np

from hydropin_sim.contracts import LeakSpec
from hydropin_sim.physics.waves import char_impedance, cavitation_head, leak_admittance, leak_reflection
from hydropin_sim.transient.moc import Options, run
from oracles.base import Check
from oracles.transient_cases import L_RPV, P, close, rpv_spec, setup

G = P.water.G.v
X_LEAK = 80.0
T0 = 0.05


@lru_cache(maxsize=4)
def partial_closure(leak: bool):
    spec = rpv_spec(h_res=25.0)
    # the healthy reference keeps a zero-size leak node at the same place → identical grid
    leaks = [LeakSpec(pipe="P1", position=X_LEAK / L_RPV, area=3e-6 if leak else 1e-14)]
    m, st = setup(spec, leaks, dt_max=2.5e-4)
    r = run(m, Options(duration=1.0, record=["END"]), [close(m, t_start=T0, closure=0.10, t_close=0.0)])
    return m, st, r


@lru_cache(maxsize=4)
def full_closure(mode: str, closure=1.0):
    m, st = setup(rpv_spec(h_res=25.0), dt_max=5e-4)
    opts = Options(duration=9.0, record=["END"], unsteady=(mode == "uf"), viscoelastic=(mode == "ve"))
    r = run(m, opts, [close(m, t_start=T0, closure=closure, t_close=0.01)],
            p_vap_head=cavitation_head(P.p_vap(20.0), P.water.P_ATM.v, P.water.RHO_W.v, G))
    return m, r


def envelope(t, h, h0, period, n):
    """Max |h - h0| in each of the first n periods after closure."""
    return np.array([np.max(np.abs(h[(t >= T0 + k * period) & (t < T0 + (k + 1) * period)] - h0))
                     for k in range(n)])


def first_down(t, h, h0, dh):
    return float(t[np.argmax((t > T0) & (h < h0 - dh / 2))])


def checks() -> list[Check]:
    c: list[Check] = []
    # 5.1 viscoelastic with J_k = 0 must equal elastic exactly
    m, st = setup(rpv_spec(h_res=25.0), dt_max=1e-3)
    m0 = copy.deepcopy(m)
    m0.j_k = [np.zeros_like(j) for j in m0.j_k]
    ev = [close(m0, t_start=T0, t_close=0.01)]
    r_el = run(m0, Options(duration=1.0, record=["END"]), ev)
    r_ve0 = run(m0, Options(duration=1.0, record=["END"], viscoelastic=True), ev)
    c.append(Check("5.1", "Viscoelastic solver with J_k = 0 reproduces the elastic solver",
                   1e-9, float(np.max(np.abs(r_el.head - r_ve0.head))), kind="le", ref="§5.3", unit="m"))

    # 5.2–5.3 leak reflection: arrival time and amplitude (small-signal, 10 % closure)
    ml, stl, rl = partial_closure(True)
    mh, sth, rh = partial_closure(False)
    a = ml.grid.a[0]
    dt = ml.grid.dt
    t = rl.time
    t_arr = T0 + 2 * (L_RPV - X_LEAK) / a
    hh = np.interp(t, rh.time, rh.head[:, 0])        # healthy run on the leaky run's time grid
    d = rl.head[:, 0] - hh
    win = (t > T0 + 2 * dt) & (t < T0 + 2 * L_RPV / a - 2 * dt)
    jump_idx = np.argmax(np.abs(np.diff(d)) * win[1:]) + 1
    c.append(Check("5.2", f"Leak echo arrives at the valve at t₀ + 2(L − x_L)/a (leak at {X_LEAK:.0f} m)",
                   float(t_arr), float(t[jump_idx]), 3 * dt, "abs", "§5.7", "s"))
    h = rl.head[:, 0]
    w = int(0.004 / dt)
    i_arr = int(np.argmin(np.abs(t - t_arr)))
    i_cl = int(np.argmin(np.abs(t - T0)))
    dH1 = float(np.mean(h[i_cl + 3:i_cl + 3 + w]) - h[0])
    jump_l = np.mean(h[i_arr + 3:i_arr + 3 + w]) - np.mean(h[i_arr - 3 - w:i_arr - 3])
    jump_h = np.mean(hh[i_arr + 3:i_arr + 3 + w]) - np.mean(hh[i_arr - 3 - w:i_arr - 3])
    measured = float(jump_l - jump_h)
    six = {n: i for i, n in enumerate(stl.node_ids)}
    h_leak = stl.pressure[0, six["LEAK0"]]
    q_leak = stl.leak_flow[0]
    B = char_impedance(a, ml.d[0], G)
    r_l = float(leak_reflection(B, leak_admittance(q_leak, h_leak)))
    q_v = float(stl.flow[0, stl.link_ids.index([p for p in stl.link_ids if p.startswith("P1")][-1])]) * 0.9
    h_v = stl.pressure[0, six["END"]] + dH1
    y_v = q_v / (2 * h_v)
    expected = r_l * dH1 * 2 / (1 + B * y_v)
    c.append(Check("5.3", "Leak echo amplitude = r_L · ΔH₁ · 2/(1 + B·Y_valve) (small-signal theory)",
                   float(expected), measured, 0.15, "rel", "§5.7", "m"))

    # 5.4–5.6 damping: quasi-steady vs unsteady friction vs viscoelastic
    me, re_ = full_closure("qs")
    mu, ru = full_closure("uf")
    mv, rv = full_closure("ve")
    h0 = re_.head[0, 0]
    period = 4 * L_RPV / me.grid.a[0]
    env_qs = envelope(re_.time, re_.head[:, 0], h0, period, 4)
    env_uf = envelope(ru.time, ru.head[:, 0], h0, period, 4)
    env_ve = envelope(rv.time, rv.head[:, 0], h0, period * 1.15, 4)
    c.append(Check("5.4", "Unsteady friction damps more than quasi-steady friction (4th-period amplitude ratio)",
                   float(env_qs[3] / env_qs[0]), float(env_uf[3] / env_uf[0]), kind="le", ref="§5.4"))
    c.append(Check("5.5", "Viscoelastic (PE creep) damps more than an elastic pipe (4th-period amplitude ratio)",
                   float(env_qs[3] / env_qs[0]), float(env_ve[3] / env_ve[0]), kind="le", ref="§5.3"))
    dh = me.grid.a[0] * me.q0[0] / me.area[0] / G
    c.append(Check("5.6", "Viscoelastic creep delays the wave (first pressure reversal comes later)",
                   first_down(re_.time, re_.head[:, 0], h0, dh), first_down(rv.time, rv.head[:, 0], h0, dh),
                   kind="ge", ref="§5.3", unit="s"))
    c.append(Check("5.7", "Each period is weaker than the previous one (energy decays)", True,
                   bool(np.all(np.diff(env_qs) < 0) and np.all(np.diff(env_uf) < 0)), kind="bool", ref="§5.1"))
    c.append(Check("5.8", "Cavitation is flagged for a full fast closure at 2.5 bar (down-surge below vapour)",
                   True, bool(re_.meta["cavitation"]), kind="bool", ref="§5.6"))
    c.append(Check("5.9", "No cavitation for a 10 % closure (the excitation M3 should use)", False,
                   bool(full_closure("qs", 0.1)[1].meta["cavitation"]), kind="bool", ref="§5.6"))
    return c
