"""Oracles – M1 graph neural network (math note §4.2)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch

from hydropin_sim.methods import m1_gnn as m1
from hydropin_sim.methods.signatures import location_xy
from oracles.base import Check
from oracles.m1_cases import experiment
from oracles.m2_cases import FARM, localisation_error_m
from oracles.m2_pca import metrics as m2_metrics
from oracles.m2_pca import sector_of


@lru_cache(maxsize=1)
def metrics():
    E = experiment()
    F, te, pt, st, thr, g = E["F"], E["te"], E["pt"], E["st"], E["thr"], E["g"]
    leak, frac = F.leak[te], F.leak_frac[te]
    alarm = st > thr
    locs = np.array(g.locations)
    pred = locs[np.argmax(pt, axis=1)]
    true = F.leak_id[te]
    out = dict(E=E, fpr=float(alarm[~leak].mean()), pred=pred, alarm=alarm)
    # naive baseline: the location nearest to the sensor with the largest pressure drop
    sensors = list(E["X"].shape and FARM_SENSORS())
    for name, lo, hi in (("small", 0.01, 0.02), ("mid", 0.02, 0.05), ("large", 0.05, 0.3)):
        s = leak & (frac >= lo) & (frac < hi)
        sa = s & alarm
        ks = np.where(sa)[0]
        errs = np.array([localisation_error_m(true[k], pred[k], F.leak_xy[te][k]) for k in ks])
        base = []
        for k in ks:
            i = te[k]
            j = int(np.nanargmin(F.dp[i]))
            sx, sy = location_xy(FARM, sensors[j])
            base.append(float(np.hypot(sx - F.leak_xy[i][0], sy - F.leak_xy[i][1])))
        out[name] = dict(tpr=float(alarm[s].mean()), top1=float(np.mean(pred[sa] == true[sa])),
                         sector=float(np.mean([sector_of(true[k]) == sector_of(pred[k]) for k in ks])),
                         err_med=float(np.median(errs)), errs=errs, base_med=float(np.median(base)))
    return out


def FARM_SENSORS():
    from hydropin_sim.sensors.dataset import FARM_SENSORS as fs
    return fs


def checks() -> list[Check]:
    c: list[Check] = []
    M = metrics()
    c.append(Check("8.1", "False alarms on healthy test windows ≤ 3 % (threshold set for 1 % on validation)", 0.03,
                   M["fpr"], kind="le", ref="§4.2"))
    c.append(Check("8.2", "Detection rate, leaks of 1–2 %", 0.90, M["small"]["tpr"], kind="ge", ref="§4.2"))
    c.append(Check("8.3", "Detection rate, leaks ≥ 5 %", 0.95, M["large"]["tpr"], kind="ge", ref="§4.2"))
    c.append(Check("8.4", "Leaks ≥ 5 %: right sector ≥ 2 × chance (chance ≈ 1/3)", 2 / 3, M["large"]["sector"],
                   kind="ge", ref="§4.2"))
    c.append(Check("8.5", "Leaks ≥ 5 %: beats the naive 'nearest sensor with the largest drop' (median error)",
                   M["large"]["base_med"], M["large"]["err_med"], kind="le", ref="§4.2", unit="m"))
    g = M["E"]["g"]
    A = g.a_hat.numpy()
    ev = np.linalg.eigvalsh(A)
    c.append(Check("8.6", "GCN propagation matrix D^-1/2 Â D^-1/2 is symmetric with eigenvalues in [−1, 1]", True,
                   bool(np.allclose(A, A.T) and ev.max() <= 1 + 1e-6 and ev.min() >= -1 - 1e-6), kind="bool",
                   ref="§4.2"))
    # transfer learning: the λ‖θ − θ_sim‖² term keeps the fine-tuned model close to the simulation model
    E = M["E"]
    X, Y, va = E["X"], E["Y"], E["va"]
    few = va[:60]
    drift = {}
    for lam in (0.0, 1.0):
        torch.manual_seed(0)
        mdl = m1.GCN(g)
        mdl.load_state_dict(E["model"].state_dict())
        ref = {n: p.detach().clone() for n, p in mdl.named_parameters()}
        m1.train(mdl, X[few], Y[few], X[few], Y[few], epochs=30, lr=1e-3, theta_ref=ref, lam=lam)
        drift[lam] = float(sum(((p.detach() - ref[n]) ** 2).sum() for n, p in mdl.named_parameters()))
    c.append(Check("8.7", "Transfer learning: the penalty λ‖θ − θ_sim‖² keeps fine-tuning closer to θ_sim",
                   drift[0.0], drift[1.0], kind="le", ref="§4.2"))
    return c
