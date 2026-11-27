"""Fusion experiment: M1 + M2 outputs on validation (learning) and test (evaluation) windows."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.contracts import MethodOutput
from hydropin_sim.fusion import decision as fu
from hydropin_sim.methods import m1_gnn as m1
from hydropin_sim.methods import m2_pca as m2
from oracles.m1_cases import experiment as m1_exp
from oracles.m2_cases import experiment as m2_exp
from oracles.transient_cases import P


def outputs_for(rows, E1, E2, p1):
    F = E2["F"]
    g = E1["g"]
    out = []
    for r, i in enumerate(rows):
        mdl, X = E2["models"][F.shift[i]]
        x = X(np.array([i]))
        o2 = m2.to_output(mdl, x, {})
        o1 = m1.to_output(g, p1[r], E1["thr"], {})
        out.append((o1, o2))
    return out


@lru_cache(maxsize=1)
def experiment():
    E1, E2 = m1_exp(), m2_exp()
    F = E2["F"]
    va, te = E1["va"], E1["te"]
    pv = m1.predict(E1["model"], E1["X"][va])
    pt = E1["pt"]
    ov = outputs_for(va, E1, E2, pv)
    ot = outputs_for(te, E1, E2, pt)
    yv = F.leak[va].astype(float)
    p0 = float(yv.mean())   # prior of the training data; operation prior applied by Bayes prior shift (report)
    sv = {"M1": np.array([o[0].score for o in ov]), "M2": np.array([o[1].score for o in ov])}
    w = fu.learn_detection_weights(sv, yv, p0)
    # prior-shift correction: validation has ~50 % leaky windows, operation p0
    leaky_v = np.where(F.leak[va])[0]
    maps = {"M1": [ov[k][0].location for k in leaky_v], "M2": [ov[k][1].location for k in leaky_v]}
    v = fu.learn_location_weights(maps, [str(F.leak_id[va][k]) for k in leaky_v])
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(40):
        b = rng.integers(0, len(yv), len(yv))
        boots.append(fu.learn_detection_weights({k: s[b] for k, s in sv.items()}, yv[b], p0))
    fm = fu.FusionModel(p0, w, v, boots, tau1=P.decision.TAU1.v, tau2=P.decision.TAU2.v)
    dec = [fu.decide([o1, o2], fm) for o1, o2 in ot]
    return dict(E1=E1, E2=E2, F=F, te=te, va=va, ot=ot, fm=fm, dec=dec, yv=yv, sv=sv)
