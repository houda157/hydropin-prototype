"""Sensor placement. Math note §7.

Φ(S) = coverage(S) + λ_iso · isolation(S)
  coverage  = share of (shift, leak location) pairs whose leak changes at least one
              sensor of S by more than κ σ_tot  (leak of size LEAK_FRAC_DESIGN)
  isolation = mean over leak locations of the angle (rad, /π/2 → [0, 1]) between its
              signature on S and the closest signature of another location more than
              ISO_MIN_DIST away (locations at the same place cannot be told apart by
              any sensor set, so they are not counted against S); a location no sensor
              sees scores 0
Greedy: add the node that raises Φ most. Genetic algorithm: population of sensor
sets, fitness Φ, crossover = union sampling, mutation = move one sensor to a
neighbouring node.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Optional, Sequence

import numpy as np

ISO_MIN_DIST = 5.0      # m


@dataclass
class PlacementProblem:
    nodes: list[str]
    neighbours: dict[int, list[int]]
    sig: list[np.ndarray]           # per shift: (n_loc, n_nodes) Δh for a design leak (m)
    loc_xy: list[np.ndarray]        # per shift: (n_loc, 2)
    threshold: float                # κ σ_tot (m)
    lam_iso: float = 1.0
    fixed: Sequence[int] = ()       # nodes that always carry a sensor (none by default)

    def phi(self, S: Sequence[int]) -> float:
        S = list(S)
        if not S:
            return 0.0
        cov, iso, n = 0.0, 0.0, 0
        for sig, xy in zip(self.sig, self.loc_xy):
            sub = sig[:, S]
            det = np.any(np.abs(sub) > self.threshold, axis=1)
            cov += det.sum()
            norm = np.linalg.norm(sub, axis=1) + 1e-12
            u = sub / norm[:, None]
            cos = np.clip(u @ u.T, -1, 1)
            ang = np.arccos(cos)
            d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
            ang = np.where(d > ISO_MIN_DIST, ang, np.inf)
            np.fill_diagonal(ang, np.inf)
            ang = np.where(det[None, :], ang, np.inf)          # compare only with visible locations
            nearest = np.min(ang, axis=1)
            nearest = np.where(np.isfinite(nearest), nearest, np.pi / 2)
            iso += np.sum(np.where(det, nearest / (np.pi / 2), 0.0))   # an unseen leak cannot be isolated
            n += len(sig)
        return float(cov / n + self.lam_iso * iso / n)


def greedy(prob: PlacementProblem, k: int) -> tuple[list[int], list[float]]:
    S = list(prob.fixed)
    hist = []
    while len(S) < k:
        cand = [v for v in range(len(prob.nodes)) if v not in S]
        best = max(cand, key=lambda v: prob.phi(S + [v]))
        S.append(best)
        hist.append(prob.phi(S))
    return S, hist


def exhaustive(prob: PlacementProblem, k: int) -> tuple[list[int], float]:
    best, val = None, -np.inf
    for S in combinations(range(len(prob.nodes)), k):
        v = prob.phi(S)
        if v > val:
            best, val = list(S), v
    return best, val


def genetic(prob: PlacementProblem, k: int, seed: int = 0, pop: int = 40, gens: int = 60,
            init: Optional[Sequence[int]] = None) -> tuple[list[int], float, list[float]]:
    rng = np.random.default_rng(seed)
    V = len(prob.nodes)

    def mutate(S):
        S = list(S)
        i = rng.integers(len(S))
        nb = [u for u in prob.neighbours[S[i]] if u not in S]
        if nb and rng.random() < 0.8:
            S[i] = int(rng.choice(nb))
        else:
            free = [u for u in range(V) if u not in S]
            S[i] = int(rng.choice(free))
        return sorted(S)

    def cross(a, b):
        pool = list(set(a) | set(b))
        return sorted(rng.choice(pool, size=k, replace=False).tolist())

    P = [sorted(rng.choice(V, size=k, replace=False).tolist()) for _ in range(pop)]
    if init is not None:
        P[0] = sorted(init)
    hist = []
    for _ in range(gens):
        fit = np.array([prob.phi(S) for S in P])
        order = np.argsort(-fit)
        elite = [P[i] for i in order[: pop // 4]]
        hist.append(float(fit[order[0]]))
        children = list(elite)
        while len(children) < pop:
            a, b = rng.choice(len(elite), 2, replace=False)
            child = cross(elite[a], elite[b])
            if rng.random() < 0.7:
                child = mutate(child)
            children.append(child)
        P = children
    fit = np.array([prob.phi(S) for S in P])
    i = int(np.argmax(fit))
    return P[i], float(fit[i]), hist
