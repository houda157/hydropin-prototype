"""Choose where to put N pressure sensors on the virtual farm (N = 1..10).

    python -m farm.placement.optimise                    # sigma from the leak dataset
    python -m farm.placement.optimise --sigma-bar 0.012  # role 1's measured bench sigma
    python -m farm.placement.optimise --no-robust        # skip the perturbed-farm re-test

Blueprint section II.B, the cost-control algorithm:
  * a sensor at candidate node i **detects** leak s if |dP(i, s)| > k * sigma (k = 3);
  * the leak is **isolated to its branch** if, after removing the common mode over the chosen
    sensors, the sensor with the largest extra drop sits on the leak's branch (main or one
    sector) - the same rule the farm explorer uses, so both show the same numbers;
  * two leaks on different branches are **distinguishable** if their patterns over the chosen
    sensors differ by more than k * sigma somewhere (reported, not optimised);
  * greedy pick, then swaps, then a small genetic algorithm (fixed seed), keeping the best;
  * robustness: the chosen sets are re-tested on the 10 perturbed farm models (other
    roughness, elevations and clogging than the dataset, same seeds as perturbed/*.inp).

Inputs: farm/leaks/out/{dP.npy, candidates.json, scenarios.csv, meta.json}.
Outputs: dashboard/farm/placement.json (Farm tab) and farm/placement/out/sets.json (the 3,
6 and 10-sensor sets for the GNN vs M2 comparison). Everything is simulation.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LEAKS = ROOT / "farm" / "leaks" / "out"
OUT = ROOT / "farm" / "placement" / "out"
DASH = ROOT / "dashboard" / "farm" / "placement.json"

K_SIGMA = 3.0
COST_PER_NODE_DT = 292            # 217 DT sensor node + 75 DT buried tapping point
COST_NOTE = ("217 DT sensor node + 75 DT buried tapping point (master document prices); "
             "assumption until the market lead confirms the BOM")
N_MAX = 10
DETECT_WEIGHT = 0.25              # score = isolated + 0.25 * detected (as in the explorer)
TARGET_ISOLATED = 0.90


@dataclass
class Dataset:
    dP: np.ndarray            # [n_candidates x n_scenarios] bar, 0 where the node is unpressurised
    cand: list[str]           # candidate ids in row order
    cand_branch: np.ndarray   # [n_candidates] branch label
    branch: np.ndarray        # [n_scenarios] leak branch
    size: np.ndarray          # [n_scenarios] leak size %
    world: np.ndarray         # [n_scenarios] world id (for distinguishability pairs)
    sigma: float
    attr: np.ndarray | None = None   # [n_candidates x n_scenarios] branch a sensor speaks for:
                                     # its own, or "main" when its sector valve is closed


def attributed_branches(cand_branch: np.ndarray, cand_sector: list, open_sectors: list[str]) -> np.ndarray:
    """A sensor at the head of a closed sector sits on dead water: it reads exactly the main
    junction next to it and says nothing about its own sector (the controller knows which
    valves are shut). It therefore speaks for the main pipe in that shift."""
    out = np.repeat(cand_branch[:, None], len(open_sectors), axis=1).astype(object)
    for j, os_ in enumerate(open_sectors):
        opened = {int(x) for x in str(os_).split(";") if x != ""}
        for i, sec in enumerate(cand_sector):
            if sec is not None and int(sec) not in opened:
                out[i, j] = "main"
    return out.astype(str)


def load_dataset(leaks_dir: Path = LEAKS, sigma: float | None = None) -> Dataset:
    meta = json.loads((leaks_dir / "meta.json").read_text(encoding="utf-8"))
    cands = json.loads((leaks_dir / "candidates.json").read_text(encoding="utf-8"))
    sc = pd.read_csv(leaks_dir / "scenarios.csv")
    dP = np.load(leaks_dir / "dP.npy").astype(float)
    assert dP.shape == (len(cands), len(sc)), dP.shape
    cb = np.array([c["branch"] for c in cands])
    return Dataset(dP=dP, cand=[c["id"] for c in cands], cand_branch=cb,
                   branch=sc.branch.to_numpy(), size=sc.size_pct.to_numpy(dtype=float),
                   world=sc.world_id.to_numpy(),
                   sigma=float(meta["sigma_bar"] if sigma is None else sigma),
                   attr=attributed_branches(cb, [c["sector"] for c in cands], sc.open_sectors.tolist()))


def evaluate(rows, dP: np.ndarray, cand_branch: np.ndarray, branch: np.ndarray,
             sigma: float, k: float = K_SIGMA) -> dict:
    """Detected / isolated flags per scenario for the sensor rows `rows`.

    cand_branch is [n_candidates] or, per scenario, [n_candidates x n_scenarios]
    (see attributed_branches). Order-independent: ties go to the lowest candidate row."""
    rows = sorted(rows)
    n = dP.shape[1]
    if not rows:
        z = np.zeros(n, dtype=bool)
        return {"detected": z, "isolated": z.copy()}
    sub = dP[rows]                                     # [k x S]
    live = sub != 0.0
    detected = ((-sub > k * sigma) & live).any(axis=0)
    cnt = np.maximum(live.sum(axis=0), 1)
    mean = np.where(live, sub, 0.0).sum(axis=0) / cnt
    dev = np.where(live, sub - mean, np.inf)
    best = np.argmin(dev, axis=0)
    cb = cand_branch[np.array(rows)]
    named = cb[best, np.arange(n)] if cb.ndim == 2 else cb[best]
    isolated = detected & live.any(axis=0) & (named == branch)
    return {"detected": detected, "isolated": isolated}


def _cb(ds: Dataset) -> np.ndarray:
    return ds.attr if ds.attr is not None else ds.cand_branch


def score(rows, ds: Dataset, k: float = K_SIGMA) -> float:
    r = evaluate(rows, ds.dP, _cb(ds), ds.branch, ds.sigma, k)
    return float(r["isolated"].mean() + DETECT_WEIGHT * r["detected"].mean())


def distinguishable(rows, ds: Dataset, k: float = K_SIGMA) -> float:
    """Share of detected leak pairs (same world, different branch) whose common-mode-free
    patterns over the chosen sensors differ by more than k * sigma at some sensor."""
    rows = list(rows)
    if len(rows) < 2:
        return 0.0
    det = evaluate(rows, ds.dP, _cb(ds), ds.branch, ds.sigma, k)["detected"]
    ok = tot = 0
    for w in np.unique(ds.world):
        idx = np.where((ds.world == w) & det)[0]
        if len(idx) < 2:
            continue
        sub = ds.dP[np.ix_(rows, idx)]
        live = (sub != 0.0).all(axis=1)                # sensors pressurised in this world
        if live.sum() < 2:
            continue
        pat = sub[live] - sub[live].mean(axis=0)       # [k_live x m]
        diff = np.abs(pat[:, :, None] - pat[:, None, :]).max(axis=0)
        other = ds.branch[idx][:, None] != ds.branch[idx][None, :]
        iu = np.triu(other, 1)
        tot += int(iu.sum())
        ok += int((diff[iu] > k * ds.sigma).sum())
    return ok / tot if tot else 0.0


def greedy(n: int, ds: Dataset, start=(), k: float = K_SIGMA) -> list[int]:
    chosen = list(start)
    while len(chosen) < n:
        best, bs = None, -1.0
        for c in range(len(ds.cand)):
            if c in chosen:
                continue
            v = score(chosen + [c], ds, k)
            if v > bs + 1e-12:
                best, bs = c, v
        chosen.append(best)
    return chosen


def swaps(chosen: list[int], ds: Dataset, k: float = K_SIGMA) -> list[int]:
    chosen, cur, improved = list(chosen), score(chosen, ds, k), True
    while improved:
        improved = False
        for i in range(len(chosen)):
            for c in range(len(ds.cand)):
                if c in chosen:
                    continue
                trial = chosen.copy()
                trial[i] = c
                v = score(trial, ds, k)
                if v > cur + 1e-12:
                    chosen, cur, improved = trial, v, True
    return chosen


def genetic(n: int, ds: Dataset, seed_sets: list[list[int]], k: float = K_SIGMA,
            pop: int = 40, gens: int = 60, seed: int = 20261126) -> list[int]:
    """Fixed-size subsets; uniform crossover on the union, swap mutation, elitism."""
    rng = np.random.default_rng(seed + n)
    m = len(ds.cand)
    if n >= m:
        return list(range(m))
    popu = [sorted(s) for s in seed_sets if len(s) == n]
    while len(popu) < pop:
        popu.append(sorted(rng.choice(m, n, replace=False).tolist()))
    cache: dict[tuple, float] = {}

    def fit(s):
        key = tuple(s)
        if key not in cache:
            cache[key] = score(s, ds, k)
        return cache[key]

    for _ in range(gens):
        popu.sort(key=fit, reverse=True)
        nxt = popu[:4]                                   # elitism
        while len(nxt) < pop:
            a, b = (popu[min(rng.integers(0, pop, 2))] for _ in range(2))   # tournament
            pool = sorted(set(a) | set(b))
            child = sorted(rng.choice(pool, n, replace=False).tolist())
            if rng.random() < 0.4:
                out = [c for c in range(m) if c not in child]
                child[rng.integers(n)] = int(rng.choice(out))
                child = sorted(child)
            nxt.append(child)
        popu = nxt
    return max(popu, key=fit)


def optimise_all(ds: Dataset, n_max: int = N_MAX, k: float = K_SIGMA, use_ga: bool = True) -> list[dict]:
    out, prev = [], []
    for n in range(1, min(n_max, len(ds.cand)) + 1):
        g = greedy(n, ds, start=prev, k=k)               # nested greedy: N builds on N-1
        s = swaps(g, ds, k)
        best = s
        if use_ga:
            ga = genetic(n, ds, [g, s], k=k)
            if score(ga, ds, k) > score(best, ds, k) + 1e-12:
                best = ga
        prev = best
        out.append({"n": n, "rows": best, "greedy_rows": g,
                    "score": score(best, ds, k), "greedy_score": score(g, ds, k)})
    return out


def summarise(rows, ds: Dataset, k: float = K_SIGMA) -> dict:
    r = evaluate(rows, ds.dP, _cb(ds), ds.branch, ds.sigma, k)
    by_size = {}
    for s in sorted(np.unique(ds.size)):
        m = ds.size == s
        by_size[f"{s:g}"] = {"detected_pct": round(100 * float(r["detected"][m].mean()), 1),
                             "isolated_pct": round(100 * float(r["isolated"][m].mean()), 1)}
    return {"detected_pct": round(100 * float(r["detected"].mean()), 1),
            "isolated_pct": round(100 * float(r["isolated"].mean()), 1),
            "by_size": by_size}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sigma-bar", type=float, help="sensor noise sigma in bar (default: dataset meta)")
    ap.add_argument("--k", type=float, default=K_SIGMA)
    ap.add_argument("--no-ga", action="store_true")
    ap.add_argument("--no-robust", action="store_true", help="skip the perturbed-farm re-test")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)

    ds = load_dataset(sigma=a.sigma_bar)
    results = optimise_all(ds, k=a.k, use_ga=not a.no_ga)

    robust_ds = None
    if not a.no_robust:
        from farm.placement.robustness import load_or_simulate
        robust_ds = load_or_simulate(ds, workers=a.workers)

    sets = []
    for r in results:
        rows = r["rows"]
        entry = {"n": r["n"], "nodes": [ds.cand[i] for i in rows],
                 "greedy_nodes": [ds.cand[i] for i in r["greedy_rows"]],
                 **summarise(rows, ds, a.k),
                 "distinguishable_pct": round(100 * distinguishable(rows, ds, a.k), 1),
                 "cost_dt": r["n"] * COST_PER_NODE_DT}
        if robust_ds is not None:
            rs = summarise(rows, robust_ds, a.k)
            entry["robust"] = {"detected_pct": rs["detected_pct"], "isolated_pct": rs["isolated_pct"],
                               "by_size": rs["by_size"]}
        sets.append(entry)

    def _big(s, key):
        return min(s["by_size"].get(z, {}).get(key, 0.0) for z in ("3", "10"))
    ok = [s for s in sets if _big(s, "detected_pct") >= 99.9 and _big(s, "isolated_pct") >= 100 * TARGET_ISOLATED]
    recommended = ok[0]["n"] if ok else max(sets, key=lambda s: _big(s, "isolated_pct") - 1.0 * s["n"])["n"]

    doc = {
        "version": "1.1", "simulation": True,
        "source": "farm/placement/optimise.py on farm/leaks/out (WNTR virtual farm)",
        "n_scenarios": int(ds.dP.shape[1]), "candidates": ds.cand,
        "sigma_bar": ds.sigma,
        "sigma_note": (json.loads((LEAKS / "meta.json").read_text(encoding="utf-8")).get("sigma_note", "")
                       if a.sigma_bar is None else "given on the command line (role 1's measured bench sigma)"),
        "k": a.k, "cost_per_node_dt": COST_PER_NODE_DT, "cost_note": COST_NOTE,
        "rules": {"detected": "|dP| > k*sigma at one chosen sensor at least",
                  "isolated": "largest common-mode-free drop is on the leak's branch",
                  "distinguishable": "pairs of detected leaks on different branches (same farm "
                                     "state) whose patterns differ by > k*sigma at some sensor",
                  "robust": "same sets re-tested on the 10 perturbed farm models, 3 % and 10 % leaks"},
        "method": "nested greedy, then swaps, then a genetic algorithm (fixed seed); best kept",
        "recommended_n": recommended,
        "target": (f"all 3 % and 10 % leaks detected and >= {int(100 * TARGET_ISOLATED)} % of them isolated; "
                   "if no N reaches it, the N with the best isolation minus 1 point per sensor"),
        "target_met": bool(ok),
        "sets": sets,
    }
    DASH.parent.mkdir(parents=True, exist_ok=True)
    DASH.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    pick = {str(n): next(s["nodes"] for s in sets if s["n"] == n) for n in (3, 6, 10) if n <= len(sets)}
    (OUT / "sets.json").write_text(json.dumps({"simulation": True, "sigma_bar": ds.sigma, "sets": pick},
                                              indent=1), encoding="utf-8")
    for s in sets:
        rb = f"  robust {s['robust']['detected_pct']:5.1f}/{s['robust']['isolated_pct']:5.1f}" if "robust" in s else ""
        print(f"N={s['n']:2d}  detected {s['detected_pct']:5.1f} %  isolated {s['isolated_pct']:5.1f} %  "
              f"distinct {s['distinguishable_pct']:5.1f} %  {s['cost_dt']:5d} DT{rb}  {' '.join(s['nodes'])}")
    print(f"recommended N = {recommended}  ->  {DASH.relative_to(ROOT)}, {(OUT / 'sets.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
