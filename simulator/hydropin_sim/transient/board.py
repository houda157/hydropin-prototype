"""Transients on the prototype board (math note §10.7).

The board's steady twin (steady/board.py) gives the initial state; the MOC solver
(transient/moc.py) then propagates pressure waves through every gridded pipe
(hose, PE pipes, stainless sensor tees, return). Hand valves are lumped valves and
open leak taps are emitters, both calibrated on the steady flow, so the run starts
in exact equilibrium.

Events (scenario definitions, not physical parameters):
  v1_slam    V1 shuts completely in T_SLAM (a fast solenoid or a hand slam)
  v1_pulse   V1 closes by PULSE_CLOSURE in T_PULSE (the small M3 pulse)
  l1_burst   L1 opens suddenly to a BURST_D orifice in T_BURST
  pump_trip  the 12 V supply is cut: pump speed falls to 0 in PB_T_SPINDOWN
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import TransientResult
from hydropin_sim.network.prototype import TAPS, BoardSetting
from hydropin_sim.steady.board import BoardState, run_board_full
from hydropin_sim.transient.moc import Options, RampEvent, ValveEvent, build_model, run

T_EVENT = 0.005          # s, event starts after 5 ms of steady flow
T_SLAM = 0.010           # s
T_PULSE = 0.005          # s
PULSE_CLOSURE = 0.10     # fraction of the valve conductance removed
T_BURST = 0.005          # s
BURST_D = 0.8e-3         # m
VALVES = ("VALVE_R1", "VALVE_R2", "VALVE_V1", "VALVE_V2")

EVENTS = {
    "v1_slam": "V1 slams shut (10 ms)",
    "v1_pulse": "M3 pulse: V1 closes by 10 % in 5 ms",
    "l1_burst": "L1 bursts open (0.8 mm hole)",
    "pump_trip": "Pump power cut",
}


@dataclass
class BoardTransient:
    event: str
    setting: BoardSetting
    state: BoardState
    result: TransientResult
    model: object


def _with_leak(setting: BoardSetting, tap: str, d: float) -> BoardSetting:
    return BoardSetting(theta=dict(setting.theta), leak_d={**setting.leak_d, tap: d},
                        v_supply=setting.v_supply, water_temp=setting.water_temp)


def run_event(P: Params, setting: BoardSetting, event: str, duration: float,
              record: Sequence[str] = (), record_points: Sequence[tuple[str, float]] = (),
              frame_dt: float = 2.5e-4, viscoelastic: bool = True, unsteady: bool = True) -> BoardTransient:
    """Run one event on the board from its steady state. Math note §10.7."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event}; choose from {list(EVENTS)}")
    state, spec, wn, steady = run_board_full(P, setting)
    taps_open = [f"TAP_{t}" for t in TAPS if f"TAP_{t}" in wn.link_name_list]
    model = build_model(spec, wn, steady, P, lumped=[v for v in VALVES if v in wn.link_name_list],
                        to_emitter=taps_open)
    events, pump_speed = [], None
    vc = {v["id"]: v["c"] for v in model.valves}
    if event == "v1_slam":
        events.append(ValveEvent("VALVE_V1", vc["VALVE_V1"], T_EVENT, T_SLAM, e_m=1.0, closure=1.0))
    elif event == "v1_pulse":
        events.append(ValveEvent("VALVE_V1", vc["VALVE_V1"], T_EVENT, T_PULSE, e_m=1.0, closure=PULSE_CLOSURE))
    elif event == "l1_burst":
        if "L1" in setting.leak_d or setting.theta.get("L1") is not None:
            raise ValueError("l1_burst needs L1 shut before the event")
        after, _, _, st_after = run_board_full(P, _with_leak(setting, "L1", BURST_D))
        i = st_after.node_ids.index("TL1")
        dh = st_after.head[0, i] - st_after.head[0, st_after.node_ids.index("OUT_L1")]
        c1 = after.q_out["L1"] / np.sqrt(dh)
        ni = model.node_ids.index("TL1")
        model.z_em[ni] = st_after.head[0, st_after.node_ids.index("OUT_L1")]
        events.append(RampEvent("TL1", 0.0, float(c1), T_EVENT, T_BURST))
    elif event == "pump_trip":
        t_sd = P.prototype.PB_T_SPINDOWN.v
        pump_speed = lambda t: 1.0 if t < T_EVENT else max(0.0, 1.0 - (t - T_EVENT) / t_sd)  # noqa: E731
    dt = model.grid.dt
    opts = Options(duration=duration, friction="quasi-steady", unsteady=unsteady, viscoelastic=viscoelastic,
                   record=list(record), record_points=list(record_points),
                   record_every=max(1, int(round(frame_dt / dt))), pump_speed=pump_speed)
    res = run(model, opts, events)
    return BoardTransient(event, setting, state, res, model)
