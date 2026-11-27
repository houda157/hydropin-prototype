"""Monte Carlo scenario sampler. Math note §2.9.

Each scenario = one irrigation shift (set of open sectors) in a perturbed farm,
healthy or with ONE leak. Leaks are placed only where water flows during that
shift (main + open sectors): a leak in a closed sector loses no water and no
method can see it.

Leak locations:
* "pipe"    – on a main or sub-main pipe, uniform position along it;
* "lateral" – inside a lateral block (split lateral), modelled as a leak at the
              block node (position 1.0 of the sub-main pipe ending there).
Leak size: flow fraction of the shift's nominal flow, log-uniform in
[LEAK_FRAC_MIN, LEAK_FRAC_MAX], converted to an orifice area at the nominal
pressure of the shift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import LeakSpec, NetworkSpec, Scenario
from hydropin_sim.physics.leaks import leak_area_for_flow

LEAK_FRAC_MIN, LEAK_FRAC_MAX = 0.01, 0.20
ROUGHNESS_SCALE = (0.8, 3.0)       # ageing / deposits multiplier on EPS_R
ELEVATION_SD = 0.05                # m, survey error per node
TEMP_RANGE = (15.0, 35.0)          # degC, irrigation-season water temperature
CLOG_BETA = (1.0, 6.0)             # c_j = C_CLOG_max × Beta(1, 6): mostly clean, a few clogged


@dataclass
class ShiftInfo:
    sectors: tuple[str, ...]
    q_nominal: float      # m3/s, healthy pump flow of the unperturbed farm
    h_nominal: float      # m, mean block pressure of the unperturbed farm


def default_shifts(spec: NetworkSpec) -> list[tuple[str, ...]]:
    ids = [s.id for s in spec.sectors]
    singles = [(s,) for s in ids]
    pairs = [(ids[i], ids[i + len(ids) // 2]) for i in range(len(ids) // 2)]
    return singles + pairs


def candidate_leaks(spec: NetworkSpec, sectors: Sequence[str]) -> tuple[list[str], list[str]]:
    """(pipes carrying water during the shift, lateral blocks of the open sectors)."""
    open_set = set(sectors)
    sector_of_pipe = {}
    for s in spec.sectors:
        k = s.id[-1]
        valve_pipe = next(v.pipe for v in spec.valves if v.id == s.valve)
        sector_of_pipe[valve_pipe] = s.id
        for p in spec.pipes:
            if p.id.startswith(f"SUB{k}"):
                sector_of_pipe[p.id] = s.id
    pipes = [p.id for p in spec.pipes if sector_of_pipe.get(p.id) in open_set or p.id not in sector_of_pipe]
    # main pipes downstream of the last open take-off carry no flow: drop them
    takeoffs = [int(s[-1]) for s in sectors]
    last = max(takeoffs)
    pipes = [p for p in pipes if not (p.startswith("MAIN") and int(p[4:]) > last)]
    blocks = [b for s in spec.sectors if s.id in open_set for b in s.lateral_blocks]
    return pipes, blocks


class ScenarioSampler:
    def __init__(self, spec: NetworkSpec, P: Params, shift_info: dict[tuple[str, ...], ShiftInfo],
                 seed: int, leak_prob: float = 0.5, lateral_share: float = 0.5):
        self.spec, self.P = spec, P
        self.shift_info = shift_info
        self.shifts = list(shift_info)
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.leak_prob, self.lateral_share = leak_prob, lateral_share
        self.c_clog_max = P.emitters.C_CLOG.range[1]
        self._pipe_len = {p.id: p.length for p in spec.pipes}
        self._block_pipe = {p.end: p.id for p in spec.pipes if p.id.startswith("SUB")}

    def sample(self, i: int, shift: Optional[tuple[str, ...]] = None,
               leak: Optional[bool] = None) -> Scenario:
        rng = self.rng
        shift = shift if shift is not None else self.shifts[rng.integers(len(self.shifts))]
        info = self.shift_info[shift]
        clog = {lb.node: float(self.c_clog_max * rng.beta(*CLOG_BETA)) for lb in self.spec.lateral_blocks}
        rough = {p.id: float(rng.uniform(*ROUGHNESS_SCALE)) for p in self.spec.pipes}
        elev = {n.id: float(rng.normal(0, ELEVATION_SD)) for n in self.spec.nodes if n.kind.value != "source"}
        temp = float(rng.uniform(*TEMP_RANGE))
        leaks = []
        has_leak = (rng.random() < self.leak_prob) if leak is None else leak
        if has_leak:
            pipes, blocks = candidate_leaks(self.spec, shift)
            frac = float(np.exp(rng.uniform(np.log(LEAK_FRAC_MIN), np.log(LEAK_FRAC_MAX))))
            area = float(leak_area_for_flow(frac * info.q_nominal, info.h_nominal, self.P.leaks.CD_LEAK.v))
            if rng.random() < self.lateral_share:
                b = blocks[rng.integers(len(blocks))]
                leaks.append(LeakSpec(pipe=self._block_pipe[b], position=1.0, area=area))
            else:
                w = np.array([self._pipe_len[p] for p in pipes])
                p = pipes[rng.choice(len(pipes), p=w / w.sum())]
                leaks.append(LeakSpec(pipe=p, position=float(rng.uniform(0.02, 0.98)), area=area))
        return Scenario(id=f"s{self.seed}_{i:05d}", network=self.spec.name, seed=self.seed * 100000 + i,
                        open_sectors=list(shift), duration=1, timestep=1, water_temp=temp,
                        leaks=leaks, clogging=clog, roughness_scale=rough, elevation_offset=elev)
