"""Digital twin of the 3rd-phase prototype board (hardware list and sketch of 18 Nov 2026).

Math note §10.1–10.2. Layout (board seen from the front, origin at its bottom-left
corner, x to the right, y up, metres; positions read off the sketch):

    bucket ─ R365 pump ─ soft hose ─ reducer ─ F0 flow sensor ─ T0 tee
        T0 ─ elbow E1 ─ R1 ─ tee L1 ─ Swagelok tee P1 ─ V1 ─ elbow E3 ─┐
        T0 ─ elbow E2 ─ R2 ─ tee L2 ─ Swagelok tee P2 ─ tee L3 ─ V2 ───┴─ T1 ─ return ─ bucket
        L1, L2, L3: ½" tap valve + 20–30 cm tube back to the bucket (the "hidden leaks")

Every fitting is a node; every valve is a short pipe whose minor-loss coefficient
depends on its closing angle θ (0° = open, ≥ THETA_CLOSED = shut). Outlets into
the bucket are fixed-head nodes (free jet, pressure 0) behind a check valve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import NetworkSpec
from hydropin_sim.physics import fittings as ft

VALVES = ("R1", "R2", "V1", "V2")
TAPS = ("L1", "L2", "L3")
SENSORS = {"P1": "P1", "P2": "P2"}          # sensor id -> node at the pipe axis
FLOW_PIPE = "FM"                              # pipe carrying the flow sensor F0
OUTLETS = ("OUT_RET", "OUT_L1", "OUT_L2", "OUT_L3")

# x, y (m) of the fittings on the 60 × 40 cm board, read off the 18 Nov sketch
XY = {
    "IN": (0.098, 0.170), "T0": (0.254, 0.170),
    "E1": (0.254, 0.246), "R1": (0.310, 0.246), "TL1": (0.375, 0.246), "P1": (0.449, 0.246),
    "V1": (0.532, 0.246), "E3": (0.589, 0.246),
    "E2": (0.254, 0.092), "R2": (0.310, 0.092), "TL2": (0.375, 0.092), "P2": (0.449, 0.092),
    "TL3": (0.513, 0.092), "V2": (0.555, 0.092), "T1": (0.589, 0.092),
}
VALVE_LEN = 0.03          # m, body of a mini valve


@dataclass
class BoardSetting:
    """What the team sets by hand on the board. Angles in degrees, 0 = fully open.
    A valve at or beyond THETA_CLOSED (or None) is shut. ``leak_d`` puts a calibrated
    orifice of diameter d (m) at the end of a tap tube (tap valve then fully open
    unless an angle is given): a reproducible leak instead of a cracked-open valve."""
    theta: dict = field(default_factory=dict)
    leak_d: dict = field(default_factory=dict)
    v_supply: Optional[float] = None       # V, default PB_V_SUPPLY
    water_temp: Optional[float] = None     # degC, default PB_T_WATER

    def angle(self, vid: str) -> Optional[float]:
        a = self.theta.get(vid, None if vid in TAPS else 0.0)
        return a

    def is_closed(self, vid: str, P: Params) -> bool:
        if vid in self.leak_d and vid not in self.theta:
            return False
        a = self.angle(vid)
        return a is None or a >= P.prototype.THETA_CLOSED.v


def board_z(y, P: Params) -> float:
    """Elevation above the bucket water surface: z = z_B + y sin θ_B. Math note §10.1."""
    b = P.prototype
    return float(b.PB_Z_BOARD.v + y * np.sin(np.radians(b.PB_TILT.v)))


def sensor_dz(P: Params) -> float:
    """Height of a sensor diaphragm above its pipe axis: the transducers point straight up
    whatever the board's tilt, so Δz_s is vertical. Math note §10.1."""
    return float(P.prototype.PB_DZ_SENSOR.v)


def pe_d_int(P: Params) -> float:
    b = P.prototype
    return b.PB_D_OUT_PE.v - 2 * b.PB_E_WALL_PE.v


def valve_coefficient(vid: str, theta: float, P: Params) -> float:
    """Minor loss of a board valve at angle θ (pipe velocity). Math note §10.2."""
    b = P.prototype
    d = pe_d_int(P)
    bore = b.PB_D_TAP.v if vid in TAPS else b.PB_D_VALVE.v
    return float(ft.valve_k(theta, min(bore, d), d, b.K_PLUG.at, b.K_PLUG.v, b.THETA_CLOSED.v))


def orifice_k(d_orifice: float, P: Params) -> float:
    """Orifice of diameter d at a tube end (free jet), on the tube velocity:
    K_or = (A_pipe / (C_d A_or))², i.e. Q = C_d A_or √(2 g h) as in §2.5. Math note §10.2."""
    d = pe_d_int(P)
    if not 0 < d_orifice <= d:
        raise ValueError("orifice must be smaller than the tube")
    return float((d ** 2 / (P.leaks.CD_LEAK.v * d_orifice ** 2)) ** 2)


def _prune(nodes, pipes, closed):
    """A shut valve is removed from the model (no flow at all), and so is any part of the
    board it cuts off from the pump. EPANET's 'Closed' status keeps a tiny leakage
    conductance, which would break exact mass balance (bench-twin oracle 9)."""
    pipes = [p for p in pipes if p["id"] not in closed]
    adj = {n["id"]: set() for n in nodes}
    for p in pipes:
        adj[p["start"]].add(p["end"])
        adj[p["end"]].add(p["start"])
    adj["BUCKET"].add("PUMP_OUT")
    seen, todo = set(), ["BUCKET"]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(adj[n] - seen)
    for s in SENSORS.values():
        if s not in seen:
            raise ValueError(f"sensor {s} is cut off from the pump by shut valves")
    nodes = [n for n in nodes if n["id"] in seen]
    pipes = [p for p in pipes if p["start"] in seen and p["end"] in seen]
    return nodes, pipes


def _pe(pid, a, c, length, k, P):
    b = P.prototype
    return dict(id=pid, start=a, end=c, material="LDPE", length=float(max(length, 0.005)),
                d_out=b.PB_D_OUT_PE.v, e_wall=b.PB_E_WALL_PE.v, k_minor=float(k))


def board_spec(P: Params, setting: Optional[BoardSetting] = None) -> tuple[NetworkSpec, list[str]]:
    """NetworkSpec of the board for one setting, plus the list of links that are shut.
    Math note §10.1–10.3."""
    setting = setting or BoardSetting()
    b = P.prototype
    D = pe_d_int(P)
    kb = float(ft.bore_k(b.PB_D_BARB.v, D))                 # every barbed fitting
    k_run, k_branch, k_elbow = b.K_TEE_RUN.v + kb, b.K_TEE_BRANCH.v + kb, b.K_ELBOW.v + kb
    full = bool(round(b.PB_RETURN_FULL.v))
    sin_t = np.sin(np.radians(b.PB_TILT.v))

    nodes = [dict(id="BUCKET", kind="source", x=-0.30, y=-0.30, z=0.0, head=0.0),
             dict(id="PUMP_OUT", kind="junction", x=-0.20, y=-0.20, z=b.PB_Z_PUMP.v)]
    for nid, (x, y) in XY.items():
        if nid in VALVES:            # a valve is two nodes (its body ends), added below
            continue
        nodes.append(dict(id=nid, kind="junction", x=x, y=y, z=board_z(y, P)))
    # valve bodies (two nodes each) and Swagelok tee ends
    pipes, closed = [], []
    for v in VALVES:
        x, y = XY[v]
        nodes += [dict(id=f"{v}a", kind="junction", x=x - VALVE_LEN / 2, y=y, z=board_z(y, P)),
                  dict(id=f"{v}b", kind="junction", x=x + VALVE_LEN / 2, y=y, z=board_z(y, P))]
        if setting.is_closed(v, P):
            closed.append(f"VALVE_{v}")
            k = valve_coefficient(v, 0.0, P)
        else:
            k = valve_coefficient(v, setting.angle(v), P)
        pipes.append(_pe(f"VALVE_{v}", f"{v}a", f"{v}b", VALVE_LEN, k, P))
    for s in ("P1", "P2"):
        x, y = XY[s]
        nodes += [dict(id=f"{s}a", kind="junction", x=x - b.PB_L_SS.v / 2, y=y, z=board_z(y, P)),
                  dict(id=f"{s}b", kind="junction", x=x + b.PB_L_SS.v / 2, y=y, z=board_z(y, P))]
        beta2 = (b.PB_D_SS.v / D) ** 2
        d_out_ss = b.PB_D_SS.v + 0.002
        ss = dict(material="SS316", length=b.PB_L_SS.v / 2, d_out=d_out_ss, e_wall=0.001)
        pipes.append(dict(id=f"SS_{s}a", start=f"{s}a", end=s, k_minor=0.5 * (1 - beta2), **ss))
        pipes.append(dict(id=f"SS_{s}b", start=s, end=f"{s}b",
                          k_minor=b.K_TEE_RUN.v + (1 - beta2) ** 2, **ss))

    def L(a, c):
        (xa, ya), (xc, yc) = _xy(a), _xy(c)
        return abs(xc - xa) + abs(yc - ya)

    def _xy(n):
        for nd in nodes:
            if nd["id"] == n:
                return nd["x"], nd["y"]
        raise KeyError(n)

    # pump hose and inlet
    d_h = b.PB_D_HOSE.v
    pipes.append(dict(id="HOSE", start="PUMP_OUT", end="IN", material="PVC_FLEX", length=b.PB_L_HOSE.v,
                      d_out=d_h + 0.002, e_wall=0.001, k_minor=(1 - (d_h / D) ** 2) ** 2))
    pipes.append(_pe(FLOW_PIPE, "IN", "T0", L("IN", "T0"), b.K_FLOWMETER.v, P))
    # branch A (top)
    pipes += [_pe("A0", "T0", "E1", L("T0", "E1"), k_branch + k_elbow, P),
              _pe("A1", "E1", "R1a", L("E1", "R1a"), 0.0, P),
              _pe("A2", "R1b", "TL1", L("R1b", "TL1"), k_run, P),
              _pe("A3", "TL1", "P1a", L("TL1", "P1a"), 0.0, P),
              _pe("A4", "P1b", "V1a", L("P1b", "V1a"), 0.0, P),
              _pe("A5", "V1b", "E3", L("V1b", "E3"), k_elbow, P),
              _pe("A6", "E3", "T1", L("E3", "T1"), k_run, P)]
    # branch B (bottom)
    pipes += [_pe("B0", "T0", "E2", L("T0", "E2"), k_branch + k_elbow, P),
              _pe("B1", "E2", "R2a", L("E2", "R2a"), 0.0, P),
              _pe("B2", "R2b", "TL2", L("R2b", "TL2"), k_run, P),
              _pe("B3", "TL2", "P2a", L("TL2", "P2a"), 0.0, P),
              _pe("B4", "P2b", "TL3", L("P2b", "TL3"), k_run, P),
              _pe("B5", "TL3", "V2a", L("TL3", "V2a"), 0.0, P),
              _pe("B6", "V2b", "T1", L("V2b", "T1"), k_branch, P)]
    # return to the bucket
    z_t1 = board_z(XY["T1"][1], P)
    if full:
        nodes.append(dict(id="OUT_RET", kind="source", x=0.65, y=-0.30, z=0.0, head=0.0))
        pipes.append(_pe("RETURN", "T1", "OUT_RET", b.PB_L_RETURN.v, k_elbow + b.K_EXIT.v, P))
    else:
        nodes.append(dict(id="OUT_RET", kind="source", x=0.65, y=XY["T1"][1], z=z_t1, head=z_t1))
        pipes.append(_pe("RETURN", "T1", "OUT_RET", 0.05, b.K_EXIT.v, P))
    # leak taps
    for t in TAPS:
        tee = f"T{t}"
        x, y = XY[tee]
        z_tee = board_z(y, P)
        z_out = z_tee - (b.PB_L_TAP.v * sin_t if full else 0.0)
        nodes.append(dict(id=f"OUT_{t}", kind="source", x=x, y=y - b.PB_L_TAP.v, z=z_out, head=z_out))
        if setting.is_closed(t, P):
            closed.append(f"TAP_{t}")
            k = valve_coefficient(t, 0.0, P)
        else:
            k = valve_coefficient(t, setting.angle(t) or 0.0, P)
        k_end = (orifice_k(setting.leak_d[t], P) if t in setting.leak_d else b.K_EXIT.v)
        pipes.append(_pe(f"TAP_{t}", tee, f"OUT_{t}", b.PB_L_TAP.v, b.K_TEE_BRANCH.v + k + k_end, P))

    s = (setting.v_supply if setting.v_supply is not None else b.PB_V_SUPPLY.v) / b.PB_V_NOM.v
    h0, r, n = ft.diaphragm_pump(b.PB_Q0_PUMP.v, b.PB_H0_PUMP.v, b.PB_N_PUMP.v, s)
    pump = dict(id="PUMP", start="BUCKET", end="PUMP_OUT", h0=h0, r=r, n=n)
    nodes, pipes = _prune(nodes, pipes, closed)
    spec = NetworkSpec(name="prototype_board",
                       description="3rd-phase prototype board: R365 pump, F0, two branches, P1/P2, taps L1–L3",
                       nodes=nodes, pipes=pipes, pumps=[pump])
    return spec, closed
