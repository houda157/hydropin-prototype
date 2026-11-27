"""The leak-scenario grid: locations x sizes x sector configurations x perturbed worlds.

A *world* is one sector configuration plus one random draw of the uncertain parameters
(roughness, elevations, clogging): the "real farm" for that scenario. The nominal model
(no perturbation) is the *twin*: what the monitoring system believes.
"""
from __future__ import annotations

from dataclasses import dataclass

from farm.model.build_farm import FarmMeta, describe_farm, pressurised_nodes


@dataclass(frozen=True)
class LeakSite:
    kind: str        # "node" or "pipe"
    at: str          # junction id or pipe id
    branch: str      # "main" or "sector_<s>"
    sector: int | None


@dataclass(frozen=True)
class World:
    world_id: int
    config_id: int
    open_sectors: tuple[int, ...]
    seed: int


def leak_sites(meta: FarmMeta, open_sectors) -> tuple[list[LeakSite], list[LeakSite]]:
    """(pressurised sites, sites skipped because they sit behind a closed sector valve)."""
    live = pressurised_nodes(meta, open_sectors)
    ok, skipped = [], []
    for n, d in meta.nodes.items():
        if d["kind"] == "reservoir":
            continue
        site = LeakSite("node", n, d["branch"], d["sector"])
        (ok if n in live else skipped).append(site)
    for p, d in meta.pipes.items():
        if not d["leak_candidate"]:
            continue
        site = LeakSite("pipe", p, d["branch"], d["sector"])
        sector_open = d["sector"] is None or d["sector"] in set(open_sectors)
        (ok if sector_open else skipped).append(site)
    return ok, skipped


def build_grid(params: dict, n_seeds: int | None = None, sizes=None, configs=None):
    """Return (worlds, scenario rows). Scenario ids are stable for a given argument set."""
    meta = describe_farm(params)
    n_seeds = params["leaks"]["n_seeds"] if n_seeds is None else n_seeds
    sizes = params["leaks"]["sizes_pct"] if sizes is None else sizes
    all_cfgs = params["irrigation"]["open_configs"]
    cfg_ids = range(len(all_cfgs)) if configs is None else configs
    base = params["leaks"]["base_seed"]

    worlds, rows = [], []
    sid = 0
    for c in cfg_ids:
        cfg = tuple(all_cfgs[c])
        sites, skipped = leak_sites(meta, cfg)
        for k in range(n_seeds):
            w = World(len(worlds), c, cfg, base + 1000 * c + k)
            worlds.append(w)
            for site in sites:
                for size in sizes:
                    rows.append({"scenario_id": sid, "world_id": w.world_id, "site": site,
                                 "size_pct": float(size)})
                    sid += 1
    return worlds, rows


def skipped_count(params: dict, configs=None) -> int:
    meta = describe_farm(params)
    all_cfgs = params["irrigation"]["open_configs"]
    cfg_ids = range(len(all_cfgs)) if configs is None else configs
    return sum(len(leak_sites(meta, all_cfgs[c])[1]) for c in cfg_ids)
