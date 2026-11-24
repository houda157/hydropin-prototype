"""Generate the farm leak dataset (simulation) for sensor placement (role 2) and the GNN /
farm M2 (role 4). Output format: farm/leaks/FORMAT.md.

    python -m farm.leaks.generate                 # full grid from params.yaml
    python -m farm.leaks.generate --quick         # 1 config, 1 world: smoke test
    python -m farm.leaks.generate --sigma-bar 0.004   # re-run with role 1's measured sigma
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import wntr

from farm.leaks.scenarios import build_grid, skipped_count
from farm.leaks.simulate import simulate_world
from farm.model.build_farm import HERE as MODEL_DIR, build_network, describe_farm, load_params

ROOT = MODEL_DIR.parent.parent
DEFAULT_OUT = ROOT / "farm" / "leaks" / "out"
FORMAT_VERSION = "1.0"


def _job(args):
    params, world, rows, sigma, n_healthy = args
    return simulate_world(params, world, rows, sigma, n_healthy)


def graph_dict(params: dict) -> dict:
    """Pipe graph over junctions (nominal twin), for the GNN."""
    wn, meta = build_network(params)
    names = meta.junction_names
    idx = {n: i for i, n in enumerate(names)}
    nodes = [{"index": i, "id": n, "x": meta.nodes[n]["x"], "y": meta.nodes[n]["y"],
              "elev": round(wn.get_node(n).elevation, 3), "kind": meta.nodes[n]["kind"],
              "sector": meta.nodes[n]["sector"], "branch": meta.nodes[n]["branch"],
              "candidate": meta.nodes[n]["candidate"]} for i, n in enumerate(names)]
    edges = []
    for p, d in meta.pipes.items():
        if d["kind"] == "pump":
            continue
        link = wn.get_link(p)
        edges.append({"id": p, "source": idx[link.start_node_name], "target": idx[link.end_node_name],
                      "kind": d["kind"], "sector": d["sector"], "branch": d["branch"],
                      "length": round(link.length, 2), "diameter": link.diameter})
    return {"version": FORMAT_VERSION, "simulation": True, "nodes": nodes, "edges": edges,
            "note": "Undirected in practice. Sector-valve edges (kind=sector_valve) are closed "
                    "when their sector is not open; see sector_open.npy per scenario."}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-seeds", type=int, help="perturbed worlds per sector config")
    ap.add_argument("--sizes", type=float, nargs="+", help="leak sizes, %% of open-sector flow")
    ap.add_argument("--sigma-bar", type=float, help="sensor noise sigma in bar")
    ap.add_argument("--configs", type=int, nargs="+", help="sector-config indices to run")
    ap.add_argument("--quick", action="store_true", help="1 config, 1 world, 2 sizes")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)

    params = load_params()
    if a.quick:
        a.n_seeds, a.sizes, a.configs = a.n_seeds or 1, a.sizes or [1, 10], a.configs or [0]
    sigma = params["leaks"]["sigma_bar"] if a.sigma_bar is None else a.sigma_bar
    n_healthy = params["leaks"]["healthy_samples_per_world"]
    worlds, rows = build_grid(params, a.n_seeds, a.sizes, a.configs)
    by_world = {w.world_id: [] for w in worlds}
    for r in rows:
        by_world[r["world_id"]].append(r)
    jobs = [(params, w, by_world[w.world_id], sigma, n_healthy) for w in worlds]

    t0 = time.time()
    print(f"{len(worlds)} worlds, {len(rows)} scenarios, sigma={sigma} bar, {a.workers} workers")
    if a.workers > 1 and len(jobs) > 1:
        with mp.Pool(a.workers) as pool:
            results = pool.map(_job, jobs, chunksize=1)
    else:
        results = [_job(j) for j in jobs]
    results.sort(key=lambda r: r["world"].world_id)
    runtime = time.time() - t0

    meta = describe_farm(params)
    names = results[0]["names"]
    cand = meta.candidate_names
    cand_idx = [names.index(c) for c in cand]
    recs = [rec for r in results for rec in r["records"]]
    order = np.argsort([rec["scenario_id"] for rec in recs])
    recs = [recs[i] for i in order]
    dP = np.concatenate([r["dP"] for r in results])[order]
    X = np.concatenate([r["X"] for r in results])[order]
    X_twin = np.concatenate([r["X_twin"] for r in results])[order]
    healthy = np.concatenate([r["healthy"] for r in results])
    healthy_world = np.repeat([r["world"].world_id for r in results], n_healthy)
    healthy_cfg = np.repeat([r["world"].config_id for r in results], n_healthy)

    node_index = {n: i for i, n in enumerate(names)}
    y_node = np.array([node_index[r["leak_at"]] if r["leak_kind"] == "node" else -1 for r in recs])
    sector_open = np.zeros((len(recs), len(names)), dtype=bool)
    for k, r in enumerate(recs):
        open_s = {int(s) for s in r["open_sectors"].split(";")}
        for i, n in enumerate(names):
            s = meta.nodes[n]["sector"]
            sector_open[k, i] = s is None or s in open_s

    out = a.out
    (out / "gnn").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(recs).to_csv(out / "scenarios.csv", index=False)
    np.save(out / "dP.npy", dP[:, cand_idx].T.astype(np.float32))        # [candidates x scenarios]
    np.save(out / "dP_all.npy", dP.astype(np.float32))                   # [scenarios x nodes]
    np.save(out / "healthy.npy", healthy.astype(np.float32))             # [samples x nodes]
    pd.DataFrame({"world_id": healthy_world, "config_id": healthy_cfg}).to_csv(out / "healthy_index.csv", index_label="sample")
    (out / "candidates.json").write_text(json.dumps([
        {"row": i, "id": c, "node_index": names.index(c), "kind": meta.nodes[c]["kind"],
         "branch": meta.nodes[c]["branch"], "sector": meta.nodes[c]["sector"],
         "x": meta.nodes[c]["x"], "y": meta.nodes[c]["y"]} for i, c in enumerate(cand)], indent=1), encoding="utf-8")
    (out / "gnn" / "graph.json").write_text(json.dumps(graph_dict(params), indent=1), encoding="utf-8")
    np.save(out / "gnn" / "X.npy", X.astype(np.float32))                 # [scenarios x nodes], noisy, vs healthy baseline
    np.save(out / "gnn" / "X_twin.npy", X_twin.astype(np.float32))       # [scenarios x nodes], noisy, vs nominal twin
    np.save(out / "gnn" / "X_clean.npy", dP.astype(np.float32))         # [scenarios x nodes], noise-free
    np.save(out / "gnn" / "y_node.npy", y_node)
    np.save(out / "gnn" / "sector_open.npy", sector_open)
    (out / "gnn" / "y_pipe.json").write_text(json.dumps(
        [r["leak_at"] if r["leak_kind"] == "pipe" else "" for r in recs]), encoding="utf-8")

    info = {
        "format_version": FORMAT_VERSION, "simulation": True,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wntr_version": wntr.__version__, "runtime_s": round(runtime, 1),
        "units": {"pressure": "bar (gauge)", "flow": "L/s", "xy": "m"},
        "sigma_bar": sigma,
        "sigma_note": "PLACEHOLDER assumption until role 1's measured bench sigma" if a.sigma_bar is None else "set on command line",
        "n_scenarios": len(recs), "n_worlds": len(worlds),
        "n_sites_skipped_not_pressurised": skipped_count(params, a.configs),
        "sizes_pct": sorted({r["size_pct"] for r in recs}),
        "node_order": names, "candidate_order": cand,
        "params_version": params["meta"]["version"],
    }
    (out / "meta.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"done in {runtime:.1f}s -> {out}")


if __name__ == "__main__":
    main()
