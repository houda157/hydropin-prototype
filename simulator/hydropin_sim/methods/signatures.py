"""Leak signatures from the digital twin (used by M2 localisation and as M1 sanity checks).

For every irrigation shift and every location that carries water in that shift,
a nominal leak (LEAK_FRAC of the shift flow, at 25 °C, unperturbed farm) is
simulated and the change of the features (pressure at each sensor, pump flow)
is stored.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import LeakSpec, NetworkSpec, Scenario
from hydropin_sim.physics.leaks import leak_area_for_flow
from hydropin_sim.steady.scenarios import candidate_leaks
from hydropin_sim.steady.solver import run_steady

LEAK_FRAC = 0.05


def location_xy(spec: NetworkSpec, name: str) -> tuple[float, float]:
    xy = {n.id: (n.x, n.y) for n in spec.nodes}
    if name in xy:
        return xy[name]
    p = next(p for p in spec.pipes if p.id == name)
    (x1, y1), (x2, y2) = xy[p.start], xy[p.end]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def shift_signatures(spec: NetworkSpec, P: Params, shift: Sequence[str], sensors: Sequence[str]
                     ) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Returns (location names, Δp (n_loc, n_sensors), Δq (n_loc,))."""
    sc0 = Scenario(id="sig0", network=spec.name, seed=0, open_sectors=list(shift), duration=1, timestep=1,
                   water_temp=25.0)
    base = run_steady(spec, sc0, P)
    ix = {n: i for i, n in enumerate(base.node_ids)}
    p0 = np.array([base.pressure[0, ix[s]] for s in sensors])
    q0 = float(base.pump_flow[0])
    blocks_open = [b for s in spec.sectors if s.id in shift for b in s.lateral_blocks]
    h_nom = float(np.mean([base.pressure[0, ix[b]] for b in blocks_open]))
    area = float(leak_area_for_flow(LEAK_FRAC * q0, h_nom, P.leaks.CD_LEAK.v))
    pipes, blocks = candidate_leaks(spec, shift)
    block_pipe = {p.end: p.id for p in spec.pipes if p.id.startswith("SUB")}
    locs = [(p, LeakSpec(pipe=p, position=0.5, area=area)) for p in pipes] + \
           [(b, LeakSpec(pipe=block_pipe[b], position=1.0, area=area)) for b in blocks]
    names, dp, dq = [], [], []
    for name, lk in locs:
        r = run_steady(spec, sc0.model_copy(update=dict(leaks=[lk])), P)
        ixl = {n: i for i, n in enumerate(r.node_ids)}
        dp.append([r.pressure[0, ixl[s]] for s in sensors] - p0)
        dq.append(r.pump_flow[0] - q0)
        names.append(name)
    return names, np.array(dp), np.array(dq)
