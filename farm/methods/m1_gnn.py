"""M1 on the virtual farm: a small graph convolutional network over the pipe graph (simulation).

    python -m farm.methods.m1_gnn          # torch (.venv-sim); then python -m farm.methods.results

Graph = the farm's 28 junctions and 27 pipes (farm/leaks/out/gnn/graph.json), symmetric
normalised adjacency with self-loops (D^-1/2 (A + I) D^-1/2). Node features per scenario:
  residual at sensor nodes / sigma (0 elsewhere), the same with the common mode removed,
  has-sensor flag, sector-open flag, elevation (standardised).
Three GCN layers (32 units) -> node embeddings. A leak site is a junction (its own embedding)
or a pipe (mean of its two end embeddings); a shared linear head gives one logit per site;
sites that cannot leak in that irrigation shift are masked. Cross-entropy, Adam, fixed seed.
One model per sensor set (3 / 6 / 10 from the placement tool) and per noise case (single reading,
1-minute average). Trained on worlds 0-6, evaluated by farm.methods.results on worlds 7-9.

Writes farm/methods/out/m1_pred_n{n}_a{avg}.npy: [n_scenarios x n_sites] probabilities.
"""
from __future__ import annotations

import json

import numpy as np
import torch
from torch import nn

from farm.methods.common import LEAKS, OUT, FarmData, load, sensor_sets

SEED = 20261126
EPOCHS = 1000
HIDDEN = 32


def graph(fd: FarmData):
    g = json.loads((LEAKS / "gnn" / "graph.json").read_text(encoding="utf-8"))
    n = len(g["nodes"])
    A = np.eye(n)
    for e in g["edges"]:
        A[e["source"], e["target"]] = A[e["target"], e["source"]] = 1.0
    d = A.sum(axis=1)
    Ahat = A / np.sqrt(np.outer(d, d))
    elev = np.array([x["elev"] for x in g["nodes"]], dtype=float)
    elev = (elev - elev.mean()) / (elev.std() or 1.0)
    idx = {x["id"]: x["index"] for x in g["nodes"]}
    ends = {e["id"]: (e["source"], e["target"]) for e in g["edges"]}
    # site -> (a, b) node indices (a == b for a junction)
    site_nodes = [(idx[s], idx[s]) if s in idx else ends[s] for s in fd.sites]
    return torch.tensor(Ahat, dtype=torch.float32), elev, site_nodes


def features(fd: FarmData, sensors: list[str], elev: np.ndarray) -> torch.Tensor:
    S, N = fd.X.shape
    cols = [fd.nodes.index(s) for s in sensors]
    has = np.zeros(N)
    has[cols] = 1.0
    open_ = np.load(LEAKS / "gnn" / "sector_open.npy").astype(float)
    R = np.zeros((S, N))
    R[:, cols] = fd.X[:, cols] / fd.sigma_eff
    live = np.zeros((S, N), dtype=bool)
    live[:, cols] = np.abs(fd.X[:, cols]) > 1e-12
    cnt = np.maximum(live.sum(axis=1, keepdims=True), 1)
    mean = np.where(live, R, 0).sum(axis=1, keepdims=True) / cnt
    C = np.where(live, R - mean, 0.0)
    F = np.stack([np.clip(R, -50, 50) / 10, np.clip(C, -50, 50) / 5, np.broadcast_to(has, (S, N)), open_,
                  np.broadcast_to(elev, (S, N))], axis=-1)
    return torch.tensor(F, dtype=torch.float32)


class FarmGCN(nn.Module):
    def __init__(self, f_in: int, site_nodes, hidden: int = HIDDEN):
        super().__init__()
        self.l1, self.l2, self.l3 = nn.Linear(f_in, hidden), nn.Linear(hidden, hidden), nn.Linear(hidden, hidden)
        self.head = nn.Linear(hidden, 1)
        self.a = torch.tensor([s[0] for s in site_nodes])
        self.b = torch.tensor([s[1] for s in site_nodes])

    def forward(self, A: torch.Tensor, X: torch.Tensor) -> torch.Tensor:
        h = torch.relu(A @ self.l1(X))
        h = torch.relu(A @ self.l2(h)) + h
        h = torch.relu(A @ self.l3(h)) + h
        site = 0.5 * (h[:, self.a, :] + h[:, self.b, :])
        return self.head(site).squeeze(-1)          # [S x n_sites]


def site_mask(fd: FarmData) -> torch.Tensor:
    cfg = fd.sc.config_id.to_numpy()
    allowed = {c: set(fd.sc[fd.sc.config_id == c].leak_at) for c in np.unique(cfg)}
    M = np.zeros((len(cfg), len(fd.sites)), dtype=bool)
    for c, ok in allowed.items():
        cols = [i for i, s in enumerate(fd.sites) if s in ok]
        M[np.ix_(cfg == c, cols)] = True
    return torch.tensor(M)


def train_predict(fd: FarmData, sensors: list[str]) -> tuple[np.ndarray, dict]:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    A, elev, site_nodes = graph(fd)
    X = features(fd, sensors, elev)
    y = torch.tensor(fd.site_idx, dtype=torch.long)
    mask = site_mask(fd)
    tr = torch.tensor(np.where(fd.train)[0])
    model = FarmGCN(X.shape[-1], site_nodes)
    opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    for ep in range(EPOCHS):
        model.train()
        opt.zero_grad()
        logits = model(A, X[tr]).masked_fill(~mask[tr], -1e9)
        loss = loss_fn(logits, y[tr])
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        logits = model(A, X).masked_fill(~mask, -1e9)
        P = torch.softmax(logits, dim=1).numpy()
    tr_acc = float((P[fd.train].argmax(1) == fd.site_idx[fd.train]).mean())
    te_acc = float((P[fd.test].argmax(1) == fd.site_idx[fd.test]).mean())
    return P, {"loss": float(loss.detach()), "train_site_acc": round(tr_acc, 3), "test_site_acc": round(te_acc, 3)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sets = sensor_sets()
    for avg in (1, 60):
        fd = load(avg)
        for n, sensors in sets.items():
            P, info = train_predict(fd, sensors)
            np.save(OUT / f"m1_pred_n{n}_a{avg}.npy", P.astype(np.float32))
            print(f"avg={avg:2d} n={n:>2}: {info}")
    print(f"-> {OUT}; now run python -m farm.methods.results")


if __name__ == "__main__":
    main()
