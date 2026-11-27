"""NetworkSpec -> WNTR model. Math note §2.1–2.6.

Modelling choices (Architecture D2):
* Darcy–Weisbach everywhere; EPANET viscosity set from the water temperature.
* Each lateral block = one node with an emitter (exponent 0.5) whose coefficient
  is fitted to the equivalent-lateral law of math note §2.4 over the operating range.
* Pumps use the 3-parameter curve H = h0 - r Q^n (math note §2.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import wntr

from hydropin_sim.config import Params
from hydropin_sim.contracts import LateralBlock, NetworkSpec, NodeKind
from hydropin_sim.physics import emitters as em

EPANET_NU_REF = 1.1e-5 * 0.3048 ** 2   # EPANET reference viscosity (1.1e-5 ft2/s = 1.0219e-6 m2/s)
FIT_RANGE = (6.0, 25.0)                # m: operating range for the lateral-block emitter fit


@dataclass
class BlockFit:
    c_lateral: float       # emitter coefficient of ONE lateral (m3/s / m^0.5)
    max_rel_error: float   # worst relative error of the fit over FIT_RANGE
    h: np.ndarray
    q_equivalent: np.ndarray


@dataclass
class BuildInfo:
    block_fits: dict[str, BlockFit] = field(default_factory=dict)
    nu: float = 0.0


@lru_cache(maxsize=64)
def _fit_lateral(n_e: int, s: float, d: float, eps: float, nu: float, slope: float,
                 q_nom: float, h_nom: float, x: float) -> BlockFit:
    def dr(h):
        return em.dripper_flow(h, q_nom, h_nom, x)
    h = np.linspace(*FIT_RANGE, 25)
    q = np.array([em.lateral_equivalent_flow(hi, n_e, s, d, eps, nu, dr, slope=slope) for hi in h])
    # least squares on the RELATIVE error of q = C h^0.5: min sum (C sqrt(h)/q - 1)^2
    sq = np.sqrt(h)
    c = float(np.sum(sq / q) / np.sum(h / q ** 2))
    err = float(np.max(np.abs(c * sq / q - 1)))
    return BlockFit(c, err, h, q)


def fit_block(lb: LateralBlock, P: Params, nu: float) -> BlockFit:
    e = P.emitters
    if lb.pressure_compensating:
        raise NotImplementedError("PC drippers are not a power law; not supported by the EPANET twin yet")
    s = e.S_EMIT.v
    n_e = int(round(lb.lateral_length / s))
    return _fit_lateral(n_e, s, lb.lateral_d_int, P.material("LDPE").EPS_R.v, nu, lb.slope,
                        e.Q_NOM.v, e.H_NOM.v, e.X_EMIT.v)


def build_wntr(spec: NetworkSpec, P: Params, water_temp: Optional[float] = None
               ) -> tuple[wntr.network.WaterNetworkModel, BuildInfo]:
    nu = P.nu_w(water_temp)
    info = BuildInfo(nu=nu)
    wn = wntr.network.WaterNetworkModel()
    opts = wn.options.hydraulic
    opts.headloss = "D-W"
    opts.viscosity = nu / EPANET_NU_REF
    opts.emitter_exponent = 0.5
    opts.accuracy = 1e-7
    opts.trials = 500
    opts.demand_model = "DD"
    wn.options.time.duration = 0

    blocks = {lb.node: lb for lb in spec.lateral_blocks}
    for n in spec.nodes:
        if n.kind == NodeKind.SOURCE:
            wn.add_reservoir(n.id, base_head=n.head, coordinates=(n.x, n.y))
            continue
        wn.add_junction(n.id, base_demand=0.0, elevation=n.z, coordinates=(n.x, n.y))
        j = wn.get_node(n.id)
        c = 0.0
        if n.id in blocks:
            fit = fit_block(blocks[n.id], P, nu)
            info.block_fits[n.id] = fit
            c += blocks[n.id].n_laterals * fit.c_lateral
        if n.outlet_coeff:
            c += n.outlet_coeff
        if c > 0:
            j.emitter_coefficient = c

    for p in spec.pipes:
        eps = p.roughness if p.roughness is not None else P.material(p.material).EPS_R.v
        wn.add_pipe(p.id, p.start, p.end, length=p.length, diameter=p.d_int,
                    roughness=eps, minor_loss=p.k_minor)
    for pu in spec.pumps:
        q_max = (pu.h0 / pu.r) ** (1 / pu.n)
        qs = (0.0, 0.5 * q_max, 0.95 * q_max)   # EPANET 3-point curve: exact for H = h0 - r Q^n
        pts = [(q, float(pu.h0 - pu.r * q ** pu.n)) for q in qs]
        wn.add_curve(f"{pu.id}_curve", "HEAD", pts)
        wn.add_pump(pu.id, pu.start, pu.end, pump_type="HEAD", pump_parameter=f"{pu.id}_curve")
    return wn, info


def write_inp(wn: wntr.network.WaterNetworkModel, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wntr.network.write_inpfile(wn, str(path), units="LPS")
    return path
