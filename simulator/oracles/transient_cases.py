"""Reference transient set-ups shared by the pressure-wave oracles and reports."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Sequence

import numpy as np

from hydropin_sim.config import load_params
from hydropin_sim.contracts import LeakSpec, NetworkSpec, Scenario
from hydropin_sim.network.generators import PE100_63_SDR11, bench_spec
from hydropin_sim.steady.solver import prepare, run_steady
from hydropin_sim.transient.moc import Options, ValveEvent, build_model, run

P = load_params()
L_RPV = 150.0
H_RES = 50.0
Q_RPV = 0.002


def rpv_spec(length=L_RPV, h_res=H_RES, q=Q_RPV, nodes_at: Sequence[float] = ()) -> NetworkSpec:
    """Reservoir – HDPE Ø63 pipe – valve discharging to atmosphere (classic water-hammer case)."""
    d_out, sdr = PE100_63_SDR11
    xs = [0.0, *nodes_at, length]
    ids = ["R", *[f"X{int(x)}" for x in nodes_at], "END"]
    nodes = [dict(id="R", kind="source", x=0, y=0, z=0, head=h_res)]
    nodes += [dict(id=f"X{int(x)}", kind="junction", x=x, y=0, z=0) for x in nodes_at]
    nodes.append(dict(id="END", kind="flush_valve", x=length, y=0, z=0, outlet_coeff=q / np.sqrt(h_res)))
    pipes = [dict(id=f"P{i + 1}", start=ids[i], end=ids[i + 1], material="PE100", length=xs[i + 1] - xs[i],
                  d_out=d_out, e_wall=d_out / sdr) for i in range(len(ids) - 1)]
    return NetworkSpec(name="rpv", nodes=nodes, pipes=pipes)


def setup(spec: NetworkSpec, leaks: Sequence[LeakSpec] = (), dt_max: float = 1e-3, temp: Optional[float] = None,
          **kw):
    sc = Scenario(id="t", network=spec.name, seed=0, open_sectors=[], duration=1, timestep=1,
                  leaks=list(leaks), water_temp=temp)
    wn, info, leak_nodes = prepare(spec, sc, P)
    st = run_steady(spec, sc, P, wn=wn)
    model = build_model(spec, wn, st, P, dt_max=dt_max, **kw)
    return model, st


def make_frictionless(model, h_res=H_RES):
    """Exact frictionless steady state of a reservoir–pipe–valve line (for the analytical oracle)."""
    c = float(model.c_e[model.node_ids.index("END")])
    q = c * np.sqrt(h_res)
    model.h0_pts[:] = h_res
    model.q0_pts[:] = q
    model.q0[:] = q
    for k in model.meta["steady_head"]:
        model.meta["steady_head"][k] = h_res
    return q


def close(model, node="END", t_start=0.05, t_close=0.0, closure=1.0, e_m=1.5):
    c0 = float(model.c_e[model.node_ids.index(node)])
    return ValveEvent(node, c0, t_start, t_close, e_m, closure)


def exact_square_wave(t, t0, h0, dh, period):
    """Frictionless reservoir–pipe–valve, instantaneous full closure at t0: head at the valve."""
    tau = (np.asarray(t) - t0) % period
    out = np.where(tau < period / 2, h0 + dh, h0 - dh)
    return np.where(np.asarray(t) <= t0, h0, out)


@lru_cache(maxsize=8)
def bench_with_leak(x_leak: Optional[float], friction="quasi-steady", closure=1.0, duration=1.5,
                    t_close=0.0, upstream="reservoir"):
    """Bench-like line (150 m HDPE Ø63) with optional leak at x_leak; returns (time, head at END, model)."""
    spec = rpv_spec(h_res=25.0, q=0.002) if upstream == "reservoir" else bench_spec()
    leaks = []
    if x_leak is not None:
        if upstream == "reservoir":
            leaks = [LeakSpec(pipe="P1", position=x_leak / L_RPV, area=3e-6)]
        else:
            seg = {40: ("L2", 0.0), 80: ("L3", 0.0), 120: ("L4", 0.0)}
            leaks = [LeakSpec(pipe="L2", position=(x_leak - 40) / 40, area=3e-6)]
    model, st = setup(spec, leaks, dt_max=2.5e-4)
    res = run(model, Options(duration=duration, friction=friction, record=["END"]),
              [close(model, closure=closure, t_close=t_close)])
    return res.time, res.head[:, 0], model, st
