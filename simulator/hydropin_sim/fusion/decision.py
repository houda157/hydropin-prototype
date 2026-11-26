"""Quality gate, probability and location fusion, decision. Math note §6.

    logit P = logit p₀ + Σ_{i∈A} w_i (logit s_i − logit p₀)
    p(x)   ∝ Π_{i∈A} p_i(x)^{v_i}
Detection weights w_i and location weights v_i are learned separately on
validation data (the fusion study made this explicit: M1 detects as well as M2 but
localises worse, so one weight per method is not enough).
A method is excluded (i ∉ A) if its own quality gate fails, or — with three or
more methods — if its logit score is more than δ away from the median.
The 5–95 % band comes from bootstrap resamples of the weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from scipy.optimize import minimize

from hydropin_sim.contracts import Decision, MethodOutput

EPS = 1e-6


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class FusionModel:
    p0: float
    w: dict[str, float]                     # detection weights
    v: dict[str, float]                     # location weights
    w_boot: list[dict[str, float]] = field(default_factory=list)
    delta: float = 4.0                      # outlier distance in logit units
    tau1: float = 0.3
    tau2: float = 0.8


def gate(outputs: Sequence[MethodOutput], delta: float) -> tuple[list[MethodOutput], dict[str, str]]:
    kept, excluded = [], {}
    for o in outputs:
        if not o.quality_ok:
            excluded[o.method] = f"quality gate failed (q = {o.quality:.3g})"
        else:
            kept.append(o)
    if len(kept) >= 3:
        med = float(np.median([logit(o.score) for o in kept]))
        still = []
        for o in kept:
            if abs(logit(o.score) - med) > delta:
                excluded[o.method] = f"outlier vs the other methods (logit {logit(o.score):.1f}, median {med:.1f})"
            else:
                still.append(o)
        kept = still
    return kept, excluded


def fuse_prob(kept: Sequence[MethodOutput], p0: float, w: dict[str, float]) -> float:
    l0 = float(logit(p0))
    return float(sigmoid(l0 + sum(w.get(o.method, 1.0) * (logit(o.score) - l0) for o in kept)))


def fuse_location(kept: Sequence[MethodOutput], v: dict[str, float], floor: float = 1e-4) -> dict[str, float]:
    keys = sorted({k for o in kept for k in o.location})
    if not keys:
        return {}
    logp = np.zeros(len(keys))
    for o in kept:
        p = np.array([max(o.location.get(k, 0.0), floor) for k in keys])
        logp += v.get(o.method, 1.0) * np.log(p / p.sum())
    p = np.exp(logp - logp.max())
    p /= p.sum()
    return dict(zip(keys, p.tolist()))


def decide(outputs: Sequence[MethodOutput], fm: FusionModel) -> Decision:
    kept, excluded = gate(outputs, fm.delta)
    P = fuse_prob(kept, fm.p0, fm.w)
    boots = [fuse_prob(kept, fm.p0, wb) for wb in fm.w_boot] or [P]
    band = (float(np.percentile(boots, 5)), float(np.percentile(boots, 95)))
    loc = fuse_location(kept, fm.v)
    suspect = max(loc, key=loc.get) if loc else None
    action = "log" if P < fm.tau1 else ("watch" if P < fm.tau2 else "alert")
    return Decision(P, (min(band[0], P), max(band[1], P)), suspect, loc, action,
                    [o.method for o in kept], excluded)


def learn_detection_weights(scores: dict[str, np.ndarray], y: np.ndarray, p0: float) -> dict[str, float]:
    """Max-likelihood weights of the log-odds fusion (intercept fixed at logit p₀)."""
    names = list(scores)
    l0 = float(logit(p0))
    Z = np.c_[[logit(scores[n]) - l0 for n in names]].T

    def nll(w):
        z = l0 + Z @ w
        return float(np.sum(np.logaddexp(0, z) - y * z)) + 1e-3 * float(w @ w)

    w = minimize(nll, np.ones(len(names)), method="L-BFGS-B", bounds=[(0, 5)] * len(names)).x
    return dict(zip(names, w.tolist()))


def learn_location_weights(maps: dict[str, list[dict[str, float]]], truth: Sequence[str],
                           grid: Sequence[float] = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0)) -> dict[str, float]:
    """Grid search maximising the mean log-probability given to the true location."""
    names = list(maps)
    best, best_v = -np.inf, None
    import itertools
    for combo in itertools.product(grid, repeat=len(names)):
        if sum(combo) == 0:
            continue
        v = dict(zip(names, combo))
        ll = 0.0
        for i, t in enumerate(truth):
            outs = [MethodOutput(n, 0.5, maps[n][i], 1.0, True) for n in names]
            loc = fuse_location(outs, v)
            ll += np.log(max(loc.get(t, 0.0), 1e-9))
        if ll > best:
            best, best_v = ll, v
    return best_v
