"""Wave speed and transient quick formulas. Math note §5.2 and §5.7."""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np

from hydropin_sim.config import Params

Anchoring = Literal["upstream", "throughout", "free", "thick_throughout"]


def c1_factor(anchoring: Anchoring, nu_p: float, d: Optional[float] = None,
              e: Optional[float] = None) -> float:
    """Pipe anchoring factor c_1. Math note §5.2.

    upstream   : 1 - nu_p/2   (thin wall, anchored at the upstream end only)
    throughout : 1 - nu_p^2   (thin wall, anchored against axial movement)
    free       : 1            (expansion joints / free to move)
    thick_throughout : 2e/D (1+nu_p) + D (1-nu_p^2)/(D+e)   (thick wall, anchored)
    """
    if anchoring == "upstream":
        return 1.0 - nu_p / 2.0
    if anchoring == "throughout":
        return 1.0 - nu_p ** 2
    if anchoring == "free":
        return 1.0
    if anchoring == "thick_throughout":
        if d is None or e is None:
            raise ValueError("thick-wall c1 needs D and e")
        return 2.0 * e / d * (1.0 + nu_p) + d * (1.0 - nu_p ** 2) / (d + e)
    raise ValueError(f"unknown anchoring '{anchoring}'")


def wave_speed(k, rho, d, e, young, c1):
    """a = sqrt( (K/rho) / (1 + c1 K D / (E e)) ). Math note §5.2."""
    return np.sqrt((k / rho) / (1.0 + c1 * k * np.asarray(d) / (young * np.asarray(e))))


def wave_speed_air(a, alpha_g, p_abs, rho):
    """Effective wave speed with free air: a / sqrt(1 + alpha_g rho a^2 / p_abs). Math note §5.2."""
    return a / np.sqrt(1.0 + alpha_g * rho * np.asarray(a) ** 2 / p_abs)


def pipe_wave_speed(P: Params, material: str, d_int: float, e_wall: float,
                    anchoring: Anchoring = "free", alpha_g: Optional[float] = None,
                    h_gauge: float = 20.0) -> float:
    """Wave speed of a real pipe from params.yaml (material E, nu_p; water K, rho; air).

    h_gauge is the operating pressure head (m), used only for the air correction.
    """
    mat = P.material(material)
    c1 = (P.pipes.C1.v if anchoring == "free" else
          c1_factor(anchoring, mat.NU_P.v, d_int, e_wall))
    a = float(wave_speed(P.water.K_W.v, P.water.RHO_W.v, d_int, e_wall, mat.E_PIPE.v, c1))
    alpha = P.transient.ALPHA_AIR.v if alpha_g is None else alpha_g
    if alpha > 0:
        p_abs = P.water.P_ATM.v + P.water.RHO_W.v * P.water.G.v * h_gauge
        a = float(wave_speed_air(a, alpha, p_abs, P.water.RHO_W.v))
    return a


def joukowsky(a, dv, g=9.81):
    """ΔH = -(a/g) ΔV (instantaneous velocity change). Math note §5.7."""
    return -a * np.asarray(dv) / g


def period(length, a):
    """Oscillation period of a source–pipe–valve system: T = 4L/a. Math note §5.7."""
    return 4.0 * length / a


def char_impedance(a, d, g=9.81):
    """B = a / (g A). Math note §5.5."""
    return a / (g * np.pi * d ** 2 / 4.0)


def leak_admittance(q_l0, h_l0):
    """Small-signal leak admittance Y_L = Q_L0 / (2 h_L0) = dQ_L/dh. Math note §5.7."""
    return q_l0 / (2.0 * h_l0)


def leak_reflection(b, y_l):
    """Reflection coefficient of a leak: r_L = -B Y_L / (2 + B Y_L). Math note §5.7."""
    by = b * np.asarray(y_l)
    return -by / (2.0 + by)


def leak_position(a, t_l):
    """x_L = a t_L / 2. Math note §5.7."""
    return a * np.asarray(t_l) / 2.0


def resolution(a, t_close):
    """Best localisation resolution Δx_res ≈ a T_c / 2. Math note §5.7."""
    return a * np.asarray(t_close) / 2.0


def sample_spacing(a, fs):
    """Distance travelled by the wave between two samples: a / f_s. Math note §5.7."""
    return a / fs


def cavitation_head(p_vap, p_atm, rho, g=9.81):
    """Gauge pressure head below which the liquid column can separate (m). Math note §5.6."""
    return (p_vap - p_atm) / (rho * g)
