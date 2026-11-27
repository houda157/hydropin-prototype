"""Parameter loading and validation (single source of truth: config/params.yaml).

Every constant used by the simulation is read through this module. Values are
checked against their plausible range when the file is loaded, and a parameter
whose value is still unknown (``null``) raises an error the moment it is used.

Example
-------
>>> from hydropin_sim.config import load_params
>>> P = load_params()
>>> P.water.G.value
9.81
>>> P.material("PE100").E_PIPE.value
1100000000.0
>>> P.nu_w(25.0)          # interpolated kinematic viscosity at 25 degC
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARAMS = PACKAGE_ROOT / "config" / "params.yaml"

Number = Union[float, int]


class MissingParameterError(RuntimeError):
    """Raised when a parameter whose value is still unknown (null) is used."""


class Param(BaseModel):
    """One physical parameter with its unit, symbol and provenance."""

    model_config = ConfigDict(extra="forbid")

    value: Optional[Union[Number, list[Number]]]
    unit: str
    symbol: str
    meaning: str
    source: str
    range: Optional[tuple[float, float]] = None
    verify: bool = False
    at: Optional[list[float]] = None
    at_unit: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "Param":
        if self.value is None:
            return self
        values = self.value if isinstance(self.value, list) else [self.value]
        if self.at is not None:
            if len(self.at) != len(values):
                raise ValueError("'at' and 'value' must have the same length")
            if any(b <= a for a, b in zip(self.at, self.at[1:])):
                raise ValueError("'at' must be strictly increasing")
        if self.range is not None:
            lo, hi = self.range
            if lo > hi:
                raise ValueError(f"range {self.range} is reversed")
            bad = [v for v in values if not lo <= v <= hi]
            if bad:
                raise ValueError(f"value(s) {bad} outside plausible range {self.range}")
        return self

    @property
    def v(self) -> Union[float, np.ndarray]:
        """Value as float or numpy array; raises if the value is still unknown."""
        if self.value is None:
            raise MissingParameterError(
                f"Parameter '{self.meaning}' has no value yet (source: {self.source})."
            )
        if isinstance(self.value, list):
            return np.asarray(self.value, dtype=float)
        return float(self.value)

    def interp(self, x: float) -> float:
        """Linear interpolation of a tabulated parameter (e.g. vs temperature)."""
        if self.at is None:
            raise ValueError("parameter is not tabulated")
        lo, hi = self.at[0], self.at[-1]
        if not lo <= x <= hi:
            raise ValueError(f"{x} {self.at_unit} outside table [{lo}, {hi}]")
        return float(np.interp(x, self.at, np.asarray(self.v)))


class Group(BaseModel):
    """A named group of parameters; access them as attributes (P.water.G)."""

    model_config = ConfigDict(extra="allow")

    def items(self) -> dict[str, Param]:
        return dict(self.__pydantic_extra__ or {})

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: dict) -> dict:
        return {k: Param(**v) for k, v in data.items()}


class Params(BaseModel):
    """All simulation parameters, grouped as in the math note (section 0)."""

    model_config = ConfigDict(extra="forbid")

    meta: dict
    water: Group
    materials: dict[str, Group]
    pipes: Group
    emitters: Group
    leaks: Group
    energy: Group
    transient: Group
    sensors: Group
    decision: Group
    prototype: Group

    # ── convenience accessors ──
    def material(self, name: str) -> Group:
        if name not in self.materials:
            raise KeyError(f"Unknown material '{name}'. Known: {sorted(self.materials)}")
        return self.materials[name]

    def nu_w(self, temp_c: Optional[float] = None) -> float:
        """Kinematic viscosity (m2/s) at temperature temp_c (default T_WATER)."""
        t = self.water.T_WATER.v if temp_c is None else temp_c
        return self.water.NU_W.interp(t)

    def p_vap(self, temp_c: Optional[float] = None) -> float:
        """Vapour pressure (Pa) at temperature temp_c (default T_WATER)."""
        t = self.water.T_WATER.v if temp_c is None else temp_c
        return self.water.P_VAP.interp(t)

    def all_params(self) -> dict[str, Param]:
        """Flat view {code_name: Param}. Material params are prefixed 'PE100.E_PIPE'."""
        out: dict[str, Param] = {}
        for gname in ("water", "pipes", "emitters", "leaks", "energy", "transient",
                      "sensors", "decision", "prototype"):
            out.update(getattr(self, gname).items())
        for mname, grp in self.materials.items():
            for k, p in grp.items().items():
                out[f"{mname}.{k}"] = p
        return out

    def code_names(self) -> set[str]:
        """Code names defined in params.yaml (material params without prefix)."""
        return {k.split(".")[-1] for k in self.all_params()}


# Names from the math note that are NOT stored in params.yaml, and where they live.
DERIVED: dict[str, str] = {
    "J0": "1 / E_PIPE (per material)",
    "K_D": "Q_NOM / H_NOM**X_EMIT",
    "N_EMIT": "lateral length / S_EMIT",
    "A_WAVE": "hydropin_sim.physics.waves.wave_speed (math note §5.2)",
    "DT": "chosen so that the Courant number is 1 (math note §5.5)",
}
PER_ELEMENT: dict[str, str] = {
    "D_INT": "network spec, per pipe",
    "E_WALL": "network spec, per pipe",
    "L_PIPE": "network spec, per pipe",
    "H0_PUMP": "network spec, pump curve",
    "R_PUMP": "network spec, pump curve",
    "N_PUMP": "network spec, pump curve",
    "A_LEAK": "scenario spec, per leak",
}


def load_params(path: Union[str, Path, None] = None) -> Params:
    """Load and validate params.yaml. Raises on any unit/range/structure error."""
    path = Path(path) if path is not None else DEFAULT_PARAMS
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    params = Params(**raw)
    if params.decision.TAU1.v >= params.decision.TAU2.v:
        raise ValueError("TAU1 must be smaller than TAU2")
    for mname, grp in params.materials.items():
        jk, tk = grp.J_K.value, grp.TAU_K.value
        if len(jk) != len(tk):
            raise ValueError(f"{mname}: J_K and TAU_K must have the same length")
    return params
