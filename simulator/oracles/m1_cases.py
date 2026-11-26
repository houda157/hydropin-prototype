"""M1 experiment on the simulated dataset (same split as M2)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch

from hydropin_sim.methods import m1_gnn as m1
from hydropin_sim.methods.features import make_features, split
from hydropin_sim.sensors.model import sigma_total
from oracles.m2_cases import FARM, dataset
from oracles.transient_cases import P


@lru_cache(maxsize=1)
def experiment(epochs: int = 250, seed: int = 0):
    torch.manual_seed(seed)
    ds = dataset()
    F = make_features(ds, P)
    tr, va, te = split(len(F.shift), seed=0)
    g = m1.build_graph(FARM)
    shifts = [tuple(s.split("+")) for s in ds["shifts"]]
    opens = [shifts[s] for s in F.shift]
    X = m1.node_features(g, F.dp, F.dq, list(ds["sensor_nodes"]), opens, sigma_total(P))
    Y = m1.labels(g, F.leak_id)
    model = m1.GCN(g)
    hist = m1.train(model, X[tr], Y[tr], X[va], Y[va], epochs=epochs, seed=seed)
    pv = m1.predict(model, X[va])
    pt = m1.predict(model, X[te])
    score = lambda p: 1.0 - np.prod(1.0 - p, axis=1)  # noqa: E731
    sv, st_ = score(pv), score(pt)
    healthy_v = ~F.leak[va]
    thr = float(np.quantile(sv[healthy_v], 0.99))      # 1 % false alarms on validation
    return dict(F=F, g=g, model=model, X=X, Y=Y, tr=tr, va=va, te=te, pt=pt, st=st_, thr=thr, hist=hist)
