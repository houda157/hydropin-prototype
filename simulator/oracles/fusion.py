"""Oracles – fusion and decision (math note §6)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.contracts import MethodOutput
from hydropin_sim.fusion import decision as fu
from oracles.base import Check
from oracles.fusion_cases import experiment
from oracles.m2_pca import sector_of


def auc(score, y):
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    pos = y.astype(bool)
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def ece(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b) if b < 1 else (p >= a) & (p <= b)
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)


@lru_cache(maxsize=1)
def metrics():
    X = experiment()
    F, te, dec, ot = X["F"], X["te"], X["dec"], X["ot"]
    y = F.leak[te].astype(float)
    P = np.array([d.p_leak for d in dec])
    s1 = np.array([o[0].score for o in ot])
    s2 = np.array([o[1].score for o in ot])
    frac = F.leak_frac[te]
    big = (y > 0) & (frac >= 0.05)
    true = F.leak_id[te]

    def sector_acc(locs):
        return float(np.mean([sector_of(true[k]) == sector_of(max(locs[k], key=locs[k].get)) for k in np.where(big)[0]]))

    acc = dict(fused=sector_acc([d.location for d in dec]),
               M1=sector_acc([o[0].location for o in ot]), M2=sector_acc([o[1].location for o in ot]))
    top1 = dict(fused=float(np.mean([d.suspect_pipe == true[k] for k, d in enumerate(dec) if big[k]])),
                M2=float(np.mean([max(ot[k][1].location, key=ot[k][1].location.get) == true[k] for k in np.where(big)[0]])),
                M1=float(np.mean([max(ot[k][0].location, key=ot[k][0].location.get) == true[k] for k in np.where(big)[0]])))
    act = np.array([d.action for d in dec])
    return dict(X=X, y=y, P=P, s1=s1, s2=s2, auc=dict(fused=auc(P, y), M1=auc(s1, y), M2=auc(s2, y)),
                ece=ece(P, y), acc=acc, top1=top1, act=act, frac=frac,
                fa_alert=float(np.mean(act[y == 0] == "alert")), alert_big=float(np.mean(act[big] == "alert")))


def checks() -> list[Check]:
    c: list[Check] = []
    M = metrics()
    fm = M["X"]["fm"]
    c.append(Check("10.1", "Fused probability: expected calibration error ≤ 0.05 (weak test here, see findings)", 0.05, M["ece"],
                   kind="le", ref="§6"))
    c.append(Check("10.2", "Fused detection AUC ≥ best single method", max(M["auc"]["M1"], M["auc"]["M2"]) - 1e-3,
                   M["auc"]["fused"], kind="ge", ref="§6"))
    c.append(Check("10.3", "Fused location (leaks ≥ 5 %): right sector ≥ best single method − 1 pt",
                   max(M["acc"]["M1"], M["acc"]["M2"]) - 0.01, M["acc"]["fused"], kind="ge", ref="§6"))
    c.append(Check("10.4", "Alerts on healthy test windows ≤ 2 %", 0.02, M["fa_alert"], kind="le", ref="§6"))
    c.append(Check("10.5", "Leaks ≥ 5 % raise an alert ≥ 95 % of the time", 0.95, M["alert_big"], kind="ge", ref="§6"))
    o1 = MethodOutput("M1", 0.95, {"SUB12": 0.7, "SUB13": 0.3}, 0.5, True)
    o2_bad = MethodOutput("M2", 0.95, {"MAIN1": 1.0}, 0.2, False)
    d = fu.decide([o1, o2_bad], fm)
    c.append(Check("10.6", "Quality gate: a method failing its own gate is excluded (decision = M1 alone)", True,
                   d.methods_used == ["M1"] and "M2" in d.methods_excluded and d.suspect_pipe == "SUB12",
                   kind="bool", ref="§6"))
    o3 = MethodOutput("M3", 0.01, {"SUB12": 1.0}, 0.0, True)
    o2 = MethodOutput("M2", 0.97, {"SUB12": 0.6, "SUB11": 0.4}, 0.01, True)
    d3 = fu.decide([o1, o2, o3], fm)
    c.append(Check("10.7", "Outlier rule: with 3 methods, one silent method (M3, damped wave) is excluded", True,
                   "M3" in d3.methods_excluded and d3.action == "alert", kind="bool", ref="§6"))
    ok = all(d.band[0] <= d.p_leak <= d.band[1] for d in M["X"]["dec"])
    c.append(Check("10.8", "The 5–95 % band always contains the fused probability", True, ok, kind="bool", ref="§6"))
    acts = M["act"]
    P = M["P"]
    consistent = np.all((P < fm.tau1) == (acts == "log")) and np.all((P >= fm.tau2) == (acts == "alert"))
    c.append(Check("10.9", "Actions follow the thresholds τ₁, τ₂ exactly", True, bool(consistent), kind="bool", ref="§6"))
    return c
