"""M2 experiment on the simulated dataset: train per shift on healthy windows, test on everything else."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from hydropin_sim.methods import m2_pca as m2
from hydropin_sim.methods.features import make_features, split
from hydropin_sim.methods.signatures import location_xy, shift_signatures
from hydropin_sim.network.generators import demo_farm_spec
from hydropin_sim.sensors.dataset import load
from oracles.transient_cases import P

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "farm_dataset.npz"
FARM = demo_farm_spec()


@lru_cache(maxsize=1)
def dataset():
    if not DATA.exists():
        raise FileNotFoundError("run run/sensors.py first (creates data/farm_dataset.npz)")
    return load(DATA)


@lru_cache(maxsize=1)
def experiment():
    ds = dataset()
    F = make_features(ds, P)
    n = len(F.shift)
    tr, va, te = split(n, seed=0)
    shifts = [tuple(s.split("+")) for s in ds["shifts"]]
    sensors = list(ds["sensor_nodes"])
    models, sig_cache = {}, {}
    q_scale = 0.01           # 1 % flow change ~ 1 unit (features are already changes)
    for si, sh in enumerate(shifts):
        rows_tr = tr[(F.shift[tr] == si) & ~F.leak[tr]]
        rows_va = va[(F.shift[va] == si) & ~F.leak[va]]
        used = np.where(np.median(F.p[rows_tr], axis=0) > 1.0)[0]     # pressurised sensors in this shift
        # features = change vs the last healthy irrigation of the same shift
        X = lambda rows, used=used: np.c_[F.dp[rows][:, used], F.dq[rows] / q_scale]  # noqa: E731
        mdl = m2.fit_shift(X(rows_tr), X(rows_va), "+".join(sh), used)
        names, dp, dq = shift_signatures(FARM, P, sh, sensors)
        q_nom = float(np.median(F.q[rows_tr]))
        m2.set_signatures(mdl, names, np.c_[dp[:, used], dq / q_nom / q_scale])
        models[si] = (mdl, X)
    # evaluate on the test split
    rows = te
    res = []
    for i in rows:
        mdl, X = models[F.shift[i]]
        x = X(np.array([i]))
        best, p = m2.localise(mdl, x)
        res.append((i, m2.alarm_ratio(mdl, x), best))
    idx = np.array([r[0] for r in res])
    ratio = np.array([r[1] for r in res])
    best = np.array([r[2] for r in res])
    return dict(F=F, models=models, idx=idx, ratio=ratio, best=best, shifts=shifts, sensors=sensors)


def localisation_error_m(name_true: str, name_pred: str, xy_true) -> float:
    if not np.all(np.isfinite(xy_true)):
        return float("nan")
    x, y = location_xy(FARM, name_pred)
    return float(np.hypot(x - xy_true[0], y - xy_true[1]))
