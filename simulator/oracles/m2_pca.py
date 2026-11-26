"""Oracles – M2 PCA/SVD detection and localisation (math note §4.1)."""

from __future__ import annotations

import numpy as np

from hydropin_sim.methods import m2_pca as m2
from oracles.base import Check
from oracles.m2_cases import FARM, experiment, localisation_error_m


def sector_of(name: str) -> str:
    for s in FARM.sectors:
        k = s.id[-1]
        if name in s.lateral_blocks or name in {f"SUB{k}1", f"SUB{k}2", f"SUB{k}3", f"V{k}"}:
            return s.id
    return "MAIN"


def metrics():
    E = experiment()
    F, idx, ratio, best = E["F"], E["idx"], E["ratio"], E["best"]
    leak, frac = F.leak[idx], F.leak_frac[idx]
    alarm = ratio > 1
    true = F.leak_id[idx]
    out = dict(E=E, fpr=float(alarm[~leak].mean()), n_healthy=int((~leak).sum()))
    for name, lo, hi in (("small", 0.01, 0.02), ("mid", 0.02, 0.05), ("large", 0.05, 0.3)):
        s = leak & (frac >= lo) & (frac < hi)
        sa = s & alarm
        errs = np.array([localisation_error_m(true[k], best[k], F.leak_xy[idx][k]) for k in np.where(sa)[0]])
        out[name] = dict(tpr=float(alarm[s].mean()), n=int(s.sum()),
                         top1=float(np.mean(best[sa] == true[sa])),
                         sector=float(np.mean([sector_of(true[k]) == sector_of(best[k]) for k in np.where(sa)[0]])),
                         err_med=float(np.nanmedian(errs)), err_p90=float(np.nanpercentile(errs, 90)), errs=errs)
    return out


def checks() -> list[Check]:
    c: list[Check] = []
    M = metrics()
    c.append(Check("7.1", f"False alarms on {M['n_healthy']} healthy test windows ≤ 3 % (design: 1 %)", 0.03,
                   M["fpr"], kind="le", ref="§4.1"))
    c.append(Check("7.2", "Detection rate, leaks of 1–2 % of the flow", 0.90, M["small"]["tpr"], kind="ge", ref="§4.1"))
    c.append(Check("7.3", "Detection rate, leaks of 2–5 %", 0.95, M["mid"]["tpr"], kind="ge", ref="§4.1"))
    c.append(Check("7.4", "Detection rate, leaks ≥ 5 %", 0.95, M["large"]["tpr"], kind="ge", ref="§4.1"))
    c.append(Check("7.5", "Leaks ≥ 5 %: the right sector (or main) is found", 0.90, M["large"]["sector"], kind="ge",
                   ref="§4.1"))
    c.append(Check("7.6", "Leaks ≥ 5 %: median localisation error ≤ 10 m", 10.0, M["large"]["err_med"], kind="le",
                   ref="§4.1", unit="m"))
    worst_orth, worst_ortho_res = 0.0, 0.0
    self_ok = []
    for mdl, X in M["E"]["models"].values():
        V = mdl.V
        if V.shape[1]:
            worst_orth = max(worst_orth, float(np.max(np.abs(V.T @ V - np.eye(V.shape[1])))))
            r = mdl.residual(np.random.default_rng(0).normal(size=(5, V.shape[0])))
            worst_ortho_res = max(worst_ortho_res, float(np.max(np.abs(r @ V))))
        S = mdl.signatures
        for j, name in enumerate(mdl.locations):
            raw = (S[j] + 0.0)                     # already standardised + projected
            r = raw
            cos = S @ r / (np.linalg.norm(S, axis=1) * np.linalg.norm(r) + 1e-300)
            self_ok.append(np.argmax(cos) == j or np.isclose(cos.max(), cos[j]))
    c.append(Check("7.7", "SVD algebra: VᵀV = I and the residual is orthogonal to the normal subspace", 1e-10,
                   max(worst_orth, worst_ortho_res), kind="le", ref="§4.1"))
    c.append(Check("7.8", "Each noise-free twin signature is recognised as itself (or an exact twin of itself)", True,
                   bool(np.all(self_ok)), kind="bool", ref="§4.1"))
    return c
