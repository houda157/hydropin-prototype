"""Leak signatures on the 10 perturbed farm models, for the placement robustness re-test.

The perturbed models are the ones exported to farm/model/perturbed/farm_pXX.inp
(seed = base_seed + 100000 + k): other roughness, elevations and clogging than any world in
the leak dataset. For each model and each irrigation shift, every pressurised leak site is
simulated at 3 % and 10 % of the open-sector flow (1 % leaks are mostly below the noise
anyway). The noise-free dP at the candidate nodes is cached in farm/placement/out/robust_dP.npz.

    python -m farm.placement.robustness          # (re)build the cache
"""
from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import numpy as np

from farm.leaks.scenarios import World, leak_sites
from farm.leaks.simulate import simulate_world
from farm.model.build_farm import describe_farm, load_params
from farm.placement.optimise import OUT, Dataset, attributed_branches

CACHE = OUT / "robust_dP.npz"
SIZES = (3.0, 10.0)


def _job(args):
    params, world, rows = args
    r = simulate_world(params, world, rows, sigma_bar=0.0, n_healthy=1)
    return world.world_id, r["names"], r["dP"], r["records"]


def simulate(workers: int | None = None) -> dict:
    params = load_params()
    meta = describe_farm(params)
    base = params["leaks"]["base_seed"] + 100000          # same seeds as perturbed/*.inp
    n_models = params["perturb"]["n_perturbed_models"]
    jobs, sid = [], 0
    for c, cfg in enumerate(params["irrigation"]["open_configs"]):
        sites, _ = leak_sites(meta, tuple(cfg))
        for k in range(n_models):
            w = World(len(jobs), c, tuple(cfg), base + k)
            rows = []
            for site in sites:
                for size in SIZES:
                    rows.append({"scenario_id": sid, "world_id": w.world_id, "site": site, "size_pct": size})
                    sid += 1
            jobs.append((params, w, rows))
    workers = workers or max(1, (mp.cpu_count() or 2) - 1)
    if workers > 1:
        with mp.Pool(workers) as pool:
            res = pool.map(_job, jobs, chunksize=1)
    else:
        res = [_job(j) for j in jobs]
    res.sort(key=lambda r: r[0])
    names = res[0][1]
    cand_idx = [names.index(c) for c in meta.candidate_names]
    dP = np.concatenate([r[2] for r in res])[:, cand_idx].T          # [candidates x S]
    recs = [rec for r in res for rec in r[3]]
    out = {"dP": dP.astype(np.float32), "branch": np.array([r["branch"] for r in recs]),
           "size": np.array([r["size_pct"] for r in recs], dtype=float),
           "world": np.array([r["world_id"] for r in recs]),
           "open": np.array([r["open_sectors"] for r in recs]),
           "cand": np.array(meta.candidate_names)}
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, **out)
    return out


def load_or_simulate(ds: Dataset, workers: int | None = None, rebuild: bool = False) -> Dataset:
    if CACHE.exists() and not rebuild:
        d = dict(np.load(CACHE, allow_pickle=False))
    else:
        print("simulating leaks on the 10 perturbed farm models ...")
        d = simulate(workers)
    if list(d["cand"]) != ds.cand or "open" not in d:
        print("robustness cache out of date: re-simulating ...")
        d = simulate(workers)
    meta = describe_farm(load_params())
    sectors = [meta.nodes[c]["sector"] for c in ds.cand]
    return Dataset(dP=d["dP"].astype(float), cand=ds.cand, cand_branch=ds.cand_branch,
                   branch=d["branch"], size=d["size"], world=d["world"], sigma=ds.sigma,
                   attr=attributed_branches(ds.cand_branch, sectors, d["open"].tolist()))


if __name__ == "__main__":
    r = simulate()
    print(f"{r['dP'].shape[1]} perturbed-farm leak scenarios -> {CACHE}")
