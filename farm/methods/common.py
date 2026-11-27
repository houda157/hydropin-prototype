"""Shared data loading for the farm methods: scenarios, residuals, train/test split, sites, pipes.

Split (fixed, no leakage): within each irrigation shift there are 10 perturbed worlds
(world_id % 10 = 0..9). Worlds 0-6 train, 7-9 test. A test world never shapes a fingerprint,
a threshold or a network weight.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LEAKS = ROOT / "farm" / "leaks" / "out"
LAYOUT = ROOT / "farm" / "model" / "layout.json"
SETS = ROOT / "farm" / "placement" / "out" / "sets.json"
OUT = ROOT / "farm" / "methods" / "out"
TEST_WORLDS = (7, 8, 9)
N_BASELINE = 20          # healthy samples averaged into the baseline (farm/leaks/simulate.py)


@dataclass
class FarmData:
    sc: pd.DataFrame
    X: np.ndarray                 # [S x 28] residual vs measured healthy baseline (noisy), bar
    nodes: list[str]              # node order
    sigma: float                  # per-reading sensor noise
    sigma_eff: float              # noise of one residual value (reading + baseline, after averaging)
    avg_samples: int
    train: np.ndarray             # bool [S]
    test: np.ndarray              # bool [S]
    sites: list[str]              # all leak sites (node or pipe ids)
    site_idx: np.ndarray          # [S] index into sites
    site_branch: dict[str, str]
    links: list[dict]             # layout links except the pump
    site_links: dict[str, list[str]] = field(default_factory=dict)   # site -> links it maps to
    link_nodes: dict[str, tuple[str, str]] = field(default_factory=dict)


def load(avg_samples: int = 1) -> FarmData:
    """avg_samples = 1: the dataset's single noisy reading (gnn/X.npy).
    avg_samples = a > 1: the residual a farm controller would see after averaging a readings
    (and a baselines of 20 readings): noise-free dP + N(0, sigma * sqrt((1 + 1/20) / a)),
    fixed seed. White noise is an assumption; real drift averages down less."""
    meta = json.loads((LEAKS / "meta.json").read_text(encoding="utf-8"))
    sc = pd.read_csv(LEAKS / "scenarios.csv")
    sigma = float(meta["sigma_bar"])
    sig_eff = sigma * np.sqrt((1.0 + 1.0 / N_BASELINE) / avg_samples)
    if avg_samples <= 1:
        X = np.load(LEAKS / "gnn" / "X.npy").astype(float)
    else:
        clean = np.load(LEAKS / "gnn" / "X_clean.npy").astype(float)
        rng = np.random.default_rng([20261126, avg_samples])
        X = np.where(np.abs(clean) > 0, clean + rng.normal(0.0, sig_eff, clean.shape), 0.0)
    lay = json.loads(LAYOUT.read_text(encoding="utf-8"))
    links = [p for p in lay["pipes"] if p["kind"] != "pump"]
    link_nodes = {p["id"]: (p["from"], p["to"]) for p in links}
    sites = sorted(sc.leak_at.unique().tolist())
    sidx = {s: i for i, s in enumerate(sites)}
    site_links = {}
    for s in sites:
        if s in link_nodes:
            site_links[s] = [s]
        else:
            site_links[s] = [p for p, (a, b) in link_nodes.items() if s in (a, b)]
    w = (sc.world_id % 10).to_numpy()
    test = np.isin(w, TEST_WORLDS)
    return FarmData(sc=sc, X=X, nodes=meta["node_order"], sigma=sigma, sigma_eff=float(sig_eff),
                    avg_samples=int(avg_samples),
                    train=~test, test=test, sites=sites,
                    site_idx=sc.leak_at.map(sidx).to_numpy(),
                    site_branch=dict(zip(sc.leak_at, sc.branch)), links=links,
                    site_links=site_links, link_nodes=link_nodes)


def sensor_sets() -> dict[str, list[str]]:
    if SETS.exists():
        return json.loads(SETS.read_text(encoding="utf-8"))["sets"]
    raise FileNotFoundError("run python -m farm.placement.optimise first (writes the 3/6/10 sets)")


def site_to_link_probs(p_site: np.ndarray, fd: FarmData) -> dict[str, float]:
    """Spread site probabilities onto links: a pipe site is its pipe; a node site is shared
    equally by the links that touch it."""
    out = {p["id"]: 0.0 for p in fd.links}
    for i, s in enumerate(fd.sites):
        ls = fd.site_links[s]
        for link in ls:
            out[link] += float(p_site[i]) / len(ls)
    return out


def sites_adjacent(a: str, b: str, fd: FarmData) -> bool:
    """Within one hop: same site, or the two sites share a node."""
    if a == b:
        return True

    def ends(s):
        return set(fd.link_nodes[s]) if s in fd.link_nodes else {s}
    return bool(ends(a) & ends(b))
