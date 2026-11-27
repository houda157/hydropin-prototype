"""Simulate every leak scenario of one world (healthy run once, then one run per leak)."""
from __future__ import annotations

import math

import numpy as np
import wntr

from farm.leaks.scenarios import World
from farm.model.build_farm import M_TO_BAR, build_network, run_steady

G = 9.80665


def _pressures_bar(result, names) -> np.ndarray:
    return result["pressure_m"].reindex(names).to_numpy(dtype=float) * M_TO_BAR


def simulate_world(params: dict, world: World, rows: list[dict], sigma_bar: float,
                   n_healthy: int) -> dict:
    """Run the healthy world, the nominal twin and every leak scenario in `rows`.

    Returns arrays over junctions (node order = meta.junction_names), all in bar:
      p_leak     pressure with the leak (noise-free)
      dP         p_leak - p_healthy(world)            true leak signature, noise-free
      X          p_leak + noise - baseline             residual vs a measured healthy baseline
                                                       (mean of n_healthy noisy samples), as on the bench
      X_twin     p_leak + noise - p_twin(nominal)      residual vs the uncalibrated nominal twin:
                                                       includes the model-reality gap (harder)
      healthy    n_healthy noisy healthy samples of this world
    """
    cfg = list(world.open_sectors)
    wn_h, meta = build_network(params, seed=world.seed, open_sectors=cfg)
    names = meta.junction_names
    healthy = run_steady(wn_h)
    p_h = _pressures_bar(healthy, names)
    pump_h = float(healthy["flow"]["PUMP"])
    demand_h = float(healthy["demand"].reindex(names).sum())

    wn_t, _ = build_network(params, seed=None, open_sectors=cfg)
    p_twin = _pressures_bar(run_steady(wn_t), names)

    rng_h = np.random.default_rng([params["leaks"]["base_seed"], 7, world.world_id])
    healthy_samples = p_h[None, :] + rng_h.normal(0.0, sigma_bar, size=(n_healthy, len(names)))
    baseline = healthy_samples.mean(axis=0)

    cd = params["hydraulics"]["leak_discharge_coeff"]
    recs, p_leak, dP, X, X_twin = [], [], [], [], []
    for row in rows:
        site = row["site"]
        q_target = row["size_pct"] / 100.0 * demand_h
        if site.kind == "node":
            wn, _ = build_network(params, seed=world.seed, open_sectors=cfg)
            leak_node = site.at
            h = float(healthy["pressure_m"][leak_node])
            xy = (meta.nodes[leak_node]["x"], meta.nodes[leak_node]["y"])
        else:
            base, _ = build_network(params, seed=world.seed, open_sectors=cfg)
            link = base.get_link(site.at)
            a, b = link.start_node_name, link.end_node_name
            leak_node = f"LK_{site.at}"
            wn = wntr.morph.split_pipe(base, site.at, f"{site.at}_2", leak_node)
            h = 0.5 * float(healthy["pressure_m"][a] + healthy["pressure_m"][b])
            xy = (0.5 * (meta.nodes[a]["x"] + meta.nodes[b]["x"]),
                  0.5 * (meta.nodes[a]["y"] + meta.nodes[b]["y"]))
        area = q_target / (cd * math.sqrt(2 * G * max(h, 0.1)))
        wn.get_node(leak_node).add_leak(wn, area=area, discharge_coeff=cd, start_time=0)
        res = run_steady(wn)
        pl = _pressures_bar(res, names)
        rng = np.random.default_rng([params["leaks"]["base_seed"], 11, row["scenario_id"]])
        measured = pl + rng.normal(0.0, sigma_bar, size=pl.shape)
        p_leak.append(pl)
        dP.append(pl - p_h)
        X.append(measured - baseline)
        X_twin.append(measured - p_twin)
        recs.append({
            "scenario_id": row["scenario_id"], "world_id": world.world_id,
            "config_id": world.config_id, "open_sectors": ";".join(map(str, cfg)),
            "world_seed": world.seed, "leak_kind": site.kind, "leak_at": site.at,
            "branch": site.branch, "sector": site.sector if site.sector is not None else "",
            "x": round(xy[0], 2), "y": round(xy[1], 2),
            "size_pct": row["size_pct"], "q_target_lps": round(q_target * 1000, 4),
            "area_m2": area, "leak_lps": round(float(res["leak_demand"][leak_node]) * 1000, 4),
            "pump_lps": round(float(res["flow"]["PUMP"]) * 1000, 4),
            "healthy_pump_lps": round(pump_h * 1000, 4),
        })
    return {
        "world": world, "records": recs, "names": names,
        "p_leak": np.array(p_leak), "dP": np.array(dP), "X": np.array(X),
        "X_twin": np.array(X_twin),
        "healthy": healthy_samples, "p_healthy": p_h, "p_twin": p_twin,
    }
