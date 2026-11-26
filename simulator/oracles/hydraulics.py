"""Oracles – networks and steady-state twin (math note §1, §2.1–2.6)."""

from __future__ import annotations

import os
import tempfile
import warnings
from functools import lru_cache

import numpy as np
import wntr

from hydropin_sim.config import load_params
from hydropin_sim.contracts import LeakSpec, Scenario
from hydropin_sim.network.builder import EPANET_NU_REF, FIT_RANGE, build_wntr, write_inp
from hydropin_sim.network.generators import bench_spec, demo_farm_spec
from hydropin_sim.physics import emitters as em
from hydropin_sim.physics.friction import headloss_dw, reynolds
from hydropin_sim.physics.leaks import orifice
from hydropin_sim.steady.solver import run_steady
from oracles.base import Check

P = load_params()
G = P.water.G.v
FARM = demo_farm_spec()
BENCH = bench_spec()
D_LAT, L_LAT = 0.0136, 80.0


def scenario(opens=("SECTOR1", "SECTOR3"), leaks=(), temp=None, sid="s"):
    return Scenario(id=sid, network="farm_demo", seed=0, open_sectors=list(opens),
                    duration=1, timestep=1, leaks=list(leaks), water_temp=temp)


def dripper(h):
    e = P.emitters
    return em.dripper_flow(h, e.Q_NOM.v, e.H_NOM.v, e.X_EMIT.v)


def single_pipe_wntr(q, length, d, eps, temp):
    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.headloss = "D-W"
    wn.options.hydraulic.viscosity = P.nu_w(temp) / EPANET_NU_REF
    wn.options.hydraulic.accuracy = 1e-8
    wn.options.time.duration = 0
    wn.add_reservoir("R", base_head=50.0)
    wn.add_junction("J", base_demand=q, elevation=0.0)
    wn.add_pipe("P", "R", "J", length=length, diameter=d, roughness=eps)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = wntr.sim.EpanetSimulator(wn).run_sim()
    return 50.0 - float(r.node["pressure"]["J"].iloc[0])


@lru_cache(maxsize=16)
def explicit_lateral_wntr(h_in, slope=0.0, n_e=200, s=0.4):
    """Every dripper as an EPANET node: an independent solver for the aggregation check."""
    e = P.emitters
    nu = P.nu_w()
    wn = wntr.network.WaterNetworkModel()
    o = wn.options.hydraulic
    o.headloss, o.viscosity, o.emitter_exponent, o.accuracy, o.trials = "D-W", nu / EPANET_NU_REF, 0.5, 1e-9, 500
    wn.options.time.duration = 0
    wn.add_reservoir("IN", base_head=h_in)
    prev = "IN"
    c_d = e.Q_NOM.v / e.H_NOM.v ** 0.5
    for i in range(1, n_e + 1):
        nid = f"D{i}"
        wn.add_junction(nid, base_demand=0.0, elevation=-slope * i * s)
        wn.get_node(nid).emitter_coefficient = c_d
        wn.add_pipe(f"P{i}", prev, nid, length=s, diameter=D_LAT, roughness=P.material("LDPE").EPS_R.v)
        prev = nid
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = wntr.sim.EpanetSimulator(wn).run_sim()
    return float(r.link["flowrate"]["P1"].iloc[0])


def checks() -> list[Check]:
    c: list[Check] = []
    eps = P.material("PE100").EPS_R.v
    d63 = 0.063 - 2 * 0.063 / 11
    for cid, temp in (("2.1", 20.0), ("2.2", 35.0)):
        hl_ep = single_pipe_wntr(0.002, 100.0, d63, eps, temp)
        hl_py = headloss_dw(0.002, 100.0, d63, eps, P.nu_w(temp), G)
        c.append(Check(cid, f"EPANET single-pipe head loss = our Darcy–Weisbach (HDPE Ø63, 2 L/s, {temp:.0f} °C)",
                       hl_py, hl_ep, 1e-3, "rel", "§2.2", "m"))

    r = run_steady(FARM, scenario(), P)
    ix = {n: i for i, n in enumerate(r.node_ids)}
    lx = {n: i for i, n in enumerate(r.link_ids)}
    dem = r.meta["demand"][0]
    out = sum(dem[ix[n]] for n in ix if not n.startswith(("BASIN",)))
    c.append(Check("2.3", "Mass balance: pump flow = sum of all emitter outflows (2 sectors open)",
                   float(r.pump_flow[0]), float(out), 1e-4, "rel", "§2.1", "m³/s"))
    fits = r.meta["block_fits"]
    worst = max(f.max_rel_error for f in fits.values())
    c.append(Check("2.4", f"Lateral-block emitter fit (q = C√h) vs equivalent lateral over {FIT_RANGE[0]:.0f}–{FIT_RANGE[1]:.0f} m",
                   0.02, worst, kind="le", ref="§2.4"))
    for cid, slope, txt in (("2.5", 0.0, "flat"), ("2.6", -0.003, "0.3 % uphill (demo farm)")):
        q_ep = explicit_lateral_wntr(10.0, slope)
        q_eq = em.lateral_equivalent_flow(10.0, 200, 0.4, D_LAT, P.material("LDPE").EPS_R.v,
                                          P.nu_w(), dripper, slope=slope)
        c.append(Check(cid, f"Equivalent lateral vs 200 drippers solved by EPANET (80 m Ø16, {txt})",
                       q_ep, q_eq, 0.02, "rel", "§2.4", "m³/s"))
    q_mine = em.lateral_explicit(10.0, 200, 0.4, D_LAT, P.material("LDPE").EPS_R.v, P.nu_w(), dripper).q_inlet
    c.append(Check("2.7", "Our explicit lateral (physics library) vs the same lateral solved by EPANET",
                   explicit_lateral_wntr(10.0, 0.0), q_mine, 5e-3, "rel", "§2.4", "m³/s"))

    closed = max(abs(r.flow[0, lx[f"V{k}"]]) for k in (2, 4))
    c.append(Check("2.8", "Closed sector valves carry no flow", 1e-9, float(closed), kind="le", ref="§1", unit="m³/s"))
    pu = FARM.pumps[0]
    q = float(r.pump_flow[0])
    dh = r.head[0, ix[pu.end]] - r.head[0, ix[pu.start]]
    c.append(Check("2.9", "Pump operating point lies on its curve H = h0 − rQ²",
                   pu.h0 - pu.r * q ** pu.n, float(dh), 1e-3, "rel", "§2.6", "m"))
    ok = True
    worst_dw = 0.0
    wn = r.meta["wn"]
    for p in FARM.pipes:
        qi = r.flow[0, lx[p.id]]
        if abs(qi) < 1e-7:
            continue
        h1, h2 = r.head[0, ix[p.start]], r.head[0, ix[p.end]]
        ok &= np.sign(h1 - h2) == np.sign(qi)
        re_ = reynolds(qi, p.d_int, P.nu_w())
        if re_ > 4000:
            hf = headloss_dw(qi, p.length, p.d_int, P.material(p.material).EPS_R.v, P.nu_w(), G)
            v = qi / (np.pi * p.d_int ** 2 / 4)
            hm = p.k_minor * v * abs(v) / (2 * G)
            worst_dw = max(worst_dw, abs((h1 - h2) / (hf + hm) - 1))
    c.append(Check("2.10", "Head always falls in the direction of flow (every open pipe)",
                   True, bool(ok), kind="bool", ref="§2.1"))
    c.append(Check("2.11", "Every open turbulent pipe of the farm: EPANET loss = our Darcy–Weisbach + minor",
                   0.005, float(worst_dw), kind="le", ref="§2.2"))

    rl = run_steady(BENCH, Scenario(id="b", network="bench", seed=0, open_sectors=[], duration=1, timestep=1,
                                    leaks=[LeakSpec(pipe="L2", position=0.5, area=3e-6)]), P)
    ixb = {n: i for i, n in enumerate(rl.node_ids)}
    p_leak = rl.pressure[0, ixb["LEAK0"]]
    c.append(Check("2.12", "Leak outflow = orifice law at the leak node pressure (bench, 3 mm²)",
                   float(orifice(p_leak, P.leaks.CD_LEAK.v, 3e-6, G)), float(rl.leak_flow[0]), 1e-4, "rel",
                   "§2.5", "m³/s"))

    wn0, _ = build_wntr(FARM, P)
    with tempfile.TemporaryDirectory() as tmp:
        path = write_inp(wn0, os.path.join(tmp, "farm.inp"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wn1 = wntr.network.WaterNetworkModel(str(path))
            p0 = wntr.sim.EpanetSimulator(wn0).run_sim().node["pressure"].iloc[0]
            p1 = wntr.sim.EpanetSimulator(wn1).run_sim().node["pressure"].iloc[0]
    c.append(Check("2.13", "Export to EPANET .inp and reload gives the same pressures",
                   1e-3, float(np.max(np.abs(p0 - p1[p0.index]))), kind="le", ref="–", unit="m"))
    return c
