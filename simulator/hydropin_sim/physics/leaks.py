"""Leak outflow laws. Math note §2.5. Head h in m, area in m2, flow in m3/s."""

from __future__ import annotations

import numpy as np


def orifice(h, cd, area, g=9.81):
    """Q_L = C_d A_L sqrt(2 g h)  (WNTR form). Math note §2.5."""
    h = np.maximum(np.asarray(h, dtype=float), 0.0)
    return cd * area * np.sqrt(2.0 * g * h)


def c_l_from_orifice(cd, area, g=9.81):
    """Emitter coefficient equivalent to an orifice: C_L = C_d A_L sqrt(2g)."""
    return cd * area * np.sqrt(2.0 * g)


def emitter(h, c_l, n1):
    """Q_L = C_L h^N1  (EPANET emitter form). Math note §2.5."""
    h = np.maximum(np.asarray(h, dtype=float), 0.0)
    return c_l * h ** n1


def favad(h, cd, a0, m, g=9.81):
    """FAVAD: Q_L = C_d sqrt(2g) (A_0 h^0.5 + m h^1.5). Math note §2.5."""
    h = np.maximum(np.asarray(h, dtype=float), 0.0)
    return cd * np.sqrt(2.0 * g) * (a0 * h ** 0.5 + m * h ** 1.5)


def leak_area_for_flow(q_target, h, cd, g=9.81):
    """Inverse orifice law: the hole area giving flow q_target at head h."""
    return q_target / (cd * np.sqrt(2.0 * g * h))
