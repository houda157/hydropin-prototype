"""Pump curve, energy and cost of lost water. Math note §2.6–2.7."""

from __future__ import annotations

import numpy as np


def pump_head(q, h0, r, n):
    """H_p = H0 - R_p Q^n_p (m). Math note §2.6."""
    return h0 - r * np.abs(np.asarray(q, dtype=float)) ** n


def pump_curve_from_points(q_design, h_design, h0, n=2.0):
    """R_p such that the curve passes through the design point (q, h)."""
    return (h0 - h_design) / q_design ** n


def hydraulic_power(q, h, rho, g, eta):
    """Electrical power P = rho g Q H / eta (W). Math note §2.6."""
    return rho * g * np.asarray(q, dtype=float) * h / eta


def lost_volume(q_leak, dt):
    """V_lost = sum Q_L dt (m3). Math note §2.7."""
    return float(np.sum(np.asarray(q_leak, dtype=float) * dt))


def lost_energy_kwh(v_lost, h_pump, rho, g, eta):
    """E_lost = rho g H_p V_lost / eta, in kWh. Math note §2.7."""
    return rho * g * h_pump * v_lost / eta / 3.6e6


def lost_cost(v_lost, e_lost_kwh, c_water, c_elec):
    """Cost = c_w V_lost + c_e E_lost (TND). Math note §2.7."""
    return c_water * v_lost + c_elec * e_lost_kwh
