"""Oracles – sensor placement (math note §7)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.placement.optimizer import exhaustive, genetic, greedy
from oracles.base import Check
from oracles.placement_cases import default_set, problem


def coverage(pr, S):
    tot = det = 0
    for sig in pr.sig:
        det += np.any(np.abs(sig[:, list(S)]) > pr.threshold, axis=1).sum()
        tot += len(sig)
    return det / tot


@lru_cache(maxsize=1)
def results():
    pr = problem()
    g12, hist = greedy(pr, 12)
    ex = {k: exhaustive(pr, k) for k in (2, 3, 4)}
    gr = {k: pr.phi(greedy(pr, k)[0]) for k in (2, 3, 4)}
    ga, ga_val, ga_hist = genetic(pr, 9, init=g12[:9])
    return dict(pr=pr, greedy12=g12, hist=hist, ex=ex, gr=gr, ga=ga, ga_val=ga_val, ga_hist=ga_hist,
                default=default_set(pr))


def checks() -> list[Check]:
    c: list[Check] = []
    R = results()
    pr = R["pr"]
    for i, k in enumerate((2, 3, 4)):
        c.append(Check(f"9.{i + 1}", f"Greedy reaches ≥ 95 % of the exhaustive optimum with {k} sensors",
                       0.95, R["gr"][k] / R["ex"][k][1], kind="ge", ref="§7"))
    c.append(Check("9.4", "Greedy Φ never decreases when a sensor is added", True,
                   bool(np.all(np.diff(R["hist"]) >= -1e-12)), kind="bool", ref="§7"))
    g9 = pr.phi(R["greedy12"][:9])
    c.append(Check("9.5", "Genetic algorithm (seeded with greedy) ≥ greedy, 9 sensors", g9, R["ga_val"], kind="ge",
                   ref="§7"))
    c.append(Check("9.6", "Optimised 9-sensor set ≥ the default set", pr.phi(R["default"]), R["ga_val"],
                   kind="ge", ref="§7"))
    c.append(Check("9.7", "Optimised 9 sensors see as many design leaks as a sensor on every junction would",
                   float(coverage(pr, range(len(pr.nodes)))), float(coverage(pr, R["ga"])), 1e-9, "abs", "§7"))
    return c
