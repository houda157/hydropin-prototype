"""Virtual sensors. Math note §3 (and §2.7 for the flow meter).

A LowRateSensor is created once per physical sensor: its gain error, bias and
ageing-drift direction are drawn at creation (they belong to the device), then
`read` turns exact pressure heads into what the device would report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import SensorSeries

M_PER_BAR = 10.197          # metres of water per bar (rho = 998.2, g = 9.81)
SECONDS_PER_YEAR = 3.15576e7


def full_scale_m(P: Params) -> float:
    """F_S in metres of water = FS_BAR × 10.197. Math note §3.1."""
    return P.sensors.FS_BAR.v * M_PER_BAR


def box_temperature(t, t_amp, phase=0.25, t_mean=0.0):
    """ΔT(t) = T_amp sin(2π (t/86400 − φ)). Math note §3.1. t in s since midnight."""
    return t_mean + t_amp * np.sin(2 * np.pi * (np.asarray(t, dtype=float) / 86400.0 - phase))


@dataclass
class LowRateSensor:
    sensor_id: str
    node_id: str
    gain: float          # γ_i
    bias: float          # b_i (m)
    drift_sign: float    # ±1
    age_years: float = 0.0

    @classmethod
    def create(cls, sensor_id: str, node_id: str, P: Params, rng: np.random.Generator,
               age_years: float = 0.0) -> "LowRateSensor":
        acc = P.sensors.ACC.v
        fs = full_scale_m(P)
        return cls(sensor_id, node_id,
                   gain=float(rng.normal(0.0, acc / 2)),
                   bias=float(rng.normal(0.0, acc * fs / 2)),
                   drift_sign=float(rng.choice([-1.0, 1.0])),
                   age_years=age_years)

    def read(self, h_true, t, P: Params, rng: np.random.Generator,
             temp_offset: Optional[np.ndarray] = None) -> SensorSeries:
        """y = (1+γ) h + b + α_T F_S ΔT + β F_S t_age + ε, quantised, with packet loss. Math note §3.1."""
        s = P.sensors
        fs = full_scale_m(P)
        h_true = np.broadcast_to(np.asarray(h_true, dtype=float), np.shape(t)).copy()
        dT = box_temperature(t, s.T_AMP.v) if temp_offset is None else np.asarray(temp_offset)
        age = self.age_years + np.asarray(t, dtype=float) / SECONDS_PER_YEAR
        y = ((1 + self.gain) * h_true + self.bias + s.TEMPCO.v * fs * dT
             + self.drift_sign * s.DRIFT_YR.v * fs * age
             + rng.normal(0.0, s.SIGMA_N.v * fs, size=h_true.shape))
        dq = fs / 2 ** int(s.ADC_BITS.v)
        y = dq * np.round(y / dq)
        y[rng.random(y.shape) < s.LOSS_RATE.v] = np.nan
        return SensorSeries(self.sensor_id, self.node_id, np.asarray(t, dtype=float), y,
                            meta=dict(temp=dT))


def read_flow(q_true, rng: np.random.Generator, P: Params):
    """Flow meter: Q̂ = Q (1 + ε_Q), ε_Q ~ N(0, σ_Q²). Math note §2.7."""
    q_true = np.asarray(q_true, dtype=float)
    return q_true * (1.0 + rng.normal(0.0, P.sensors.SIGMA_Q.v, size=q_true.shape))


def sigma_total(P: Params, compensated: bool = True, n_avg: Optional[int] = None) -> float:
    """σ_tot of a change in pressure head over a decision window. Math note §3.3.

    σ_tot² = (σ_ε F_S)² / n_avg + σ_drift²,  σ_drift = ρ_T α_T F_S T_amp / √2.
    Bias and gain cancel after zeroing at installation (a leak is judged as a change).
    """
    s = P.sensors
    fs = full_scale_m(P)
    n = P.decision.N_AVG.v if n_avg is None else n_avg
    rho = s.TEMP_COMP_RESIDUAL.v if compensated else 1.0
    drift = rho * s.TEMPCO.v * fs * s.T_AMP.v / np.sqrt(2)
    return float(np.sqrt((s.SIGMA_N.v * fs) ** 2 / n + drift ** 2))


def detectable(delta_h, sigma_tot: float, kappa: float) -> np.ndarray:
    """|h^(ℓ) − h^(0)| > κ σ_tot. Math note §3.3."""
    return np.abs(np.asarray(delta_h)) > kappa * sigma_tot


@dataclass
class HighRateSensor:
    """M3 sensor: first-order lag, sampling at f_s with a GPS time offset. Math note §3.2."""
    sensor_id: str
    node_id: str
    time_offset: float

    @classmethod
    def create(cls, sensor_id: str, node_id: str, P: Params, rng: np.random.Generator):
        return cls(sensor_id, node_id, float(rng.normal(0.0, P.sensors.SIGMA_SYNC.v)))

    def read(self, t_model, h_model, P: Params, rng: np.random.Generator,
             duration: Optional[float] = None, noise_m: float = 0.0) -> SensorSeries:
        s = P.sensors
        tau, fs = s.TAU_SENS.v, s.FS_HIGH.v
        t_model = np.asarray(t_model, dtype=float)
        h_model = np.asarray(h_model, dtype=float)
        # first-order lag, exact discretisation on the model grid
        y = np.empty_like(h_model)
        y[0] = h_model[0]
        for k in range(1, len(h_model)):
            a = np.exp(-(t_model[k] - t_model[k - 1]) / tau)
            y[k] = a * y[k - 1] + (1 - a) * h_model[k]
        t_end = t_model[-1] if duration is None else duration
        t_s = np.arange(0.0, t_end, 1.0 / fs)
        values = np.interp(t_s + self.time_offset, t_model, y)
        if noise_m > 0:
            values = values + rng.normal(0.0, noise_m, size=values.shape)
        return SensorSeries(self.sensor_id, self.node_id, t_s, values, kind="high_rate",
                            meta=dict(time_offset=self.time_offset))
