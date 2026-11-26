"""Build the HydroPin virtual farm as a WNTR model (simulation only).

Layout (plan view, main along a central farm road, pump station at the south):

    E5 ─ A5 ─ B5═H5─M3─H6═B6 ─ A6 ─ E6      row 3 (north)
                    │
    E3 ─ A3 ─ B3═H3─M2─H4═B4 ─ A4 ─ E4      row 2
                    │
    E1 ─ A1 ─ B1═H1─M1─H2═B2 ─ A2 ─ E2      row 1 (south)
                    │
                   PS  (pump outlet)
                    │ PUMP
                   R0  (farm basin)

H = sector head (upstream of the sector valve, always pressurised), ═ = sector valve
pipe V{s}, B = downstream of the valve, A / E = manifold demands (E = sub-main end).

Every value comes from params.yaml; see that file for which values are assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import wntr
import yaml

HERE = Path(__file__).resolve().parent
PARAMS_PATH = HERE / "params.yaml"
M_TO_BAR = 0.0980665  # 1 m of water head in bar (rho = 1000 kg/m3, g = 9.80665)


def load_params(path: str | Path = PARAMS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class FarmMeta:
    """Static description of the farm that WNTR objects cannot carry."""

    nodes: dict = field(default_factory=dict)   # name -> {kind, sector, branch, candidate, x, y}
    pipes: dict = field(default_factory=dict)   # name -> {kind, sector, branch, leak_candidate}
    sectors: dict = field(default_factory=dict)  # id -> {side, row, nodes, bbox}

    @property
    def junction_names(self) -> list[str]:
        return [n for n, d in self.nodes.items() if d["kind"] != "reservoir"]

    @property
    def candidate_names(self) -> list[str]:
        return [n for n, d in self.nodes.items() if d["candidate"]]


def sector_flow_m3s(params: dict) -> float:
    """Design flow of one sector (m3/s): area x application rate."""
    f = params["farm"]
    area_m2 = f["area_ha"] * 1e4 / (2 * f["n_rows"])
    return area_m2 * params["irrigation"]["application_mm_h"] / 1000.0 / 3600.0


def _elevation(params: dict, x: float, y: float) -> float:
    f = params["farm"]
    return f["ground_elev_m"] + f["slope_north"] * y + f["slope_east"] * (x - f["width_m"] / 2)


def describe_farm(params: dict) -> FarmMeta:
    """Geometry, kinds and sector membership of every node and pipe."""
    f = params["farm"]
    cand_kinds = set(params["sensors"]["candidate_kinds"])
    xm = f["width_m"] / 2
    row_h = f["length_m"] / f["n_rows"]
    off_a, off_e = params["irrigation"]["manifold_offsets_m"]
    meta = FarmMeta()

    def node(name, kind, x, y, sector=None):
        meta.nodes[name] = {
            "kind": kind, "x": float(x), "y": float(y), "sector": sector,
            "branch": "main" if sector is None else f"sector_{sector}",
            "candidate": kind in cand_kinds,
        }

    def pipe(name, kind, sector=None, leak_candidate=True):
        meta.pipes[name] = {
            "kind": kind, "sector": sector,
            "branch": "main" if sector is None else f"sector_{sector}",
            "leak_candidate": leak_candidate,
        }

    node("R0", "reservoir", xm, -30)
    node("PS", "pump_out", xm, 0)
    pipe("PUMP", "pump", leak_candidate=False)
    prev = "PS"
    for r in range(f["n_rows"]):
        y = (r + 0.5) * row_h
        m = f"M{r + 1}"
        node(m, "main", xm, y)
        pipe(f"MN{r + 1}", "main")
        for side, sgn in (("west", -1), ("east", +1)):
            s = 2 * r + (1 if side == "west" else 2)
            node(f"H{s}", "sector_head", xm + sgn * 6, y, s)
            node(f"B{s}", "valve_out", xm + sgn * 8, y, s)
            node(f"A{s}", "manifold", xm + sgn * off_a, y, s)
            node(f"E{s}", "submain_end", xm + sgn * off_e, y, s)
            pipe(f"L{s}", "sector_link", s, leak_candidate=False)   # 6 m stub: node leaks cover it
            pipe(f"V{s}", "sector_valve", s, leak_candidate=False)  # the valve itself
            pipe(f"S{s}a", "submain_1", s)
            pipe(f"S{s}b", "submain_2", s)
            x0, x1 = sorted((xm, xm + sgn * f["width_m"] / 2))
            meta.sectors[s] = {
                "side": side, "row": r + 1,
                "nodes": [f"H{s}", f"B{s}", f"A{s}", f"E{s}"],
                "bbox": [x0, r * row_h, x1, (r + 1) * row_h],
            }
        prev = m
    del prev
    return meta


def _pipe_ends(meta: FarmMeta) -> dict:
    """name -> (start, end) for every link."""
    ends = {"PUMP": ("R0", "PS")}
    rows = sorted(n for n, d in meta.nodes.items() if d["kind"] == "main")
    prev = "PS"
    for i, m in enumerate(rows, start=1):
        ends[f"MN{i}"] = (prev, m)
        prev = m
    for s in meta.sectors:
        row = meta.sectors[s]["row"]
        ends[f"L{s}"] = (f"M{row}", f"H{s}")
        ends[f"V{s}"] = (f"H{s}", f"B{s}")
        ends[f"S{s}a"] = (f"B{s}", f"A{s}")
        ends[f"S{s}b"] = (f"A{s}", f"E{s}")
    return ends


def build_network(params: dict | None = None, seed: int | None = None,
                  open_sectors: list[int] | None = None) -> tuple[wntr.network.WaterNetworkModel, FarmMeta]:
    """Build the farm model.

    seed=None gives the nominal model (the "digital twin"). An integer seed draws the
    uncertain parameters (roughness, elevation, clogging) from params['perturb'], which
    plays the role of the real farm that the twin never matches exactly.
    open_sectors: sectors whose valve is open (default: all).
    """
    params = params or load_params()
    meta = describe_farm(params)
    rng = np.random.default_rng(seed) if seed is not None else None
    pp = params["perturb"]
    hyd = params["hydraulics"]

    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.headloss = hyd["headloss"]
    wn.options.hydraulic.demand_model = hyd["demand_model"]
    wn.options.hydraulic.required_pressure = hyd["required_pressure_m"]
    wn.options.hydraulic.minimum_pressure = hyd["minimum_pressure_m"]
    wn.options.hydraulic.pressure_exponent = hyd["pressure_exponent"]
    wn.options.time.duration = 0

    # Nodes
    q_sector = sector_flow_m3s(params)
    split = dict(zip(("manifold", "submain_end"), params["irrigation"]["manifold_split"]))
    clog = {s: (rng.uniform(*pp["clogging_range"]) if rng is not None else 1.0) for s in meta.sectors}
    for name, d in meta.nodes.items():
        z = _elevation(params, d["x"], d["y"])
        if d["kind"] == "reservoir":
            wn.add_reservoir(name, base_head=params["pump"]["suction_head_m"], coordinates=(d["x"], d["y"]))
            continue
        if rng is not None:
            z += rng.normal(0.0, pp["elevation_sd_m"])
        demand = q_sector * split.get(d["kind"], 0.0) * clog.get(d["sector"], 1.0)
        wn.add_junction(name, base_demand=demand, elevation=z, coordinates=(d["x"], d["y"]))

    # Pump: 3-point head curve
    qd = params["pump"]["design_flow_lps"] / 1000.0
    hd = params["pump"]["design_head_m"]
    wn.add_curve("PUMP_CURVE", "HEAD", [(0.0, 1.33 * hd), (qd, hd), (2 * qd, 0.0)])

    # Links
    for name, (a, b) in _pipe_ends(meta).items():
        kind = meta.pipes[name]["kind"]
        if kind == "pump":
            wn.add_pump(name, a, b, pump_type="HEAD", pump_parameter="PUMP_CURVE")
            continue
        spec = params["pipes"][kind]
        if "length_m" in spec:
            length = spec["length_m"]
        else:
            na, nb = meta.nodes[a], meta.nodes[b]
            length = float(np.hypot(na["x"] - nb["x"], na["y"] - nb["y"]))
        c = spec["roughness"]
        if rng is not None:
            c *= rng.normal(1.0, pp["roughness_rel_sd"])
        wn.add_pipe(name, a, b, length=length, diameter=spec["diameter_m"], roughness=c,
                    minor_loss=spec.get("minor_loss", 0.0))

    set_sector_config(wn, meta, open_sectors if open_sectors is not None else list(meta.sectors))
    return wn, meta


def set_sector_config(wn, meta: FarmMeta, open_sectors: list[int]) -> None:
    """Open the valves of `open_sectors`, close the rest and zero their demand."""
    open_set = set(open_sectors)
    for s, sec in meta.sectors.items():
        valve = wn.get_link(f"V{s}")
        is_open = s in open_set
        valve.initial_status = wntr.network.LinkStatus.Open if is_open else wntr.network.LinkStatus.Closed
        for n in sec["nodes"]:
            j = wn.get_node(n)
            ts = j.demand_timeseries_list[0]
            if not hasattr(j, "_hp_base_demand"):
                j._hp_base_demand = ts.base_value
            ts.base_value = j._hp_base_demand if is_open else 0.0


def pressurised_nodes(meta: FarmMeta, open_sectors: list[int]) -> set[str]:
    """Junctions connected to the pump under a sector configuration."""
    open_set = set(open_sectors)
    out = set()
    for n, d in meta.nodes.items():
        if d["kind"] == "reservoir":
            continue
        if d["sector"] is None or d["kind"] == "sector_head" or d["sector"] in open_set:
            out.add(n)
    return out


def run_steady(wn) -> dict:
    """Single steady-state PDD run. Returns pressures (m), demands, leak flows, link flows."""
    res = wntr.sim.WNTRSimulator(wn).run_sim()
    out = {
        "pressure_m": res.node["pressure"].iloc[0],
        "demand": res.node["demand"].iloc[0],
        "flow": res.link["flowrate"].iloc[0],
    }
    out["leak_demand"] = res.node["leak_demand"].iloc[0] if "leak_demand" in res.node else None
    return out


if __name__ == "__main__":
    p = load_params()
    for cfg in p["irrigation"]["open_configs"]:
        wn, meta = build_network(p, open_sectors=cfg)
        r = run_steady(wn)
        pr = r["pressure_m"]
        live = sorted(pressurised_nodes(meta, cfg))
        print(f"open {cfg}: pump {r['flow']['PUMP'] * 1000:.1f} L/s, "
              f"PS {pr['PS']:.1f} m, manifolds "
              + ", ".join(f"{n}={pr[n]:.1f}" for n in live if n[0] in "AE"))
