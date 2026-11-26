"""Oracles – pressure waves on the prototype board (math note §10.7)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.steady.board import M_PER_BAR, run_board_full
from hydropin_sim.transient import board as tb
from hydropin_sim.transient.board import _with_leak, run_event
from hydropin_sim.transient.moc import Options, ValveEvent, build_model, run
from oracles.base import Check
from oracles.prototype_bench import P, reference_setting

B = P.prototype


@lru_cache(maxsize=None)
def event_run(event: str, duration: float, leak: str = "", frame_dt: float = 2.5e-4):
    ref = reference_setting()
    st = _with_leak(ref, leak, 0.5e-3) if leak else ref
    nodes = ["P1", "P2", "V1a", "V1b", "TL1", "T0", "PUMP_OUT", "IN"]
    return run_event(P, st, event, duration, record=nodes, frame_dt=frame_dt)


def joukowsky_run():
    """V1 shut in 0.05 ms (much faster than any reflection), elastic pipe, no friction."""
    ref = reference_setting()
    state, spec, wn, steady = run_board_full(P, ref)
    model = build_model(spec, wn, steady, P, lumped=list(tb.VALVES))
    c = {v["id"]: v["c"] for v in model.valves}["VALVE_V1"]
    opts = Options(duration=0.0012, friction="none", record=["V1a", "V1b"], record_every=1)
    res = run(model, opts, [ValveEvent("VALVE_V1", c, 1e-4, 5e-5, e_m=1.0, closure=1.0)])
    return state, model, res


def checks() -> list[Check]:
    c: list[Check] = []
    # 1. equilibrium: with a leak open (emitter tap) and every valve lumped, nothing moves before the event
    hold = event_run("v1_pulse", 0.02, leak="L2")
    pre = hold.result.time < tb.T_EVENT
    drift = float(np.max(np.abs(hold.result.head[pre] - hold.result.head[0])))
    c.append(Check("12b.1", "Starts in equilibrium: no head drift before the event (lumped valves, leak tap, pump n = 1)",
                   0.0, drift, 1e-4, "abs", "§10.7", "m"))
    # 2. Joukowsky at V1 for a closure faster than the first reflection
    state, model, res = joukowsky_run()
    G = model.grid
    j = G.pipes.index("A4")
    a = G.a[j]
    area = model.area[j]
    v0 = state.flow["VALVE_V1"] / area
    dh_expected = a * v0 / P.water.G.v
    t = res.time
    t_ref = 1e-4 + 5e-5 + 2 * G.dt                  # closure complete
    win = (t > t_ref) & (t < 1e-4 + 0.95 * 2 * G.n_seg[j] * G.dt)
    rise = float(np.mean(res.head[win, 0] - res.head[0, 0]))
    c.append(Check("12b.2", "Joukowsky: head rise at V1 = a ΔV / g before the first reflection", dh_expected,
                   rise, 0.02, "rel", "§5.2, §10.7", "m"))
    drop = float(np.mean(res.head[win, 1] - res.head[0, 1]))
    j5 = G.pipes.index("A5")
    dh_dn = G.a[j5] * state.flow["VALVE_V1"] / model.area[j5] / P.water.G.v
    c.append(Check("12b.3", "Joukowsky downstream: head drop at V1b = a ΔV / g", -dh_dn, drop, 0.02, "rel",
                   "§5.2, §10.7", "m"))
    # 4. time of flight TL1 → P1 for a burst at L1
    burst = run_event(P, reference_setting(), "l1_burst", 0.012, record=["TL1", "P1"], frame_dt=1e-5)
    rb = burst.result
    dh = rb.head - rb.head[0]
    gb = burst.model.grid
    travel = (gb.n_seg[gb.pipes.index("A3")] + gb.n_seg[gb.pipes.index("SS_P1a")]) * gb.dt

    def first(col, thr):
        k = np.argmax(np.abs(dh[:, col]) > thr)
        return float(rb.time[k])

    thr = 1e-4
    lag = first(1, thr) - first(0, thr)
    c.append(Check("12b.4", "Wave from L1 reaches P1 after the pipe travel time (A3 + half sensor tee)", travel,
                   lag, 3 * gb.dt, "abs", "§5.1", "s"))
    # 5-6. safety and cavitation
    slam = event_run("v1_slam", 0.15)
    hmax = float(np.max(slam.result.head[:, slam.result.point_ids.index("PUMP_OUT")]
                        - B.PB_Z_PUMP.v)) / M_PER_BAR
    c.append(Check("12b.5", "V1 slammed shut in 10 ms: highest pressure stays under 90 % of 1.6 bar",
                   B.PB_SAFE_FRAC.v * B.PS_P_MAX.v, hmax, kind="le", ref="§10.3", unit="bar"))
    trip = event_run("pump_trip", 0.4, frame_dt=1e-3)
    c.append(Check("12b.6", "Pump power cut: no cavitation anywhere on the board", False,
                   bool(trip.result.meta["cavitation"]), kind="bool", ref="§5.7"))
    ip = trip.result.point_ids.index("P1")
    last = trip.result.time > trip.result.time[-1] - 0.1
    p_end = float(np.mean(trip.result.head[last, ip]) - B.PB_Z_BOARD.v - B.PB_DZ_SENSOR.v) / M_PER_BAR
    c.append(Check("12b.7", "After the pump stops, P1 settles at the static value (outlets at board level, "
                   "sensor Δz_s above the axis)", -B.PB_DZ_SENSOR.v / M_PER_BAR, p_end, 0.002, "abs", "§10.3",
                   "bar"))
    return c
