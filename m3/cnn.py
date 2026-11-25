"""M3 trained model: 1D CNN that reads the sensor trace and predicts the leak position.

In the spirit of ref [4] (Waqar, Memon, Louati, Ghidaoui et al. 2025, transients with
domain-guided ML). "Domain-guided" here means the input carries physics, as 5 channels:
  0: sensor head, pre-closure level removed, scaled by the Joukowsky surge a_ref·V0/g
  1: sensor head − intact-pipe reference model, scaled by a typical echo (0.25 m),
     first round trip only (zero after t_close + 2L(1 − 0.12)/a_ref)
  2: residual RATE: d/dt of channel 1, low-passed at 60 Hz, muted until the closure ends,
     scaled by a typical echo rate (5 m/s). Slow model mismatches (creep, friction,
     calibration errors) almost vanish here while the echo stays sharp, the same signal
     time reversal uses (locate.residual_rate)
  3: the creep scale used in that reference (constant channel)
  4: 1 if the reference comes from a field calibration, 0 if not (constant channel)

The reference model comes from one of two routes:
  * calibrated (`calibrate.calibrate`, one leak-free valve test at installation): wave speed,
    friction and creep fitted to the pipe. Most accurate.
  * uncalibrated: wave speed read off the trace itself (`locate.estimate_wave_speed`),
    nominal friction, typical PE creep. Works with no field test, less precisely.
The training pipes cover elastic and creeping walls (creep 0…1.5 × typical, and creep of
other shapes than the model assumes), so one network serves both routes.

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

from m3.calibrate import TYPICAL, creep_scale, with_creep
from m3.locate import CUTOFF, FS, _lowpass, estimate_wave_speed
from m3.moc import G, PipeSetup, leak_cda_for_fraction, load_setup, simulate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "m3" / "out"
DATA_PATH = OUT / "cnn_data.npz"
MODEL_PATH = OUT / "cnn.pt"

WINDOW_S = 1.1          # 0 .. t_close + 2L/a_min (a_min = 315 m/s) with margin
N_SAMPLES = int(WINDOW_S * FS)
ID_WINDOW_S = 1.3       # simulated length (wave-speed identification needs the reservoir return)
ECHO_SCALE_M = 0.25
N_CHANNELS = 5
RATE_SCALE = 5.0       # m/s: a 0.2 m echo rising over the 25 ms closure ramp ~ 8 m/s
WINDOW_U = 0.12        # residual channels end before the earliest reservoir return (a up to ~10 % off)
SEED = 20261125

# Training distribution (the "real pipes")
N_TRAIN_PIPES = 12000
A_RANGE = (0.90, 1.10)            # x nominal wave speed
F_RANGE = (0.015, 0.030)          # Darcy friction
CREEP_RANGE = (0.0, 1.5)          # x typical PE creep compliance
P_ELASTIC = 0.25                  # share of perfectly elastic pipes
P_OTHER_SHAPE = 0.5               # share of creeping pipes whose retardation times differ (x U(0.5, 2) each)
LEAK_FRAC_RANGE = (0.01, 0.10)    # log-uniform
X_RANGE = (3.0, 147.0)
SIGMA_RANGE = (0.003, 0.2)        # m of head, log-uniform; 10 % of samples noise-free
# Reference model errors after a field calibration. Deliberately larger than the
# simulated calibration errors (out/calibration.json: ~0.003 %, 0.4 %, 0.001), because a real
# pipe will not match the model family exactly. Creep 0.1 = the tolerance found in ve_study.
P_CALIBRATED = 0.7
CAL_SD = {"a_rel": 0.01, "f_rel": 0.10, "creep_abs": 0.10}
F_NOMINAL = 0.02


# ----------------------------------------------------------------------------- features
def _trace(setup: PipeSetup) -> np.ndarray:
    _, h = simulate(setup.with_(duration=WINDOW_S + 0.01)).sampled(FS)
    return h[:N_SAMPLES].astype(np.float32)


_REF_CACHE: dict = {}


def reference_trace(model: PipeSetup) -> np.ndarray:
    """Intact-pipe model trace for this model setup (cached)."""
    key = (model.a, model.f, model.L, model.D, model.V0, model.H_res, model.Tc, model.t_close,
           model.ve_J, model.ve_tau)
    if key not in _REF_CACHE:
        _REF_CACHE[key] = _trace(model.with_(x_leak=None, leak_cda=0.0))
    return _REF_CACHE[key]


def features(h, h_ref, model: PipeSetup, a_ref, s_ref, calibrated) -> np.ndarray:
    """[..., 4, N_SAMPLES] input channels.

    h: trace(s); h_ref: matching reference trace(s); a_ref, s_ref, calibrated: scalar or one
    per trace (wave speed and creep scale of the reference, calibration flag)."""
    n_pre = int(model.t_close * FS)
    h = np.asarray(h, dtype=np.float32)[..., :N_SAMPLES]
    batch = h.shape[:-1]

    def col(v):
        return np.broadcast_to(np.asarray(v, dtype=np.float32).reshape(batch + (1,) if batch else ()), batch + (1,))

    jouk = col(a_ref) * model.V0 / G
    c0 = (h - h[..., :n_pre].mean(axis=-1, keepdims=True)) / jouk
    r = h - np.asarray(h_ref, dtype=np.float32)[..., :N_SAMPLES]
    c1 = (r - r[..., :n_pre].mean(axis=-1, keepdims=True)) / ECHO_SCALE_M
    t = np.arange(N_SAMPLES) / FS
    mute = np.clip((t - (model.t_close + model.Tc + 0.002)) / 0.005, 0.0, 1.0)
    # first round trip only (as time reversal): the 17 m reservoir return comes back at
    # t_close + 2L/a; a slightly wrong reference speed would put a huge mismatch there
    t_end = model.t_close + 2 * model.L * (1 - WINDOW_U) / col(a_ref)
    win = np.clip((t_end - t) / 0.01, 0.0, 1.0)
    c1 = c1 * win
    c2 = np.gradient(_lowpass(r, FS, CUTOFF, axis=-1), 1.0 / FS, axis=-1) * mute * win / RATE_SCALE
    c3 = np.broadcast_to(col(s_ref), c0.shape)
    c4 = np.broadcast_to(col(calibrated), c0.shape)
    return np.stack([c0, c1, c2, c3, c4], axis=-2).astype(np.float32)


def uncalibrated_reference(model: PipeSetup, t, h) -> PipeSetup:
    """No field test: wave speed from the trace, nominal friction, typical creep."""
    a_id = estimate_wave_speed(model.with_(ve_J=(), ve_tau=()), t, h)
    return with_creep(model.with_(a=a_id, f=F_NOMINAL, ve_J=(), ve_tau=()), 1.0)


# ----------------------------------------------------------------------------- data
def _sample_pipe(args):
    k, nominal = args
    rng = np.random.default_rng([SEED, k])
    a = nominal.a * rng.uniform(*A_RANGE)
    f = rng.uniform(*F_RANGE)
    elastic = rng.random() < P_ELASTIC
    s = 0.0 if elastic else rng.uniform(*CREEP_RANGE)
    other_shape = (not elastic) and rng.random() < P_OTHER_SHAPE
    tau = tuple(tk * rng.uniform(0.5, 2.0) for tk in TYPICAL.ve_tau) if other_shape else TYPICAL.ve_tau
    frac = math.exp(rng.uniform(math.log(LEAK_FRAC_RANGE[0]), math.log(LEAK_FRAC_RANGE[1])))
    x = rng.uniform(*X_RANGE)
    calibrated = rng.random() < P_CALIBRATED
    e_a, e_f, e_s = rng.normal(0, CAL_SD["a_rel"]), rng.normal(0, CAL_SD["f_rel"]), rng.normal(0, CAL_SD["creep_abs"])

    true = nominal.with_(a=a, f=f)
    if s > 0:
        true = true.with_(ve_J=tuple(j * s for j in TYPICAL.ve_J), ve_tau=tau)
    true = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, frac, x))
    x_actual = round(x / true.dx) * true.dx           # solver snaps the leak to the grid
    t_long, h_long = simulate(true.with_(duration=ID_WINDOW_S)).sampled(FS)

    if calibrated:
        ref_model = with_creep(nominal.with_(a=a * (1 + e_a), f=max(f * (1 + e_f), 1e-3)), max(s + e_s, 0.0))
    else:
        ref_model = uncalibrated_reference(nominal, t_long, h_long)
    ref = reference_trace(ref_model)
    meta = (x_actual, a, f, frac, s, float(other_shape), ref_model.a, ref_model.f,
            creep_scale(ref_model), float(calibrated))
    return h_long[:N_SAMPLES].astype(np.float32), ref, meta


META_COLUMNS = ["x_actual", "a", "f", "leak_fraction", "creep_scale", "other_shape",
                "a_ref", "f_ref", "creep_ref", "calibrated"]


def make_data(n: int = N_TRAIN_PIPES) -> None:
    nominal = load_setup(viscoelastic=False)
    t0 = time.time()
    with mp.Pool(max(1, mp.cpu_count() - 1)) as pool:
        rows = pool.map(_sample_pipe, [(k, nominal) for k in range(n)], chunksize=16)
    X = np.stack([r[0] for r in rows])
    refs = np.stack([r[1] for r in rows])
    meta = np.array([r[2] for r in rows], dtype=np.float32)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(DATA_PATH, traces=X, refs=refs, meta=meta, meta_columns=np.array(META_COLUMNS))
    print(f"{n} traces x {X.shape[1]} samples in {time.time() - t0:.0f}s -> {DATA_PATH.relative_to(ROOT)}; "
          f"elastic {np.mean(meta[:, 4] == 0):.0%}, calibrated {np.mean(meta[:, 9]):.0%}")


# ----------------------------------------------------------------------------- model
def build_net():
    import torch.nn as nn

    def block(cin, cout):
        return nn.Sequential(nn.Conv1d(cin, cout, 7, padding=3), nn.BatchNorm1d(cout), nn.ReLU(),
                             nn.Conv1d(cout, cout, 5, padding=2), nn.BatchNorm1d(cout), nn.ReLU(),
                             nn.MaxPool1d(2))

    return nn.Sequential(
        block(N_CHANNELS, 16), block(16, 32), block(32, 32), block(32, 64), block(64, 64), block(64, 64),
        nn.Flatten(),                                    # 64 x (2200 / 64 = 34)
        nn.Linear(64 * (N_SAMPLES // 64), 128), nn.ReLU(), nn.Dropout(0.1),
        nn.Linear(128, 1),                               # x / L
    )


def train(epochs: int = 40, batch: int = 64) -> None:
    import torch

    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, mp.cpu_count() - 1))
    nominal = load_setup(viscoelastic=False)
    d = np.load(DATA_PATH)
    traces, refs, meta = d["traces"], d["refs"], d["meta"]
    a_ref, s_ref, cal = meta[:, 6], meta[:, 8], meta[:, 9]

    def feats(h, idx):
        return features(h, refs[idx], nominal, a_ref[idx], s_ref[idx], cal[idx])

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
    Xv = torch.from_numpy(feats(Xv, val_i))
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
            xb = torch.from_numpy(feats(h, idx))
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
                "n_channels": N_CHANNELS, "val_mae_m": best}, MODEL_PATH)

    # held-out test set: never used for training or model selection
    net.eval()
    ev = {"simulation": True, "n_train": int(len(train_i)), "n_val": int(len(val_i)),
          "n_test": int(len(test_i)), "val_mae_m": best, "calibration_error_sd": CAL_SD,
          "test_by_sigma": {}}
    test_gen = np.random.default_rng([SEED, 2])
    xs = meta[test_i, 0]
    covered = (xs > 0.12 * nominal.L) & (xs < nominal.L - 5)
    groups = {
        "all": np.ones(len(test_i), bool),
        "calibrated": cal[test_i] == 1, "uncalibrated": cal[test_i] == 0,
        "elastic_pipe": meta[test_i, 4] == 0, "creeping_pipe": meta[test_i, 4] > 0,
        "creep_other_shape": meta[test_i, 5] == 1,
        "creeping_calibrated": (meta[test_i, 4] > 0) & (cal[test_i] == 1),
        "creeping_uncalibrated": (meta[test_i, 4] > 0) & (cal[test_i] == 0),
    }
    for s in (0.0, 0.02, 0.05, 0.1, 0.2):
        h, _ = noisy(test_i, test_gen, fixed_sigma=s)
        with torch.no_grad():
            pred = net(torch.from_numpy(feats(h, test_i))).squeeze(1).numpy() * nominal.L
        err = np.abs(pred - xs)
        ev["test_by_sigma"][str(s)] = {
            g: {"n": int((m & covered).sum()), "mae_covered_m": float(err[m & covered].mean()),
                "within_5m": float((err[m] <= 5).mean())} for g, m in groups.items()}
    (OUT / "cnn_eval.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
    for s, v in ev["test_by_sigma"].items():
        print(s, {g: round(x["mae_covered_m"], 2) for g, x in v.items()})


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


def cnn_locate(model: PipeSetup, t: np.ndarray, h: np.ndarray, calibrated: PipeSetup | None = None) -> float:
    """Leak position (m from the reservoir) from a 2 kHz sensor trace.

    calibrated: the model fitted by `calibrate.calibrate` on a leak-free test of this pipe.
    Without it, the wave speed is read off the trace and typical creep is assumed;
    `model` then only supplies the geometry and operating point (its `a` is not used)."""
    import torch
    if calibrated is not None:
        ref_model, flag = calibrated.with_(x_leak=None, leak_cda=0.0), 1.0
    else:
        ref_model, flag = uncalibrated_reference(model, t, h), 0.0
    x = features(h, reference_trace(ref_model), model, ref_model.a, creep_scale(ref_model), flag)[None]
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
