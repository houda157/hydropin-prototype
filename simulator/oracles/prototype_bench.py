"""Oracles – prototype board twin and its measurement chain (math note §10)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.optimize import brentq

from hydropin_sim.config import load_params
from hydropin_sim.network import prototype as pb
from hydropin_sim.network.prototype import BoardSetting, board_spec
from hydropin_sim.physics import fittings as ft
from hydropin_sim.physics.friction import headloss_dw, minor_loss
from hydropin_sim.physics.pump import pump_head
from hydropin_sim.sensors import board as sb
from hydropin_sim.steady.board import LPM, M_PER_BAR, end_valve_angle_for, is_safe, run_board
from oracles.base import Check

P = load_params()
B = P.prototype
R_REF = 65.0            # reference restrictor angle (deg)
P_REF = 0.8             # reference working pressure (bar)


@lru_cache(maxsize=1)
def reference_setting() -> BoardSetting:
    a = end_valve_angle_for(P, P_REF, BoardSetting(theta={"R1": R_REF, "R2": R_REF}))
    return BoardSetting(theta={"R1": R_REF, "R2": R_REF, "V1": a, "V2": a})


def _with(base: BoardSetting, **leak_d) -> BoardSetting:
    return BoardSetting(theta=dict(base.theta), leak_d=leak_d)


def series_path_oracle():
    """Single path (V2 shut, taps shut) solved by hand: pump head = elevation + Σ losses."""
    st = BoardSetting(theta={"R1": 60.0, "V1": 81.4, "R2": 0.0, "V2": None})   # laminar everywhere
    spec, _ = board_spec(P, st)
    pipes = {p.id: p for p in spec.pipes}
    nodes = {n.id: n for n in spec.nodes}
    path = ["HOSE", "FM", "A0", "A1", "VALVE_R1", "A2", "A3", "SS_P1a", "SS_P1b", "A4",
            "VALVE_V1", "A5", "A6", "RETURN"]
    nu = P.nu_w(B.PB_T_WATER.v)
    pu = spec.pumps[0]

    def loss(pid, q):
        p = pipes[pid]
        eps = P.material(p.material).EPS_R.v
        return headloss_dw(q, p.length, p.d_int, eps, nu) + minor_loss(q, p.d_int, p.k_minor)

    h_out = nodes["OUT_RET"].head

    def residual(q):
        return pump_head(q, pu.h0, pu.r, pu.n) - h_out - sum(loss(pid, q) for pid in path)

    q = brentq(residual, 1e-9, (pu.h0 / pu.r) ** (1 / pu.n) * 0.999, xtol=1e-14)
    h = pump_head(q, pu.h0, pu.r, pu.n)
    for pid in path[: path.index("SS_P1a") + 1]:
        h -= loss(pid, q)
    p_sensor = h - nodes["P1"].z - pb.sensor_dz(P)
    twin = run_board(P, st)
    return q, p_sensor, twin


def checks() -> list[Check]:
    c: list[Check] = []
    # ── fittings and pump (physics layer) ──
    c.append(Check("12.1", "Bore restriction K_b(β = 0.5) = (0.75² + 0.375)/0.5⁴", 15.0,
                   float(ft.bore_k(0.5, 1.0)), 1e-12, "rel", "§10.2"))
    c.append(Check("12.2", "No restriction when the bore equals the pipe: K_b(1) = 0", 0.0,
                   float(ft.bore_k(1.0, 1.0)), 1e-15, "abs", "§10.2"))
    k40 = float(ft.plug_k(40.0, B.K_PLUG.at, B.K_PLUG.v, B.THETA_CLOSED.v))
    c.append(Check("12.3", "Valve law returns the Weisbach table at 40°", 17.3, k40, 1e-9, "rel", "§10.2"))
    th = np.linspace(0, B.THETA_CLOSED.v - 0.01, 400)
    kk = ft.plug_k(th, B.K_PLUG.at, B.K_PLUG.v, B.THETA_CLOSED.v)
    c.append(Check("12.4", "Valve loss rises monotonically from open to shut", True,
                   bool(np.all(np.diff(kk) > 0)), kind="bool", ref="§10.2"))
    h0, r, n = ft.diaphragm_pump(B.PB_Q0_PUMP.v, B.PB_H0_PUMP.v, B.PB_N_PUMP.v, 0.8)
    c.append(Check("12.5", "Pump at 80 % voltage: shut-off head = 0.8 H0", 0.8 * B.PB_H0_PUMP.v,
                   float(pump_head(0.0, h0, r, n)), 1e-12, "rel", "§10.3", "m"))
    c.append(Check("12.6", "Pump at 80 % voltage: zero head at 0.8 Q0", 0.0,
                   float(pump_head(0.8 * B.PB_Q0_PUMP.v, h0, r, n)), 1e-9, "abs", "§10.3", "m"))
    # ── steady twin of the board ──
    q_hand, p_hand, twin = series_path_oracle()
    c.append(Check("12.7", "Single path: EPANET flow = hand-solved energy equation", q_hand * LPM,
                   twin.q_f0 * LPM, 1e-3, "rel", "§10.2, §2.1", "L/min"))
    c.append(Check("12.8", "Single path: P1 from EPANET = hand calculation", p_hand,
                   twin.p_sensor["P1"], 0.002, "abs", "§10.1–10.2", "m"))
    ref = reference_setting()
    s0 = run_board(P, ref)
    leak = run_board(P, _with(ref, L1=0.8e-3, L3=0.5e-3))
    out = sum(leak.q_out.values())
    c.append(Check("12.9", "Mass balance: pump flow = return + all taps (two leaks open)", leak.q_f0 * LPM,
                   out * LPM, 1e-6, "rel", "§2.1", "L/min"))
    # orifice leak law (L1 alone) against Q = C_d A sqrt(2 g h) with the tube losses
    one = run_board(P, _with(ref, L1=0.8e-3))
    spec, _ = board_spec(P, _with(ref, L1=0.8e-3))
    tap = next(p for p in spec.pipes if p.id == "TAP_L1")
    nodes = {n.id: n for n in spec.nodes}
    drive = one.head["TL1"] - nodes["OUT_L1"].head
    nu = P.nu_w(B.PB_T_WATER.v)
    q_law = brentq(lambda q: drive - headloss_dw(q, tap.length, tap.d_int, P.material("LDPE").EPS_R.v, nu)
                   - minor_loss(q, tap.d_int, tap.k_minor), 1e-12, 1e-3, xtol=1e-15)
    c.append(Check("12.10", "Tap with a 0.8 mm orifice follows the orifice law (§2.5)", q_law * LPM,
                   one.q_out["L1"] * LPM, 5e-3, "rel", "§10.2", "L/min"))
    z_board = {n.id: n.z for n in board_spec(P, ref)[0].nodes if n.id in pb.XY}
    c.append(Check("12.11", "Flat board: every fitting sits at z_B (no elevation between P1 and P2)",
                   B.PB_Z_BOARD.v, float(max(z_board.values())), 1e-12, "abs", "§10.1", "m"))
    c.append(Check("12.11b", "Sensor reads the pipe pressure minus its stem height Δz_s",
                   s0.pressure["P1"] - B.PB_DZ_SENSOR.v, s0.p_sensor["P1"], 1e-12, "abs", "§10.1", "m"))
    l1 = run_board(P, _with(ref, L1=0.5e-3))
    l2 = run_board(P, _with(ref, L2=0.5e-3))
    d1 = {k: l1.p_sensor[k] - s0.p_sensor[k] for k in ("P1", "P2")}
    d2 = {k: l2.p_sensor[k] - s0.p_sensor[k] for k in ("P1", "P2")}
    c.append(Check("12.12", "Design claim: a leak on branch A drops P1 more than P2", True,
                   bool(d1["P1"] < d1["P2"] < 0), kind="bool", ref="hardware list"))
    c.append(Check("12.13", "Design claim: a leak on branch B drops P2 more than P1", True,
                   bool(d2["P2"] < d2["P1"] < 0), kind="bool", ref="hardware list"))
    c.append(Check("12.14", "Reference setting stays below 90 % of the sensors' 1.6 bar", True,
                   is_safe(s0, P), kind="bool", ref="§10.3"))
    shut = B.PB_H0_PUMP.v - B.PB_Z_BOARD.v
    c.append(Check("12.15", "All outlets shut → shut-off head exceeds the safe limit (never do it)",
                   True, bool(shut > B.PB_SAFE_FRAC.v * B.PS_P_MAX.v * M_PER_BAR), kind="bool", ref="§10.3"))
    # ── pressure chain ──
    rng = np.random.default_rng(0)
    ch = sb.PressureChain("P1", "voltage", 0.0, 0.0, 1.0, B.DIV_R_TOP.v, B.DIV_R_BOT.v,
                          B.CL_R_SHUNT.v, 0.0, 0.0, 0.0)
    z = B.ADS_Z_IN.v
    r2 = B.DIV_R_BOT.v * z / (B.DIV_R_BOT.v + z)
    c.append(Check("12.16", "Divider ratio with the ADC input in parallel", r2 / (B.DIV_R_TOP.v + r2),
                   ch.divider_ratio(P), 1e-12, "rel", "§10.4"))
    lsb = 2 * B.ADS_FSR.v / 2 ** int(B.ADS_BITS.v)
    c.append(Check("12.17", "ADS1115 step at ±4.096 V = 125 µV", 1.25e-4, lsb, 1e-12, "rel", "§10.4", "V"))
    p = np.linspace(-0.9, 1.55, 2001)
    u = sb.PressureChain.span_fraction(p, P)
    ideal_v = B.PS_V_MAX.v * u / B.FW_DIV_FACTOR.v            # divider exactly 1/FW_DIV_FACTOR (1/3.0)
    p_hat = ch.firmware(np.round(ideal_v / lsb), lsb, P)
    lsb_bar = B.FW_DIV_FACTOR.v * lsb / B.PS_V_MAX.v * (B.PS_P_MAX.v - B.PS_P_MIN.v)
    c.append(Check("12.18", "Ideal chain: the firmware formula inverts the sensor to ± ½ code",
                   lsb_bar / 2 * (1 + 1e-9), float(np.max(np.abs(p_hat - p))), kind="le", ref="§10.4", unit="bar"))
    cl = sb.PressureChain("P2", "current", 0.0, 0.0, 1.0, B.DIV_R_TOP.v, B.DIV_R_BOT.v,
                          B.CL_R_SHUNT.v, 0.0, 0.0, 0.0)
    v_cl = (4e-3 + 16e-3 * u) * B.CL_R_SHUNT.v
    p_cl = cl.firmware(np.round(v_cl / lsb), lsb, P)
    lsb_cl = lsb / B.CL_R_SHUNT.v / 16e-3 * (B.PS_P_MAX.v - B.PS_P_MIN.v)
    c.append(Check("12.19", "4–20 mA version (150 Ω): firmware inverts to ± ½ code", lsb_cl / 2 * (1 + 1e-9),
                   float(np.max(np.abs(p_cl - p))), kind="le", ref="§10.4", unit="bar"))
    v_sat = ch.sensor_output(np.array([1.3]), P)[0]
    c.append(Check("12.20", "Overpressure saturates the output at 10 V × k (no wrap-around)",
                   B.PS_V_MAX.v * ch.divider_ratio(P), float(v_sat), 1e-12, "rel", "§10.4", "V"))
    # ripple: analytic boxcar + lag vs brute force on a 2 µs grid
    f, amp, tau, tc = 150.0, 0.1, B.PS_TAU.v, 1 / B.ADS_DR.v
    t_end = np.array([0.1, 0.1234, 0.2])
    dt = 2e-6
    tg = np.arange(0, 0.25, dt)
    x = amp * np.sin(2 * np.pi * f * tg + 0.7)
    y = np.empty_like(x)
    y[0] = 0.0
    a = np.exp(-dt / tau)
    for k in range(1, len(x)):
        y[k] = a * y[k - 1] + (1 - a) * x[k]
    brute = np.array([y[(tg > te - tc) & (tg <= te)].mean() for te in t_end])
    ana = sb.ripple_seen(t_end, amp, f, 0.7, tau, tc)
    c.append(Check("12.21", "Ripple after sensor lag + ADC boxcar: analytic = brute force", 0.0,
                   float(np.max(np.abs(ana - brute))), 2e-4 * amp, "abs", "§10.4", "m"))
    null = sb.ripple_seen(np.linspace(0, 1, 50), 1.0, B.ADS_DR.v, 0.3, 0.0, 1 / B.ADS_DR.v)
    c.append(Check("12.22", "Ripple at exactly DR is cancelled by the conversion (sinc zero)", 0.0,
                   float(np.max(np.abs(null))), 1e-12, "abs", "§10.4", "m"))
    # ── flow chain ──
    seg = sb.timeline(P, [(0.0, ref)])
    zero = lambda t: np.zeros_like(np.asarray(t, dtype=float))  # noqa: E731
    fm = sb.HallFlowMeter(k_dev=B.FM_K.v, f_off=B.FM_F_OFF.v, phase0=0.37)
    P0 = P.model_copy(deep=True)
    P0.prototype.FM_JITTER.value = 0.0
    rd = fm.read(seg, 2000.0, zero, P0, np.random.default_rng(1))
    f_true = fm.frequency(s0.q_f0)
    c.append(Check("12.23", "Counter: mean pulse rate = K_F Q + f_0 (long run, no jitter)", float(f_true),
                   float(rd.counts.mean() / B.FM_T_WIN.v), 1e-3, "rel", "§10.5", "Hz"))
    c.append(Check("12.24", "Counter: every window holds ⌊fT⌋ or ⌈fT⌉ pulses", True,
                   bool(np.all(np.abs(rd.counts - f_true * B.FM_T_WIN.v) < 1)), kind="bool", ref="§10.5"))
    rc = fm.read(seg, 2000.0, zero, P0, np.random.default_rng(1), k_fw=fm.k_dev, f0_fw=fm.f_off)
    c.append(Check("12.25", "Calibrated firmware: mean flow = true flow", s0.q_f0 * LPM,
                   float(rc.q_hat.mean() * LPM), 1e-3, "rel", "§10.5", "L/min"))
    ou = sb.ou_process(np.arange(0, 2e5, 1.0), 0.003, 60.0, np.random.default_rng(3))
    c.append(Check("12.26", "Supply wander: std = σ_V", 0.003, float(ou.std()), 0.06, "rel", "§10.3"))
    lag = 60
    corr = float(np.corrcoef(ou[:-lag], ou[lag:])[0, 1])
    c.append(Check("12.27", "Supply wander: correlation at lag τ_V = e⁻¹", float(np.exp(-1)), corr, 0.05,
                   "abs", "§10.3"))
    return c
