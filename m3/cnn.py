"""M3 trained model: 1D CNN that reads the sensor trace and predicts the leak position.

In the spirit of ref [4] (Waqar, Memon, Louati, Ghidaoui et al. 2025, transients with
domain-guided ML). "Domain-guided" here means the input carries physics:
  channel 0: sensor head, pre-closure level removed, scaled by the nominal Joukowsky surge
  channel 1: sensor head − intact-pipe model (nominal), scaled by a typical echo (0.25 m)
The CNN never sees the true wave speed or friction: the training pipes vary around the
nominal model (a ±10 %, friction, leak size), so it learns to cope with model error,
like the other locators.

    python -m m3.cnn data    # simulate clean training traces  -> m3/out/cnn_data.npz (not committed)
    python -m m3.cnn train   # train, noise added on the fly    -> m3/out/cnn.pt + cnn_eval.json
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

from m3.locate import FS
from m3.moc import PipeSetup, joukowsky_head, leak_cda_for_fraction, load_setup, simulate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "m3" / "out"
DATA_PATH = OUT / "cnn_data.npz"
MODEL_PATH = OUT / "cnn.pt"

WINDOW_S = 1.1          # 0 .. t_close + 2L/a_min (a_min = 315 m/s) with margin
N_SAMPLES = int(WINDOW_S * FS)
ECHO_SCALE_M = 0.25
SEED = 20261124

# Training distribution (the "real pipes" around the nominal model)
N_TRAIN_PIPES = 9000
A_RANGE = (0.90, 1.10)            # x nominal wave speed
F_RANGE = (0.015, 0.030)          # Darcy friction
LEAK_FRAC_RANGE = (0.01, 0.10)    # log-uniform
X_RANGE = (3.0, 147.0)
SIGMA_RANGE = (0.003, 0.2)        # m of head, log-uniform; 10 % of batches noise-free


# ----------------------------------------------------------------------------- features
def _trace(setup: PipeSetup) -> np.ndarray:
    _, h = simulate(setup.with_(duration=WINDOW_S + 0.01)).sampled(FS)
    return h[:N_SAMPLES].astype(np.float32)


_REF_CACHE: dict = {}


def reference_trace(model: PipeSetup) -> np.ndarray:
    """Intact-pipe model trace for this model setup (cached)."""
    key = (model.a, model.f, model.L, model.D, model.V0, model.H_res, model.Tc, model.t_close)
    if key not in _REF_CACHE:
        _REF_CACHE[key] = _trace(model.with_(x_leak=None, leak_cda=0.0))
    return _REF_CACHE[key]


def features(h: np.ndarray, h_ref: np.ndarray, model: PipeSetup) -> np.ndarray:
    """[..., 2, N_SAMPLES] input channels from sensor trace(s) h and the model trace."""
    n_pre = int(model.t_close * FS)
    h = h[..., :N_SAMPLES]
    c0 = (h - h[..., :n_pre].mean(axis=-1, keepdims=True)) / joukowsky_head(model)
    r = h - h_ref[:N_SAMPLES]
    c1 = (r - r[..., :n_pre].mean(axis=-1, keepdims=True)) / ECHO_SCALE_M
    return np.stack([c0, c1], axis=-2).astype(np.float32)


# ----------------------------------------------------------------------------- data
def _sample_pipe(args):
    k, nominal = args
    rng = np.random.default_rng([SEED, k])
    a = nominal.a * rng.uniform(*A_RANGE)
    f = rng.uniform(*F_RANGE)
    frac = math.exp(rng.uniform(math.log(LEAK_FRAC_RANGE[0]), math.log(LEAK_FRAC_RANGE[1])))
    x = rng.uniform(*X_RANGE)
    true = nominal.with_(a=a, f=f)
    true = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, frac, x))
    x_actual = round(x / true.dx) * true.dx           # solver snaps the leak to the grid
    return _trace(true), x_actual, a, f, frac


def make_data(n: int = N_TRAIN_PIPES) -> None:
    nominal = load_setup()
    t0 = time.time()
    with mp.Pool(max(1, mp.cpu_count() - 1)) as pool:
        rows = pool.map(_sample_pipe, [(k, nominal) for k in range(n)], chunksize=16)
    X = np.stack([r[0] for r in rows])
    meta = np.array([r[1:] for r in rows], dtype=np.float32)   # x, a, f, frac
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(DATA_PATH, traces=X, meta=meta, ref=reference_trace(nominal))
    print(f"{n} traces x {X.shape[1]} samples in {time.time() - t0:.0f}s -> {DATA_PATH.relative_to(ROOT)}")


# ----------------------------------------------------------------------------- model
def build_net():
    import torch.nn as nn

    def block(cin, cout):
        return nn.Sequential(nn.Conv1d(cin, cout, 7, padding=3), nn.BatchNorm1d(cout), nn.ReLU(),
                             nn.Conv1d(cout, cout, 5, padding=2), nn.BatchNorm1d(cout), nn.ReLU(),
                             nn.MaxPool1d(2))

    return nn.Sequential(
        block(2, 16), block(16, 32), block(32, 32), block(32, 64), block(64, 64), block(64, 64),
        nn.Flatten(),                                    # 64 x (2200 / 64 = 34)
        nn.Linear(64 * (N_SAMPLES // 64), 128), nn.ReLU(), nn.Dropout(0.1),
        nn.Linear(128, 1),                               # x / L
    )


def train(epochs: int = 40, batch: int = 64) -> None:
    import torch

    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, mp.cpu_count() - 1))
    nominal = load_setup()
    d = np.load(DATA_PATH)
    traces, meta, ref = d["traces"], d["meta"], d["ref"]
    n = len(traces)
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(n)
    n_test = n // 6
    n_val = n // 12
    test_i, val_i, train_i = perm[:n_test], perm[n_test:n_test + n_val], perm[n_test + n_val:]
    y_all = meta[:, 0] / nominal.L

    def noisy(idx, gen, fixed_sigma=None):
        h = traces[idx]
        if fixed_sigma is None:
            ls = gen.uniform(np.log(SIGMA_RANGE[0]), np.log(SIGMA_RANGE[1]), size=(len(idx), 1))
            sig = np.exp(ls) * (gen.random((len(idx), 1)) > 0.1)
        else:
            sig = np.full((len(idx), 1), fixed_sigma)
        return h + gen.normal(size=h.shape).astype(np.float32) * sig.astype(np.float32), sig[:, 0]

    net = build_net()
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=epochs * math.ceil(len(train_i) / batch))
    loss_fn = torch.nn.SmoothL1Loss(beta=0.01)
    val_gen = np.random.default_rng([SEED, 1])
    Xv, _ = noisy(val_i, val_gen)
    Xv = torch.from_numpy(features(Xv, ref, nominal))
    yv = torch.from_numpy(y_all[val_i]).float()
    best, best_state = 1e9, None
    t0 = time.time()
    for ep in range(epochs):
        net.train()
        gen = np.random.default_rng([SEED, 100 + ep])
        order = gen.permutation(train_i)
        for b in range(0, len(order), batch):
            idx = order[b:b + batch]
            h, _ = noisy(idx, gen)
            xb = torch.from_numpy(features(h, ref, nominal))
            yb = torch.from_numpy(y_all[idx]).float()
            opt.zero_grad()
            loss = loss_fn(net(xb).squeeze(1), yb)
            loss.backward()
            opt.step()
            sched.step()
        net.eval()
        with torch.no_grad():
            mae = (net(Xv).squeeze(1) - yv).abs().mean().item() * nominal.L
        if mae < best:
            best, best_state = mae, {k: v.clone() for k, v in net.state_dict().items()}
        print(f"epoch {ep + 1:2d}/{epochs}  val MAE {mae:6.2f} m  ({time.time() - t0:.0f}s)", flush=True)
    net.load_state_dict(best_state)
    torch.save({"state_dict": best_state, "n_samples": N_SAMPLES, "fs": FS, "seed": SEED,
                "val_mae_m": best}, MODEL_PATH)

    # held-out test set: never used for training or model selection
    net.eval()
    ev = {"simulation": True, "n_train": int(len(train_i)), "n_val": int(len(val_i)),
          "n_test": int(len(test_i)), "val_mae_m": best, "test_by_sigma": {}}
    test_gen = np.random.default_rng([SEED, 2])
    xs = meta[test_i, 0]
    covered = (xs > 0.12 * nominal.L) & (xs < nominal.L - 5)
    for s in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2):
        h, _ = noisy(test_i, test_gen, fixed_sigma=s)
        with torch.no_grad():
            pred = net(torch.from_numpy(features(h, ref, nominal))).squeeze(1).numpy() * nominal.L
        err = np.abs(pred - xs)
        ev["test_by_sigma"][str(s)] = {"mae_m": float(err.mean()), "mae_covered_m": float(err[covered].mean()),
                                       "within_5m": float((err <= 5).mean())}
    (OUT / "cnn_eval.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
    print(json.dumps(ev["test_by_sigma"], indent=1))


# ----------------------------------------------------------------------------- inference
_NET = None


def load_net():
    global _NET
    if _NET is None:
        import torch
        ck = torch.load(MODEL_PATH, map_location="cpu")
        net = build_net()
        net.load_state_dict(ck["state_dict"])
        net.eval()
        _NET = net
    return _NET


def cnn_locate(model: PipeSetup, t: np.ndarray, h: np.ndarray) -> float:
    """Leak position (m from the reservoir) from a 2 kHz sensor trace."""
    import torch
    x = features(np.asarray(h, dtype=np.float32), reference_trace(model), model)[None]
    with torch.no_grad():
        return float(load_net()(torch.from_numpy(x)).squeeze().item() * model.L)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "data":
        make_data(int(sys.argv[2]) if len(sys.argv) > 2 else N_TRAIN_PIPES)
    elif cmd == "train":
        train(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    else:
        print(__doc__)
