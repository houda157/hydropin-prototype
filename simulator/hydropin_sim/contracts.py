"""Data contracts: the objects that flow between the layers of the simulation.

These definitions are frozen. Later work may ADD optional fields,
but never rename or remove one without a CHANGELOG entry and re-running all
tests. Units are SI (head in m of water, flow in m3/s, length in m, time in s).

Sign conventions
----------------
* A pipe goes from ``start`` node to ``end`` node. Flow Q > 0 means start → end.
* Position along a pipe ``x`` is measured from its start node, 0 <= x <= length.
* Elevation ``z`` is metres above an arbitrary site datum (same for all nodes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ════════════════════════════════════════════════════════════════════════════
# 1. Network specification (input; written in YAML under config/networks/)
# ════════════════════════════════════════════════════════════════════════════


class NodeKind(str, Enum):
    SOURCE = "source"            # well / basin water level (fixed head)
    JUNCTION = "junction"        # plain pipe junction or tee
    LATERAL_BLOCK = "lateral_block"  # manifold outlet feeding N identical laterals
    DEAD_END = "dead_end"        # closed end of a main / sub-main
    FLUSH_VALVE = "flush_valve"  # where the M3 excitation valve is mounted


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: NodeKind
    x: float = Field(description="Easting in m (site coordinates)")
    y: float = Field(description="Northing in m (site coordinates)")
    z: float = Field(description="Ground/pipe elevation in m")
    head: Optional[float] = Field(None, description="Fixed head in m (SOURCE only)")
    outlet_coeff: Optional[float] = Field(
        None, ge=0, description="Fixed outlet (e.g. bench end valve partly open): Q = C h^0.5, C in m3/s/m^0.5")

    @model_validator(mode="after")
    def _source_has_head(self) -> "Node":
        if self.kind == NodeKind.SOURCE and self.head is None:
            raise ValueError(f"source node {self.id} needs a fixed 'head'")
        return self


class Pipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    start: str
    end: str
    material: Literal["PVC", "PE100", "LDPE", "PVC_FLEX", "SS316"]
    length: float = Field(gt=0, description="L_PIPE in m")
    d_out: float = Field(gt=0, description="Outside diameter in m")
    e_wall: float = Field(gt=0, description="E_WALL, wall thickness in m")
    k_minor: float = Field(0.0, ge=0, description="Sum of minor-loss coefficients")
    roughness: Optional[float] = Field(None, gt=0, description="Override EPS_R in m")

    @property
    def d_int(self) -> float:
        """D_INT = d_out - 2 e_wall (m)."""
        return self.d_out - 2.0 * self.e_wall

    @model_validator(mode="after")
    def _geometry(self) -> "Pipe":
        if self.start == self.end:
            raise ValueError(f"pipe {self.id} starts and ends at the same node")
        if self.d_out - 2.0 * self.e_wall <= 0:
            raise ValueError(f"pipe {self.id}: wall too thick for the diameter")
        return self


class Pump(BaseModel):
    """Pump on a link, curve H = H0_PUMP - R_PUMP * Q**N_PUMP (math note §2.6)."""
    model_config = ConfigDict(extra="forbid")
    id: str
    start: str
    end: str
    h0: float = Field(gt=0, description="H0_PUMP, shut-off head in m")
    r: float = Field(gt=0, description="R_PUMP")
    n: float = Field(gt=0, description="N_PUMP")


class Valve(BaseModel):
    """Sector valve (on/off) on an existing pipe."""
    model_config = ConfigDict(extra="forbid")
    id: str
    pipe: str


class LateralBlock(BaseModel):
    """N identical drip laterals hung on one manifold node (math note §2.4)."""
    model_config = ConfigDict(extra="forbid")
    node: str
    n_laterals: int = Field(gt=0)
    lateral_length: float = Field(gt=0, description="m")
    lateral_d_int: float = Field(gt=0, description="m (e.g. 0.0136 for Ø16)")
    slope: float = Field(0.0, description="Δz_lat / L_lat, positive downhill")
    pressure_compensating: bool = False


class Sector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    valve: str
    lateral_blocks: list[str] = Field(description="Node ids of LATERAL_BLOCK nodes")


class NetworkSpec(BaseModel):
    """Complete description of one network (test bench or farm)."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    nodes: list[Node]
    pipes: list[Pipe]
    pumps: list[Pump] = []
    valves: list[Valve] = []
    lateral_blocks: list[LateralBlock] = []
    sectors: list[Sector] = []

    @model_validator(mode="after")
    def _references(self) -> "NetworkSpec":
        node_ids = [n.id for n in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("duplicate node ids")
        link_ids = [p.id for p in self.pipes] + [p.id for p in self.pumps]
        if len(set(link_ids)) != len(link_ids):
            raise ValueError("duplicate link ids")
        known = set(node_ids)
        for link in [*self.pipes, *self.pumps]:
            for end in (link.start, link.end):
                if end not in known:
                    raise ValueError(f"link {link.id} refers to unknown node {end}")
        pipe_ids = {p.id for p in self.pipes}
        for v in self.valves:
            if v.pipe not in pipe_ids:
                raise ValueError(f"valve {v.id} on unknown pipe {v.pipe}")
        for lb in self.lateral_blocks:
            if lb.node not in known:
                raise ValueError(f"lateral block on unknown node {lb.node}")
        valve_ids = {v.id for v in self.valves}
        lb_nodes = {lb.node for lb in self.lateral_blocks}
        for s in self.sectors:
            if s.valve not in valve_ids:
                raise ValueError(f"sector {s.id} uses unknown valve {s.valve}")
            missing = set(s.lateral_blocks) - lb_nodes
            if missing:
                raise ValueError(f"sector {s.id}: unknown lateral blocks {missing}")
        return self


# ════════════════════════════════════════════════════════════════════════════
# 2. Scenario specification (one simulated situation)
# ════════════════════════════════════════════════════════════════════════════


class LeakSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipe: str
    position: float = Field(ge=0, le=1, description="x / L along the pipe")
    area: float = Field(gt=0, description="A_LEAK in m2")
    cd: Optional[float] = Field(None, description="override CD_LEAK")
    n1: Optional[float] = Field(None, description="override N1_LEAK")
    start_time: float = Field(0.0, ge=0, description="s")


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    network: str
    seed: int
    open_sectors: list[str]
    duration: float = Field(gt=0, description="s")
    timestep: float = Field(gt=0, description="s")
    water_temp: Optional[float] = Field(None, description="degC, default T_WATER")
    leaks: list[LeakSpec] = []
    clogging: dict[str, float] = Field(default_factory=dict, description="lateral block -> c_j")
    roughness_scale: dict[str, float] = Field(default_factory=dict, description="pipe -> factor")
    elevation_offset: dict[str, float] = Field(default_factory=dict, description="node -> m")


# ════════════════════════════════════════════════════════════════════════════
# 3. Simulation results (numeric, produced by the solvers)
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class SteadyResult:
    """Output of the steady-state twin for one scenario (extended-period)."""
    scenario_id: str
    time: np.ndarray                 # (T,) s
    node_ids: list[str]
    link_ids: list[str]
    head: np.ndarray                 # (T, n_nodes) m
    pressure: np.ndarray             # (T, n_nodes) m of water
    flow: np.ndarray                 # (T, n_links) m3/s, + = start→end
    leak_flow: np.ndarray            # (T,) m3/s, total leak outflow
    pump_flow: np.ndarray            # (T,) m3/s
    meta: dict = field(default_factory=dict)


@dataclass
class TransientResult:
    """Output of the MOC solver at monitored points."""
    scenario_id: str
    time: np.ndarray                 # (K,) s
    point_ids: list[str]             # "pipe_id@x" or node ids
    head: np.ndarray                 # (K, n_points) m
    flow: np.ndarray                 # (K, n_points) m3/s
    wave_speed: dict[str, float]     # pipe id -> a used on the grid (m/s)
    meta: dict = field(default_factory=dict)


@dataclass
class SensorSeries:
    """What a (virtual or real) sensor delivers. NaN = lost packet."""
    sensor_id: str
    node_id: str
    time: np.ndarray                 # (K,) s
    value: np.ndarray                # (K,) pressure head in m
    kind: Literal["low_rate", "high_rate"] = "low_rate"
    meta: dict = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════════════
# 4. Method outputs and decision
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class MethodOutput:
    """Common output of M1, M2, M3 (math note §6)."""
    method: Literal["M1", "M2", "M3"]
    score: float                     # s_i in [0, 1]
    location: dict[str, float]       # pipe id -> p_i(x) (sums to 1)
    quality: float                   # q_i, method-specific index
    quality_ok: bool                 # passed its own quality gate
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        if self.location:
            total = sum(self.location.values())
            if not np.isclose(total, 1.0, atol=1e-6):
                raise ValueError(f"location map sums to {total}, expected 1")


@dataclass
class Decision:
    p_leak: float                    # fused P(leak)
    band: tuple[float, float]        # 5th and 95th percentiles
    suspect_pipe: Optional[str]
    location: dict[str, float]
    action: Literal["log", "watch", "alert"]
    methods_used: list[str]
    methods_excluded: dict[str, str] # method -> reason


# ════════════════════════════════════════════════════════════════════════════
# 5. Field message (same format for the simulator and the real ESP32 nodes)
# ════════════════════════════════════════════════════════════════════════════


class SensorMessage(BaseModel):
    """MQTT payload published by a low-rate sensor node (topic hydropin/<farm>/<node>)."""
    model_config = ConfigDict(extra="forbid")
    farm: str
    node: str
    seq: int = Field(ge=0)
    ts: str = Field(description="ISO-8601 UTC timestamp")
    p_bar: float = Field(description="gauge pressure in bar, as measured")
    temp_c: float = Field(description="sensor box temperature")
    battery_v: float
    simulated: bool = False
