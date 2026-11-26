"""Steady-state twin: runs one Scenario on one NetworkSpec with EPANET (via WNTR).

Math note §2. Leaks are orifices (exponent 0.5) on a junction inserted at
`position` along the pipe; clogging scales a block's emitter coefficient by
(1 - c_j); roughness and elevation perturbations implement the Monte Carlo
draws of §2.9.
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import wntr
from wntr.network import LinkStatus

from hydropin_sim.config import Params
from hydropin_sim.contracts import NetworkSpec, Scenario, SteadyResult
from hydropin_sim.network.builder import BuildInfo, build_wntr
from hydropin_sim.physics.leaks import c_l_from_orifice


def leak_node_id(i: int) -> str:
    return f"LEAK{i}"


def prepare(spec: NetworkSpec, scenario: Scenario, P: Params
            ) -> tuple[wntr.network.WaterNetworkModel, BuildInfo, list[str]]:
    wn, info = build_wntr(spec, P, scenario.water_temp)
    open_set = set(scenario.open_sectors)
    known = {s.id for s in spec.sectors}
    if open_set - known:
        raise ValueError(f"unknown sectors {open_set - known}")
    valves = {v.id: v.pipe for v in spec.valves}
    for s in spec.sectors:
        link = wn.get_link(valves[s.valve])
        link.initial_status = LinkStatus.Open if s.id in open_set else LinkStatus.Closed
    for node_id, c in scenario.clogging.items():
        j = wn.get_node(node_id)
        j.emitter_coefficient = (j.emitter_coefficient or 0.0) * (1.0 - c)
    for pipe_id, f in scenario.roughness_scale.items():
        wn.get_link(pipe_id).roughness *= f
    for node_id, dz in scenario.elevation_offset.items():
        wn.get_node(node_id).elevation += dz
    leak_nodes = []
    for i, lk in enumerate(scenario.leaks):
        n1 = lk.n1 if lk.n1 is not None else P.leaks.N1_LEAK.v
        if abs(n1 - 0.5) > 1e-12:
            raise NotImplementedError("EPANET twin supports orifice leaks only (N1 = 0.5)")
        cd = lk.cd if lk.cd is not None else P.leaks.CD_LEAK.v
        nid = leak_node_id(i)
        pos = min(max(lk.position, 1e-6), 1 - 1e-6)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wn = wntr.morph.split_pipe(wn, lk.pipe, f"{lk.pipe}_L{i}", nid, split_at_point=pos)
        j = wn.get_node(nid)
        j.emitter_coefficient = (j.emitter_coefficient or 0.0) + c_l_from_orifice(cd, lk.area, P.water.G.v)
        leak_nodes.append(nid)
    wn.options.time.duration = 0 if scenario.duration <= scenario.timestep else scenario.duration
    wn.options.time.hydraulic_timestep = scenario.timestep
    wn.options.time.report_timestep = scenario.timestep
    return wn, info, leak_nodes


def run_steady(spec: NetworkSpec, scenario: Scenario, P: Params,
               wn: Optional[wntr.network.WaterNetworkModel] = None) -> SteadyResult:
    if wn is None:
        wn, info, leak_nodes = prepare(spec, scenario, P)
    else:
        info, leak_nodes = BuildInfo(), [n for n in wn.junction_name_list if n.startswith("LEAK")]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = wntr.sim.EpanetSimulator(wn).run_sim()
    nodes = list(res.node["pressure"].columns)
    links = list(res.link["flowrate"].columns)
    head = res.node["head"][nodes].to_numpy(dtype=float)
    pres = res.node["pressure"][nodes].to_numpy(dtype=float)
    flow = res.link["flowrate"][links].to_numpy(dtype=float)
    demand = res.node["demand"]
    leak_flow = demand[leak_nodes].to_numpy(dtype=float).sum(axis=1) if leak_nodes else np.zeros(len(head))
    pumps = [p.id for p in spec.pumps]
    pump_flow = flow[:, [links.index(p) for p in pumps]].sum(axis=1) if pumps else np.zeros(len(head))
    return SteadyResult(
        scenario_id=scenario.id, time=res.node["pressure"].index.to_numpy(dtype=float),
        node_ids=nodes, link_ids=links, head=head, pressure=pres, flow=flow,
        leak_flow=leak_flow, pump_flow=pump_flow,
        meta=dict(demand=demand[nodes].to_numpy(dtype=float), leak_nodes=leak_nodes, wn=wn,
                  block_fits=info.block_fits, nu=info.nu))
