"""Oracles – M3 transient time-reversal localisation (math note §5.8–5.9).

'Measurements' come from our MOC solver with unsteady friction (and creep when
stated), read by the high-rate sensor model (1 ms lag, GPS offset, noise of the
averaged test σ_HF/√N_p). The M3 model is the linear frequency-domain model of
§5.8: a different, simpler physics than the one that produced the data.
"""

from __future__ import annotations

import numpy as np

from hydropin_sim.physics.waves import resolution
from oracles.base import Check
from oracles.m3_cases import T_CLOSE, experiment, simulate
from oracles.transient_cases import P

POSITIONS = (10.0, 30.0, 80.0, 120.0, 140.0)


def checks() -> list[Check]:
    c: list[Check] = []
    kappa = P.decision.KAPPA.v
    res80, st80, lm80, _ = experiment(80.0)
    dx_res = float(resolution(lm80.a, T_CLOSE))
    for i, x in enumerate(POSITIONS):
        res, st, lm, _ = experiment(x)
        c.append(Check(f"6.{i + 1}", f"Leak at {x:.0f} m (≈ 2 % of the flow) located within Δx_res = a·T_c/2",
                       x, res.x_hat, dx_res, "abs", "§5.9", "m"))
    worst_leak = min(experiment(x, seed=s)[0].snr for x in POSITIONS for s in (0, 1))
    best_healthy = max(experiment(None, seed=s)[0].snr for s in (0, 1, 2))
    c.append(Check("6.6", f"Every leak is detected: weakest leak SNR > κ = {kappa:.0f}", kappa, float(worst_leak),
                   kind="ge", ref="§5.9"))
    c.append(Check("6.7", f"No false alarm on a healthy line: strongest healthy SNR < κ = {kappa:.0f}", kappa,
                   float(best_healthy), kind="le", ref="§5.9"))
    r, st, m, ev = simulate(80.0)
    c.append(Check("6.8", "Wave speed identified from the data (a_id) = solver's wave speed",
                   float(m.grid.a[0]), float(res80.a_id), 0.005, "rel", "§5.9", "m/s"))
    six = {n: i for i, n in enumerate(st80.node_ids)}
    y_true = st80.leak_flow[0] / (2 * st80.pressure[0, six["LEAK0"]])
    c.append(Check("6.9", "Leak size (admittance Y_L) estimated within 30 %", float(y_true), float(res80.y_hat),
                   0.30, "rel", "§5.9", "m²/s"))
    rv = experiment(80.0, viscoelastic=True)[0]
    c.append(Check("6.10", "Viscoelastic (PE creep) line: leak at 80 m still located within Δx_res",
                   80.0, rv.x_hat, dx_res, "abs", "§5.3, §5.9"))
    return c
