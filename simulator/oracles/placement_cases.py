"""Sensor-placement problem for the demo farm (all shifts, all leak locations, every junction a candidate)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from hydropin_sim.methods.signatures import location_xy, shift_signatures
from hydropin_sim.placement.optimizer import PlacementProblem
from hydropin_sim.sensors.dataset import FARM_SENSORS
from hydropin_sim.sensors.model import sigma_total
from hydropin_sim.steady.scenarios import default_shifts
from oracles.m2_cases import FARM
from oracles.transient_cases import P

DESIGN_LEAK = 0.005      # design leak: 0.5 % of the shift flow (signatures scaled linearly from 5 %)


@lru_cache(maxsize=1)
def problem(lam_iso: float = 1.0) -> PlacementProblem:
    nodes = [n.id for n in FARM.nodes if n.kind.value != "source"]
    ix = {n: i for i, n in enumerate(nodes)}
    nb = {i: [] for i in range(len(nodes))}
    for p in FARM.pipes:
        if p.start in ix and p.end in ix:
            nb[ix[p.start]].append(ix[p.end])
            nb[ix[p.end]].append(ix[p.start])
    sigs, xys = [], []
    for sh in default_shifts(FARM):
        names, dp, dq = shift_signatures(FARM, P, sh, nodes)
        sigs.append(dp * DESIGN_LEAK / 0.05)
        xys.append(np.array([location_xy(FARM, n) for n in names]))
    thr = P.decision.KAPPA.v * sigma_total(P)
    return PlacementProblem(nodes, nb, sigs, xys, thr, lam_iso)


def default_set(prob: PlacementProblem) -> list[int]:
    return [prob.nodes.index(n) for n in FARM_SENSORS]
