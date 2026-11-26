"""Drippers and drip laterals. Math note §2.3–2.4.

Units: head h in m, flow in m3/s, lengths in m. A lateral of n_e drippers has
its first dripper at distance s from the inlet and its last one at its end
(L = n_e * s).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from hydropin_sim.physics.friction import headloss_dw

X_BELOW_ACTIVATION = 0.5  # PC dripper below h_act behaves like an orifice (math note §2.3)


def k_d_from_nominal(q_nom, h_nom, x):
    """K_D = Q_NOM / H_NOM**X_EMIT. Math note §0.3 and §2.3."""
    return q_nom / h_nom ** x


def dripper_flow(h, q_nom, h_nom, x, pc=False, h_act=None, h_max=None):
    """Flow of one dripper at pressure head h. Math note §2.3.

    Non-compensating: q = q_nom (h/h_nom)^x  (= k_d h^x).
    Pressure-compensating: q = q_nom for h_act <= h <= h_max,
    q = q_nom (h/h_act)^0.5 below h_act and q_nom (h/h_max)^0.5 above h_max
    (continuous at both ends). Negative heads give zero flow.
    """
    h = np.maximum(np.asarray(h, dtype=float), 0.0)
    if not pc:
        return q_nom * (h / h_nom) ** x
    if h_act is None or h_max is None:
        raise ValueError("pressure-compensating dripper needs h_act and h_max")
    q = np.full_like(h, q_nom)
    lo = h < h_act
    hi = h > h_max
    q[lo] = q_nom * (h[lo] / h_act) ** X_BELOW_ACTIVATION
    q[hi] = q_nom * (h[hi] / h_max) ** X_BELOW_ACTIVATION
    return q


def christiansen_F(n, m):
    """Christiansen factor for n equally spaced outlets (first at full spacing).

    F = 1/(m+1) + 1/(2n) + sqrt(m-1)/(6 n^2). Math note §2.4.
    """
    n = np.asarray(n, dtype=float)
    return 1.0 / (m + 1.0) + 1.0 / (2.0 * n) + np.sqrt(m - 1.0) / (6.0 * n ** 2)


def christiansen_exact(n, m):
    """Exact sum the Christiansen formula approximates: F = sum_{i=1..n} i^m / n^(m+1)."""
    i = np.arange(1, int(n) + 1, dtype=float)
    return float(np.sum(i ** m) / n ** (m + 1))


@dataclass
class LateralProfile:
    x: np.ndarray        # position of inlet (0) and each dripper (m)
    head: np.ndarray     # pressure head at those points (m)
    q_dripper: np.ndarray  # flow of each dripper (m3/s), len n_e
    q_inlet: float       # total inflow (m3/s)


def lateral_explicit(h_in, n_e, s, d, eps, nu, dripper, slope=0.0, g=9.81):
    """Every dripper modelled: shooting on the end pressure. Reference for §2.4.

    dripper : callable h -> q for one dripper
    slope   : Δz/L, positive downhill (z decreases along the lateral)
    Head loss between drippers: Darcy–Weisbach on the segment flow.
    """
    def march(h_end):
        heads = np.empty(n_e + 1)
        q = np.empty(n_e)
        heads[n_e] = h_end
        q_seg = 0.0
        for i in range(n_e, 0, -1):
            q[i - 1] = float(dripper(heads[i]))
            q_seg += q[i - 1]
            hf = headloss_dw(q_seg, s, d, eps, nu, g)
            # H_{i-1} = H_i + hf ; z_{i-1} - z_i = slope * s
            heads[i - 1] = heads[i] + hf - slope * s
        return heads, q

    def mismatch(h_end):
        return march(h_end)[0][0] - h_in

    lo, hi = 1e-9, h_in + abs(slope) * n_e * s + 1.0
    h_end = brentq(mismatch, lo, hi, xtol=1e-10)
    heads, q = march(h_end)
    x = np.arange(n_e + 1) * s
    return LateralProfile(x=x, head=heads, q_dripper=q, q_inlet=float(q.sum()))


def lateral_mean_head(h_in, hf_lat, dz_lat):
    """Average pressure head along a lateral: h_in - 3/4 h_f,lat + 1/2 Δz. Math note §2.4."""
    return h_in - 0.75 * hf_lat + 0.5 * dz_lat


def lateral_equivalent_flow(h_in, n_e, s, d, eps, nu, dripper, slope=0.0, m=1.75, g=9.81):
    """Inflow of a lateral reduced to one equivalent emitter. Math note §2.4.

    Solves Q = n_e * q(h_bar(Q)) with h_bar = h_in - 3/4 F h_f(Q, L) + 1/2 Δz.
    m = 1.75 (Blasius, smooth plastic) is the default friction exponent for F.
    """
    length = n_e * s
    F = christiansen_F(n_e, m)
    dz = slope * length

    def residual(q):
        hf = F * headloss_dw(q, length, d, eps, nu, g)
        hbar = lateral_mean_head(h_in, hf, dz)
        return q - n_e * float(dripper(hbar))

    q_hi = n_e * float(dripper(h_in + abs(dz))) * 1.5 + 1e-12
    return brentq(residual, 0.0, q_hi, xtol=1e-14)
