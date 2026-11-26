"""M1 – graph neural network on the pipe graph. Math note §4.2.

Graph: the farm's junction nodes (source excluded); edges = pipes. Leak
locations = pipes (edge head) + lateral blocks (node head, leaks inside laterals).

Node features x_i = [r_i/σ_tot, sensor mask, z_i, sector-open flag, Δq/q]
where r_i is the change of the compensated window-mean pressure vs the last
healthy irrigation of the same shift (the residual of §4.2, taken against the
healthy baseline as established for M2), 0 where there is no sensor.

GCN layer (§4.2):  H⁽ˡ⁺¹⁾ = ReLU( D̂^{-1/2} Â D̂^{-1/2} H⁽ˡ⁾ W⁽ˡ⁾ ),  Â = A + I
Edge head:         p_e = σ( wᵀ [h_u ‖ h_v ‖ x_e] + b )
Block head:        p_b = σ( w_bᵀ [h_b ‖ x_b] + b_b )
Loss:              weighted BCE, w₊ = #healthy/#leaky per location (§4.2)
Transfer learning: L_ft = L_real + λ ‖θ − θ_sim‖²  (fine_tune)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import torch
from torch import nn

from hydropin_sim.contracts import MethodOutput, NetworkSpec


@dataclass
class GraphInfo:
    nodes: list[str]
    edges: list[tuple[int, int]]
    edge_ids: list[str]
    blocks: list[int]               # node indices of lateral blocks
    block_ids: list[str]
    a_hat: torch.Tensor             # normalised adjacency (V, V)
    z: np.ndarray
    sector_of_node: list[Optional[str]]

    @property
    def locations(self) -> list[str]:
        return self.edge_ids + self.block_ids


def build_graph(spec: NetworkSpec) -> GraphInfo:
    nodes = [n.id for n in spec.nodes if n.kind.value != "source"]
    ix = {n: i for i, n in enumerate(nodes)}
    edges, eids = [], []
    for p in spec.pipes:
        if p.start in ix and p.end in ix:
            edges.append((ix[p.start], ix[p.end]))
            eids.append(p.id)
    V = len(nodes)
    A = torch.zeros(V, V)
    for u, v in edges:
        A[u, v] = A[v, u] = 1.0
    A = A + torch.eye(V)
    d = A.sum(1)
    a_hat = A / torch.sqrt(d[:, None] * d[None, :])
    blocks = [ix[b.node] for b in spec.lateral_blocks]
    sec = {}
    for s in spec.sectors:
        k = s.id[-1]
        for b in s.lateral_blocks:
            sec[b] = s.id
        sec[f"S{k}"] = s.id
    z = np.array([next(n.z for n in spec.nodes if n.id == nid) for nid in nodes])
    return GraphInfo(nodes, edges, eids, blocks, [nodes[b] for b in blocks], a_hat, z,
                     [sec.get(n) for n in nodes])


def node_features(g: GraphInfo, dp: np.ndarray, dq: np.ndarray, sensor_nodes: Sequence[str],
                  open_sectors: Sequence[Sequence[str]], sigma: float) -> np.ndarray:
    """(N, V, 5) feature tensor. dp: (N, S) pressure change at the sensors (m), dq: (N,) relative flow change."""
    N, V = dp.shape[0], len(g.nodes)
    X = np.zeros((N, V, 5), np.float32)
    ix = {n: i for i, n in enumerate(g.nodes)}
    for k, s in enumerate(sensor_nodes):
        X[:, ix[s], 0] = np.nan_to_num(dp[:, k] / sigma)
        X[:, ix[s], 1] = 1.0
    X[:, :, 2] = (g.z - g.z.mean()) / (g.z.std() + 1e-9)
    for n in range(N):
        for v, sec in enumerate(g.sector_of_node):
            X[n, v, 3] = 1.0 if (sec is None or sec in open_sectors[n]) else 0.0
    X[:, :, 4] = (dq * 100.0)[:, None]          # % flow change, broadcast to every node
    return X


class GCN(nn.Module):
    def __init__(self, g: GraphInfo, n_in: int = 5, hidden: int = 48, layers: int = 3):
        super().__init__()
        self.register_buffer("a_hat", g.a_hat)
        self.register_buffer("eu", torch.tensor([u for u, _ in g.edges]))
        self.register_buffer("ev", torch.tensor([v for _, v in g.edges]))
        self.register_buffer("bk", torch.tensor(g.blocks))
        dims = [n_in] + [hidden] * layers
        self.lin = nn.ModuleList([nn.Linear(a, b) for a, b in zip(dims[:-1], dims[1:])])
        self.edge_head = nn.Sequential(nn.Linear(2 * hidden + 2 * n_in, hidden), nn.ReLU(), nn.Linear(hidden, 1))
        self.block_head = nn.Sequential(nn.Linear(hidden + n_in, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (N, V, F) → logits (N, n_edges + n_blocks)."""
        h = x
        for lin in self.lin:
            h = torch.relu(self.a_hat @ lin(h))          # D^-1/2 Â D^-1/2 H W
        he = torch.cat([h[:, self.eu], h[:, self.ev], x[:, self.eu], x[:, self.ev]], dim=-1)
        hb = torch.cat([h[:, self.bk], x[:, self.bk]], dim=-1)
        return torch.cat([self.edge_head(he)[..., 0], self.block_head(hb)[..., 0]], dim=-1)


def labels(g: GraphInfo, leak_id: np.ndarray) -> np.ndarray:
    loc = {n: i for i, n in enumerate(g.locations)}
    Y = np.zeros((len(leak_id), len(loc)), np.float32)
    for n, lid in enumerate(leak_id):
        if lid:
            Y[n, loc[str(lid)]] = 1.0
    return Y


def train(model: GCN, X: np.ndarray, Y: np.ndarray, X_val: np.ndarray, Y_val: np.ndarray,
          epochs: int = 300, lr: float = 3e-3, seed: int = 0, theta_ref: Optional[dict] = None,
          lam: float = 0.0, verbose: bool = False) -> list[float]:
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    Xt, Yt = torch.tensor(X), torch.tensor(Y)
    Xv, Yv = torch.tensor(X_val), torch.tensor(Y_val)
    pos = Yt.sum(0).clamp(min=1.0)
    w_pos = ((len(Yt) - pos) / pos).clamp(max=200.0)          # w+ = #healthy / #leaky per location
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=w_pos)
    best, best_state, hist = np.inf, None, []
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xt))
        for b in range(0, len(Xt), 128):
            i = perm[b:b + 128]
            opt.zero_grad()
            loss = loss_fn(model(Xt[i]), Yt[i])
            if theta_ref is not None and lam > 0:
                loss = loss + lam * sum(((p - theta_ref[n]) ** 2).sum() for n, p in model.named_parameters())
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(loss_fn(model(Xv), Yv))
        hist.append(vl)
        if vl < best:
            best, best_state = vl, {k: v.clone() for k, v in model.state_dict().items()}
        if verbose and ep % 50 == 0:
            print(ep, vl)
    model.load_state_dict(best_state)
    return hist


def fine_tune(model: GCN, X: np.ndarray, Y: np.ndarray, X_val, Y_val, lam: float = 1e-2, epochs: int = 100):
    """Transfer learning on a few real staged leaks: L_ft = L_real + λ‖θ − θ_sim‖² (§4.2)."""
    ref = {n: p.detach().clone() for n, p in model.named_parameters()}
    return train(model, X, Y, X_val, Y_val, epochs=epochs, lr=1e-3, theta_ref=ref, lam=lam)


def predict(model: GCN, X: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        return torch.sigmoid(model(torch.tensor(X))).numpy()


def to_output(g: GraphInfo, p: np.ndarray, threshold: float, block_to_pipe: dict[str, str]) -> MethodOutput:
    """Score = 1 − Π(1 − p_e) (any location leaking); location map normalised over locations."""
    s = float(1.0 - np.prod(1.0 - p))
    s_cal = float(1.0 / (1.0 + np.exp(-8 * (s - threshold))))
    w = p / p.sum() if p.sum() > 0 else np.full_like(p, 1.0 / len(p))
    loc: dict[str, float] = {}
    for name, wi in zip(g.locations, w):
        pipe = block_to_pipe.get(name, name)
        loc[pipe] = loc.get(pipe, 0.0) + float(wi)
    return MethodOutput("M1", s_cal, loc, quality=threshold, quality_ok=True, details=dict(raw=s))
