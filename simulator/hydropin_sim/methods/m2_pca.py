"""M2 – PCA/SVD subspace detection and signature localisation. Math note §4.1.

One model per irrigation shift ("one normal per configuration", §4.1 warning).
Features of a decision window: temperature-compensated, zeroed pressure heads
of the sensors that are pressurised in that shift (window mean of the last
N_AVG readings), plus the pump flow. Standardised with the healthy mean and
standard deviation, then:

    X̃ = U Σ Vᵀ,  P_k = V_k V_kᵀ,  r = (I − P_k) x̃,  SPE = ‖r‖²,  T² = Σ t_j²/λ_j
    alarm if SPE > SPE_99 (99th percentile of healthy validation windows)
    ℓ* = argmax_ℓ  rᵀ (I−P_k) s_ℓ / (‖r‖ ‖(I−P_k) s_ℓ‖)

Leak signatures s_ℓ come from the digital twin (a nominal leak at every
candidate location of the shift), standardised the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from hydropin_sim.contracts import MethodOutput


@dataclass
class ShiftModel:
    shift: str
    sensors: np.ndarray            # indices of the sensors used
    mu: np.ndarray
    sd: np.ndarray
    V: np.ndarray                  # (d, k)
    lam: np.ndarray                # (k,)
    spe99: float
    explained: float
    t2_99: float = np.inf
    locations: list[str] = field(default_factory=list)
    signatures: Optional[np.ndarray] = None    # (n_loc, d) standardised, projected on residual space

    def standardise(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mu) / self.sd

    def residual(self, xs: np.ndarray) -> np.ndarray:
        return xs - (xs @ self.V) @ self.V.T

    def spe(self, x: np.ndarray) -> np.ndarray:
        r = self.residual(self.standardise(np.atleast_2d(x)))
        return np.sum(r ** 2, axis=1)

    def t2(self, x: np.ndarray) -> np.ndarray:
        t = self.standardise(np.atleast_2d(x)) @ self.V
        return np.sum(t ** 2 / self.lam, axis=1)


def fit_shift(X_healthy: np.ndarray, X_val: np.ndarray, shift: str, sensors: np.ndarray,
              q: float = 99.0, floor_factor: float = 2.0) -> ShiftModel:
    """k = number of components standing above the noise floor (λ_j > floor_factor × median λ).

    When the healthy variation is low-rank (drift along a few directions) this keeps
    those directions, as the "90–95 % of variance" rule of §4.1 would; when it is
    isotropic noise, k = 0 and the residual is the whole standardised change.
    Alarm: SPE > SPE_q  or  T² > T²_q (each at q' = (100+q)/2 so the pair is ≈ q).
    """
    mu = X_healthy.mean(axis=0)
    sd = X_healthy.std(axis=0) + 1e-12
    Xs = (X_healthy - mu) / sd
    U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
    lam = S ** 2 / (len(Xs) - 1)
    cum = np.cumsum(lam) / lam.sum()
    k = int(np.sum(lam > floor_factor * np.median(lam)))
    V = Vt[:k].T
    m = ShiftModel(shift, sensors, mu, sd, V, lam[:k], 0.0, float(cum[k - 1]) if k else 0.0)
    qq = (100.0 + q) / 2
    m.spe99 = float(np.percentile(m.spe(X_val), qq))
    m.t2_99 = float(np.percentile(m.t2(X_val), qq)) if k else np.inf
    return m


def alarm_ratio(m: ShiftModel, x: np.ndarray) -> float:
    """max(SPE/SPE_q, T²/T²_q): > 1 means alarm."""
    r = float(m.spe(x)[0] / m.spe99)
    if m.V.shape[1]:
        r = max(r, float(m.t2(x)[0] / m.t2_99))
    return r


def set_signatures(m: ShiftModel, locations: list[str], deltas: np.ndarray) -> None:
    """deltas: (n_loc, d) raw feature change caused by a nominal leak at each location."""
    s = deltas / m.sd
    m.locations = list(locations)
    m.signatures = s - (s @ m.V) @ m.V.T


def localise(m: ShiftModel, x: np.ndarray, beta: float = 25.0) -> tuple[str, np.ndarray]:
    """Cosine of the residual with each projected signature; softmax(β·cos) as location map."""
    r = m.residual(m.standardise(np.atleast_2d(x)))[0]
    S = m.signatures
    cos = S @ r / (np.linalg.norm(S, axis=1) * np.linalg.norm(r) + 1e-300)
    p = np.exp(beta * (cos - cos.max()))
    p /= p.sum()
    return m.locations[int(np.argmax(cos))], p


def score(m: ShiftModel, x: np.ndarray, steepness: float = 4.0) -> float:
    """s₂ in [0, 1]: 0.5 at the alarm threshold, logistic in log(alarm ratio)."""
    ratio = alarm_ratio(m, x)
    return float(1.0 / (1.0 + np.exp(-steepness * np.log(max(ratio, 1e-12)))))


def to_output(m: ShiftModel, x: np.ndarray, location_to_pipe: dict[str, str]) -> MethodOutput:
    s = score(m, x)
    best, p = localise(m, x)
    loc: dict[str, float] = {}
    for name, pi in zip(m.locations, p):
        pipe = location_to_pipe.get(name, name)
        loc[pipe] = loc.get(pipe, 0.0) + float(pi)
    fa = getattr(m, "val_false_alarm", 0.01)
    return MethodOutput("M2", s, loc, quality=fa, quality_ok=fa <= 0.03,
                        details=dict(spe=float(m.spe(x)[0]), spe99=m.spe99, best=best))
