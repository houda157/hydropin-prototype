"""Oracles – elastic MOC solver (math note §5.1, §5.5–5.7).

TSNet was planned as an independent reference (Architecture D1). It could not
be used: TSNet 0.3.1 fails under NumPy 2, and in a separate NumPy-1 environment
it mis-initialises a valve discharging to a reservoir (its own warning: 39 m
initial discrepancy) and crashes on a valve feeding a junction. It is replaced
by stronger oracles: the EXACT analytical solution (frictionless line), grid
convergence (with friction) and conservation checks.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.network.generators import demo_farm_spec
from hydropin_sim.contracts import Scenario
from hydropin_sim.steady.solver import prepare, run_steady
from hydropin_sim.transient.moc import Options, build_model, run
from oracles.base import Check
from oracles.transient_cases import (L_RPV, P, close, exact_square_wave, make_frictionless, rpv_spec,
                                     setup)

G = P.water.G.v


@lru_cache(maxsize=1)
def frictionless():
    m, _ = setup(rpv_spec(), dt_max=5e-4)
    q0 = make_frictionless(m)
    r = run(m, Options(duration=2.0, friction="none", record=["END"]), [close(m)])
    return m, q0, r


@lru_cache(maxsize=4)
def with_friction(dt_max):
    m, st = setup(rpv_spec(h_res=25.0), dt_max=dt_max)
    r = run(m, Options(duration=1.2, friction="quasi-steady", record=["END"]), [close(m, t_close=0.01)])
    return m, r


def checks() -> list[Check]:
    c: list[Check] = []
    m, q0, r = frictionless()
    a = m.grid.a[0]
    v0 = q0 / m.area[0]
    h = r.head[:, 0]
    dh = a * v0 / G
    period = 4 * L_RPV / a
    c.append(Check("4.1", "Joukowsky: first surge at the valve = a·V₀/g (instant closure, no friction)",
                   float(dh), float(h.max() - h[0]), 1e-6, "rel", "§5.7", "m"))
    ex = exact_square_wave(r.time, 0.05, h[0], dh, period)
    c.append(Check("4.2", "Whole 2 s trace = exact square-wave solution (max error / ΔH_J)",
                   1e-9, float(np.max(np.abs(h - ex)) / dh), kind="le", ref="§5.1"))
    t_down = r.time[np.argmax(h < h[0] - dh / 2)]          # first switch to the low plateau
    per = float(2 * (t_down - 0.05))
    c.append(Check("4.3", "Oscillation period = 4L/a", float(period), per, 2 * m.grid.dt / period + 1e-9,
                   "rel", "§5.7", "s"))
    late = h[r.time > 1.5].max() - h[0]
    c.append(Check("4.4", "No numerical damping (Courant = 1): surge after 1.5 s = first surge",
                   float(dh), float(late), 1e-9, "rel", "§5.5", "m"))

    errs = []
    dts = (2e-3, 1e-3, 5e-4, 2.5e-4)
    ref_m, ref = with_friction(1.25e-4)
    for d in dts:
        mm, rr = with_friction(d)
        hi = np.interp(ref.time, rr.time, rr.head[:, 0])
        errs.append(np.sqrt(np.mean((hi - ref.head[:, 0]) ** 2)))
    order = float(np.polyfit(np.log(dts), np.log(errs), 1)[0])
    c.append(Check("4.5", "Grid convergence with friction: error falls when Δt is refined (observed order)",
                   0.8, order, kind="ge", ref="§5.5"))
    jk = with_friction(2.5e-4)[1].head[:, 0]
    c.append(Check("4.6", "With friction, the line packs: surge exceeds Joukowsky, then decays",
                   True, bool(jk.max() - jk[0] > 0 and np.max(jk[-200:]) < jk.max()), kind="bool", ref="§5.7"))

    farm = demo_farm_spec()
    sc = Scenario(id="f", network="farm_demo", seed=0, open_sectors=["SECTOR1", "SECTOR3"], duration=1, timestep=1)
    wn, _, _ = prepare(farm, sc, P)
    st = run_steady(farm, sc, P, wn=wn)
    fm = build_model(farm, wn, st, P, dt_max=1e-3)
    c.append(Check("4.7", "Farm grid: wave-speed adjustment within PSI_MAX, Courant = 1 everywhere",
                   P.transient.PSI_MAX.v, fm.grid.max_adjustment, kind="le", ref="§5.5"))
    rec = ["HEAD", "S1", "B13", "S3", "B33"]
    rs = run(fm, Options(duration=3.0, record=rec))
    drift = float(np.max(np.abs(rs.head - rs.head[0])))
    c.append(Check("4.8", "No excitation → the farm (pump, junctions, 6 lateral blocks) stays steady for 3 s",
                   0.01, drift, kind="le", ref="§5.6", unit="m"))
    return c
