"""Friction head loss in pressurised pipes. Math note §2.2.

All functions are vectorised (NumPy) and use SI units. Flow sign is kept:
h_f > 0 when Q > 0 (head drops from start to end).
"""

from __future__ import annotations

import numpy as np

RE_LAMINAR = 2000.0   # below: laminar, f = 64/Re
RE_TURBULENT = 4000.0  # above: turbulent (Swamee–Jain); between: linear blend


def area(d):
    """Pipe cross-section A = pi D^2 / 4 (m2)."""
    return np.pi * np.asarray(d, dtype=float) ** 2 / 4.0


def reynolds(q, d, nu):
    """Re = |V| D / nu with V = Q / A. Math note §2.2."""
    v = np.abs(np.asarray(q, dtype=float)) / area(d)
    return v * d / nu


def f_laminar(re):
    """Hagen–Poiseuille: f = 64 / Re (laminar, Re < 2000). Math note §2.2."""
    return 64.0 / np.asarray(re, dtype=float)


def f_blasius(re):
    """Blasius smooth-pipe law: f = 0.316 Re^-0.25 (4000 < Re < 1e5). Math note §2.2."""
    return 0.316 * np.asarray(re, dtype=float) ** -0.25


def f_swamee_jain(re, eps, d):
    """Swamee–Jain explicit turbulent friction factor. Math note §2.2."""
    re = np.asarray(re, dtype=float)
    return 0.25 / np.log10(eps / (3.7 * d) + 5.74 / re ** 0.9) ** 2


def f_colebrook(re, eps, d, tol=1e-13, max_iter=100):
    """Colebrook–White (implicit), solved iteratively. Used only as a reference oracle.

    1/sqrt(f) = -2 log10( eps/(3.7 D) + 2.51 / (Re sqrt(f)) )
    """
    re = np.asarray(re, dtype=float)
    x = 1.0 / np.sqrt(f_swamee_jain(re, eps, d))  # x = 1/sqrt(f), good start
    for _ in range(max_iter):
        x_new = -2.0 * np.log10(eps / (3.7 * d) + 2.51 * x / re)
        if np.all(np.abs(x_new - x) < tol):
            x = x_new
            break
        x = x_new
    return 1.0 / x ** 2


def friction_factor(re, eps, d):
    """Darcy friction factor over all regimes. Math note §2.2.

    Re < 2000: laminar 64/Re; Re > 4000: Swamee–Jain; in between: linear blend
    in Re between the two end values (EPANET uses a cubic; the difference is
    < 2 % and this zone only occurs briefly near the end of laterals).
    """
    re = np.atleast_1d(np.asarray(re, dtype=float))
    eps = np.broadcast_to(np.asarray(eps, dtype=float), re.shape)
    d = np.broadcast_to(np.asarray(d, dtype=float), re.shape)
    f = np.empty_like(re)
    lam = re < RE_LAMINAR
    tur = re > RE_TURBULENT
    mid = ~(lam | tur)
    f[lam] = f_laminar(np.maximum(re[lam], 1e-12))
    f[tur] = f_swamee_jain(re[tur], eps[tur], d[tur])
    if mid.any():
        f0 = 64.0 / RE_LAMINAR
        f1 = f_swamee_jain(RE_TURBULENT, eps[mid], d[mid])
        w = (re[mid] - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR)
        f[mid] = (1 - w) * f0 + w * f1
    return f


def headloss_dw(q, length, d, eps, nu, g=9.81):
    """Darcy–Weisbach head loss h_f = f (L/D) V|V| / (2g), signed. Math note §2.2.

    Q = 0 gives exactly 0 (the laminar limit h_f = 32 nu L V / (g D^2) -> 0).
    """
    q = np.atleast_1d(np.asarray(q, dtype=float))
    v = q / area(d)
    re = np.abs(v) * d / nu
    out = np.zeros_like(q)
    nz = re > 0
    f = friction_factor(re[nz], eps, d)
    out[nz] = f * (length / d) * v[nz] * np.abs(v[nz]) / (2.0 * g)
    return out if out.size > 1 else float(out[0])


def headloss_hw(q, length, d, c_hw):
    """Hazen–Williams head loss (SI), signed. Math note §2.2. NOT valid for laterals."""
    q = np.asarray(q, dtype=float)
    return np.sign(q) * 10.67 * length * np.abs(q) ** 1.852 / (c_hw ** 1.852 * d ** 4.87)


def minor_loss(q, d, k_m, g=9.81):
    """Minor loss h_m = K_m V|V| / (2g), signed. Math note §2.2."""
    v = np.asarray(q, dtype=float) / area(d)
    return k_m * v * np.abs(v) / (2.0 * g)
