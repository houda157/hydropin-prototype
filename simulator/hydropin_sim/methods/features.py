"""Turning raw sensor windows into method features (shared by M1 and M2).

Math note §3.1/§3.3: readings are zeroed (bias removed at installation),
temperature-compensated with the measured box temperature (a fraction ρ_T of
the drift remains), and averaged over the last N_AVG readings of the window.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.sensors.model import full_scale_m


def compensate(X: np.ndarray, temp: np.ndarray, bias: np.ndarray, P: Params) -> np.ndarray:
    """Zeroing + temperature compensation of readings X (N, S, T) with box temperature (N, T)."""
    s = P.sensors
    drift = (1 - s.TEMP_COMP_RESIDUAL.v) * s.TEMPCO.v * full_scale_m(P) * temp[:, None, :]
    return X - bias[None, :, None] - drift


def window_mean(X: np.ndarray, n_avg: int) -> np.ndarray:
    """Mean of the last n_avg readings (NaN-safe: lost packets ignored)."""
    with np.errstate(all="ignore"):
        return np.nanmean(X[..., -n_avg:], axis=-1)


@dataclass
class Features:
    p: np.ndarray            # (N, S) compensated window-mean pressure heads
    q: np.ndarray            # (N,)   window-mean pump flow
    dp: np.ndarray           # (N, S) change vs the paired healthy baseline (same shift, other day)
    dq: np.ndarray           # (N,)   relative flow change vs the baseline
    shift: np.ndarray        # (N,)
    leak: np.ndarray         # (N,) bool
    leak_id: np.ndarray
    leak_kind: np.ndarray
    leak_frac: np.ndarray    # leak flow / pump flow
    leak_xy: np.ndarray


def make_features(ds: dict, P: Params, n_avg: Optional[int] = None) -> Features:
    n = int(P.decision.N_AVG.v) if n_avg is None else n_avg
    Xc = compensate(ds["X"].astype(float), ds["TEMP"].astype(float), ds["sensor_bias"], P)
    p = window_mean(Xc, n)
    q = window_mean(ds["Q"].astype(float), n)
    Xb = compensate(ds["X_BASE"].astype(float), ds["TEMP_BASE"].astype(float), ds["sensor_bias"], P)
    pb = window_mean(Xb, n)
    qb = window_mean(ds["Q_BASE"].astype(float), n)
    leak = ds["LEAK_KIND"] > 0
    frac = np.where(leak, ds["LEAK_FLOW"] / ds["Q_TRUE"], 0.0)
    return Features(p, q, p - pb, q / qb - 1.0, ds["SHIFT"].astype(int), leak, ds["LEAK_ID"], ds["LEAK_KIND"], frac, ds["LEAK_XY"])


def split(n: int, seed: int = 0, frac=(0.6, 0.2, 0.2)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    a = int(frac[0] * n)
    b = a + int(frac[1] * n)
    return idx[:a], idx[a:b], idx[b:]
