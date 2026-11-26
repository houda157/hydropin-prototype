"""Steady state of the prototype board for one hand setting. Math note §10.1–10.3, §2.

Uses the same EPANET twin (WNTR, Darcy–Weisbach, temperature-dependent viscosity)
as the farm. Board specifics: shut valves get status Closed, and every outlet into
the bucket sits behind a check valve (the bucket cannot push water back).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import wntr

from hydropin_sim.config import Params
from hydropin_sim.contracts import SteadyResult
from hydropin_sim.network.builder import build_wntr
from hydropin_sim.network.prototype import (FLOW_PIPE, TAPS, BoardSetting, board_spec, sensor_dz)

M_PER_BAR = 10.197
LPM = 6.0e4        # (L/min) per (m3/s)


@dataclass
class BoardState:
    """What the board does in one setting (true values, before any sensor)."""
    setting: BoardSetting
    p_sensor: dict           # sensor id -> pressure head at the diaphragm (m)
    q_f0: float              # flow through the flow sensor (m3/s)
    q_out: dict              # outlet id -> flow into the bucket (m3/s): RET, L1, L2, L3
    head: dict               # node id -> hydraulic head (m)
    pressure: dict           # node id -> pressure head (m)
    flow: dict               # link id -> flow (m3/s)
    p_max: float             # highest pressure head on the board (m)

    @property
    def p_bar(self) -> dict:
        return {k: v / M_PER_BAR for k, v in self.p_sensor.items()}

    @property
    def q_leak(self) -> float:
        return float(sum(self.q_out[t] for t in TAPS))


def _outlet_pipes():
    return ["RETURN", *[f"TAP_{t}" for t in TAPS]]


def run_board(P: Params, setting: Optional[BoardSetting] = None) -> BoardState:
    """Solve the board for one setting. Math note §10."""
    return run_board_full(P, setting)[0]


def run_board_full(P: Params, setting: Optional[BoardSetting] = None):
    """Same as run_board, also returning (spec, prepared WNTR model, SteadyResult) for the
    transient solver (math note §10.7)."""
    setting = setting or BoardSetting()
    temp = setting.water_temp if setting.water_temp is not None else P.prototype.PB_T_WATER.v
    spec, closed = board_spec(P, setting)
    wn, _ = build_wntr(spec, P, temp)
    for pid in _outlet_pipes():
        if pid in wn.link_name_list:          # shut taps are not in the model at all
            wn.get_link(pid).check_valve = True
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = wntr.sim.EpanetSimulator(wn).run_sim()
    head = res.node["head"].iloc[0].to_dict()
    pres = res.node["pressure"].iloc[0].to_dict()
    flow = res.link["flowrate"].iloc[0].to_dict()
    nodes, links = list(res.node["head"].columns), list(res.link["flowrate"].columns)
    steady = SteadyResult(scenario_id="board", time=np.zeros(1), node_ids=nodes, link_ids=links,
                          head=res.node["head"].to_numpy(dtype=float)[:1],
                          pressure=res.node["pressure"].to_numpy(dtype=float)[:1],
                          flow=res.link["flowrate"].to_numpy(dtype=float)[:1],
                          leak_flow=np.zeros(1), pump_flow=np.array([flow["PUMP"]]),
                          meta=dict(nu=P.nu_w(temp)))
    for pid in closed:                        # removed links carry no flow
        flow.setdefault(pid, 0.0)
    dz = sensor_dz(P)
    p_sensor = {s: float(pres[s] - dz) for s in ("P1", "P2")}
    q_out = {"RET": float(flow["RETURN"]), **{t: float(flow[f"TAP_{t}"]) for t in TAPS}}
    junctions = [n for n in wn.junction_name_list]
    state = BoardState(setting=setting, p_sensor=p_sensor, q_f0=float(flow[FLOW_PIPE]), q_out=q_out,
                       head={k: float(v) for k, v in head.items()},
                       pressure={k: float(v) for k, v in pres.items()},
                       flow={k: float(v) for k, v in flow.items()},
                       p_max=float(max(pres[j] for j in junctions)))
    return state, spec, wn, steady


def is_safe(state: BoardState, P: Params) -> bool:
    """Highest pressure on the board stays below φ_s × p_max of the sensors. Math note §10.6."""
    b = P.prototype
    return state.p_max <= b.PB_SAFE_FRAC.v * b.PS_P_MAX.v * M_PER_BAR


def end_valve_angle_for(P: Params, target_bar: float, base: Optional[BoardSetting] = None,
                        valves=("V1", "V2")) -> float:
    """Same closing angle on V1 and V2 that puts the mean of P1 and P2 at target_bar
    (bisection; the pressure rises monotonically as the end valves close)."""
    base = base or BoardSetting(theta={"R1": 45.0, "R2": 45.0})
    hi_lim = P.prototype.THETA_CLOSED.v - 0.5

    def p_mean(a):
        th = dict(base.theta)
        th.update({v: a for v in valves})
        s = run_board(P, BoardSetting(theta=th, v_supply=base.v_supply, water_temp=base.water_temp))
        return float(np.mean(list(s.p_bar.values())))

    lo, hi = 0.0, hi_lim
    if p_mean(lo) > target_bar or p_mean(hi) < target_bar:
        raise ValueError(f"{target_bar} bar is out of reach with the end valves alone")
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if p_mean(mid) < target_bar:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
