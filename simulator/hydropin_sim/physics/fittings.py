"""Small fittings, hand valves, DC diaphragm pump and pump ripple of the prototype board.

Math note §10.2–10.3. All loss coefficients are referred to the velocity in the
pipe that carries the fitting (D = inside diameter of that pipe), so that
h_m = K V^2 / (2 g) with V = Q / A_pipe, the convention EPANET uses for minor losses.
"""

from __future__ import annotations

import numpy as np


def bore_k(d_bore, d_pipe):
    """Sudden contraction + sudden expansion through a short narrow bore. Math note §10.2.

    K_b = [ (1 - β²)² + ½ (1 - β²) ] / β⁴,  β = d_bore / D   (Borda–Carnot + contraction)
    """
    beta = np.asarray(d_bore, dtype=float) / np.asarray(d_pipe, dtype=float)
    if np.any(beta <= 0) or np.any(beta > 1):
        raise ValueError("bore must be 0 < d_bore <= d_pipe")
    s = 1.0 - beta ** 2
    return (s ** 2 + 0.5 * s) / beta ** 4


def plug_k(theta_deg, table_theta, table_k, theta_closed):
    """Loss coefficient of a quarter-turn plug/ball valve at closing angle θ, on the valve bore
    velocity (Weisbach plug-cock table). Log-linear interpolation; beyond the last table
    point, log-linear extrapolation of the last segment up to θ_c (closed). Math note §10.2.
    """
    th = np.asarray(theta_deg, dtype=float)
    tt = np.asarray(table_theta, dtype=float)
    tk = np.asarray(table_k, dtype=float)
    if np.any(th < 0) or np.any(th >= theta_closed):
        raise ValueError(f"valve angle must be in [0, {theta_closed}) deg (closed at {theta_closed})")
    pos = tk > 0                       # the 0° point is exactly 0: handle the first segment linearly
    lt, lk = tt[pos], np.log(tk[pos])
    slope = (lk[-1] - lk[-2]) / (lt[-1] - lt[-2])
    k_log = np.exp(np.where(th <= lt[-1], np.interp(th, lt, lk), lk[-1] + slope * (th - lt[-1])))
    k_lin = np.interp(th, tt[:2], tk[:2])
    return np.where(th <= tt[1], k_lin, k_log)


def valve_k(theta_deg, d_bore, d_pipe, table_theta, table_k, theta_closed):
    """Hand valve on a pipe: K_v(θ) = K_b(β) + K_pc(θ) / β⁴ (pipe velocity). Math note §10.2."""
    beta = d_bore / d_pipe
    return bore_k(d_bore, d_pipe) + plug_k(theta_deg, table_theta, table_k, theta_closed) / beta ** 4


def diaphragm_pump(q0, h0, n, speed_ratio=1.0):
    """DC diaphragm pump curve at speed ratio s = V / V_nom. Math note §10.3.

    H(Q) = s H0 [1 - (Q / (s Q0))^n]  →  contract form H = h0' - r' Q^n with
    h0' = s H0,  r' = s H0 / (s Q0)^n.
    Returns (h0', r', n).
    """
    s = float(speed_ratio)
    if s <= 0:
        raise ValueError("speed ratio must be > 0")
    return s * h0, s * h0 / (s * q0) ** n, n


def ripple(t, amp, freq, phase=0.0):
    """Pump pressure ripple δh(t) = A sin(2π f t + φ). Math note §10.3."""
    return amp * np.sin(2 * np.pi * freq * np.asarray(t, dtype=float) + phase)
