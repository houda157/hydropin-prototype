"""M3 leak locators that need no leak-free *measurement*: time reversal, matched-field, echo.

All three use the transient model of the intact pipe (the "twin") instead of a healthy
recording, and all work on the **residual rate**: d/dt (measured − intact model), low-passed,
muted during the valve closure and limited to the first round trip (see `residual_rate`).

Time reversal (blueprint ref [2], Waqar, Louati & Ghidaoui 2023)
    1. residual rate r'(t) at the sensor (the leak's echoes, as pulses)
    2. back-propagate: inject r'(T − t) at the sensor end of the (linearised) model
    3. imaging: at every position x, correlate the back-propagated field with the incident
       field the valve closure sent through x:  E(x) = Σ_t p_back(x, T−t) · ṗ_inc(x, t)
    The leak re-radiated the incident wave, so the two fields line up only at the leak:
    |E(x)| focuses there. Peak = estimate. This is the zero-lag "imaging condition" form
    of time reversal, on the first round trip; the exact formulation of ref [2] should be
    confirmed with the mentor.

Matched-field processing (fallback, ref [3])
    Simulate a leak at each candidate x with the full model; compare its residual rate with
    the measured one (normalised correlation, Bartlett). Peak = estimate.

Echo
    Time of the strongest pulse in the residual rate: d = a (t − t_close − Tc/2) / 2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt

from m3.moc import PipeSetup, leak_cda_for_fraction, simulate

G = 9.80665
FS = 2000.0
CUTOFF = 60.0          # Hz; a 25 ms closure has little energy above ~40 Hz
A_UNCERTAINTY = 0.12   # window margin: tolerates up to ~±10 % wave-speed error in the model


@dataclass
class LocatorResult:
    x: np.ndarray
    score: np.ndarray      # normalised to max 1
    x_est: float


def measure(setup_true: PipeSetup, fs: float = FS, sigma_m: float = 0.0,
            rng: np.random.Generator | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Sensor trace at the valve, sampled at fs, with Gaussian noise sigma_m (m of head)."""
    t, h = simulate(setup_true).sampled(fs)
    if sigma_m > 0:
        rng = rng or np.random.default_rng(0)
        h = h + rng.normal(0.0, sigma_m, size=h.shape)
    return t, h


def _lowpass(y: np.ndarray, fs: float, cutoff: float, axis: int = 0) -> np.ndarray:
    b, a = butter(4, cutoff / (fs / 2))
    return filtfilt(b, a, y, axis=axis)


def _t_off(model: PipeSetup, a_uncertainty: float) -> float:
    return model.t_close + 2 * model.L * (1 - a_uncertainty) / model.a


def estimate_wave_speed(model: PipeSetup, t: np.ndarray, h: np.ndarray, fs: float = FS,
                        cutoff: float = CUTOFF) -> float:
    """Identify the wave speed from the trace itself: the reservoir return (the surge drops
    back) reaches the sensor at t_close + 2L/a. Uses the time the head crosses halfway
    between the surge plateau and the pre-closure head, after the plateau.
    This is M3's quality index in the blueprint ("identified wave speed")."""
    hf = _lowpass(h, fs, cutoff)
    h0 = hf[t < model.t_close].mean()
    plateau_t = (t > model.t_close + model.Tc + 0.01) & (t < model.t_close + model.Tc + 0.05)
    h_top = hf[plateau_t].mean()
    mid = 0.5 * (h0 + h_top)
    after = t > model.t_close + model.Tc + 0.05
    i = int(np.argmax(after & (hf < mid)))
    t_mid = t[i - 1] + (mid - hf[i - 1]) / (hf[i] - hf[i - 1]) * (t[i] - t[i - 1])
    return float(2 * model.L / (t_mid - model.t_close - model.Tc / 2))


def analysis_window(model: PipeSetup, t: np.ndarray, a_uncertainty: float = A_UNCERTAINTY) -> np.ndarray:
    """Weight 0..1: after the closure, before the earliest possible reservoir return.

    Before t_close + Tc: no echo can have come back yet, and the closure itself differs
    slightly between model and reality (blind zone a·Tc/2 next to the sensor).
    After t_close + 2L (1 − u) / a: the 17 m reservoir return could arrive if the model's
    wave speed is too low by up to ~u. Leaks closer than about u·L to the reservoir are cut.
    """
    t_on = model.t_close + model.Tc + 0.002
    t_off = _t_off(model, a_uncertainty)
    return np.clip((t - t_on) / 0.005, 0, 1) * np.clip((t_off - t) / 0.01, 0, 1)


def residual_rate(model: PipeSetup, t: np.ndarray, h: np.ndarray, fs: float = FS,
                  cutoff: float = CUTOFF, a_uncertainty: float = A_UNCERTAINTY) -> np.ndarray:
    """d/dt (measured − intact model), low-passed and windowed. Offsets drop out."""
    _, h_model = simulate(model.with_(x_leak=None, leak_cda=0.0)).sampled(fs)
    n = min(len(h), len(h_model))
    r = _lowpass(h[:n] - h_model[:n], fs, cutoff)
    return np.gradient(r, 1.0 / fs) * analysis_window(model, t[:n], a_uncertainty)


def _incident_rate(model: PipeSetup, cutoff: float, a_uncertainty: float) -> tuple[np.ndarray, np.ndarray]:
    """ṗ_inc(t, x) of the intact model on the solver grid, low-passed, same time window."""
    m = model.with_(x_leak=None, leak_cda=0.0)
    res = simulate(m, frame_every_s=m.dt)
    p = res.frames - res.frames[0][None, :]
    dp = np.gradient(_lowpass(p, 1.0 / m.dt, cutoff, axis=0), m.dt, axis=0)
    return res.frame_t, dp * np.clip((_t_off(m, a_uncertainty) - res.frame_t) / 0.01, 0, 1)[:, None]


def _back_propagate(model: PipeSetup, src: np.ndarray) -> np.ndarray:
    """Linear frictionless MOC; head src[n] imposed at the sensor end, reservoir h = 0."""
    B = model.a / (G * model.A)
    n_t, n_x = len(src), model.N + 1
    h = np.zeros(n_x)
    q = np.zeros(n_x)
    out = np.empty((n_t, n_x))
    out[0] = h
    for n in range(1, n_t):
        cp = h[:-2] + B * q[:-2]
        cm = h[2:] - B * q[2:]
        hn = np.empty(n_x)
        qn = np.empty(n_x)
        hn[1:-1] = 0.5 * (cp + cm)
        qn[1:-1] = (cp - cm) / (2 * B)
        hn[0] = 0.0
        qn[0] = -(h[1] - B * q[1]) / B
        hn[-1] = src[n]
        qn[-1] = (h[-2] + B * q[-2] - src[n]) / B
        h, q = hn, qn
        out[n] = h
    return out


def time_reversal(model: PipeSetup, t: np.ndarray, h: np.ndarray, fs: float = FS,
                  cutoff: float = CUTOFF, a_uncertainty: float = A_UNCERTAINTY) -> LocatorResult:
    dr = residual_rate(model, t, h, fs, cutoff, a_uncertainty)
    t_inc, dp_inc = _incident_rate(model, cutoff, a_uncertainty)
    dr_solver = np.interp(t_inc, t[:len(dr)], dr)                 # onto the solver grid
    p_back = _back_propagate(model, dr_solver[::-1])              # time-reversed injection
    E = np.abs(np.einsum("tx,tx->x", p_back, dp_inc[::-1]))      # p_back(T−t) · ṗ_inc(t)
    x = np.arange(model.N + 1) * model.dx
    E = np.where((x > 2 * model.dx) & (x < model.L - 2 * model.dx), E, 0.0)
    score = E / E.max() if E.max() > 0 else E
    return LocatorResult(x, score, float(x[np.argmax(score)]))


@dataclass
class ReplicaBank:
    """Model residual rates for a leak at each candidate position (MFP replicas)."""
    x: np.ndarray
    replicas: np.ndarray   # [n_candidates x n_samples]


def mfp_bank(model: PipeSetup, fs: float = FS, cutoff: float = CUTOFF, step_m: float = 1.0,
             leak_fraction: float = 0.05, a_uncertainty: float = A_UNCERTAINTY) -> ReplicaBank:
    t, _ = simulate(model.with_(x_leak=None, leak_cda=0.0)).sampled(fs)
    xs = np.arange(step_m, model.L - step_m / 2, step_m)
    reps = []
    for xc in xs:
        cand = model.with_(x_leak=float(xc), leak_cda=leak_cda_for_fraction(model, leak_fraction, float(xc)))
        _, h_c = simulate(cand).sampled(fs)
        n = min(len(t), len(h_c))
        reps.append(residual_rate(model, t[:n], h_c[:n], fs, cutoff, a_uncertainty))
    n = min(len(r) for r in reps)
    return ReplicaBank(xs, np.array([r[:n] for r in reps]))


def matched_field(model: PipeSetup, t: np.ndarray, h: np.ndarray, fs: float = FS,
                  cutoff: float = CUTOFF, bank: ReplicaBank | None = None,
                  a_uncertainty: float = A_UNCERTAINTY, **bank_kw) -> LocatorResult:
    bank = bank or mfp_bank(model, fs, cutoff, a_uncertainty=a_uncertainty, **bank_kw)
    dr = residual_rate(model, t, h, fs, cutoff, a_uncertainty)
    n = min(len(dr), bank.replicas.shape[1])
    d, R = dr[:n], bank.replicas[:, :n]
    num = (R @ d) ** 2
    den = (R * R).sum(axis=1) * np.dot(d, d)
    scores = np.where(den > 0, num / np.where(den > 0, den, 1.0), 0.0)
    return LocatorResult(bank.x, scores / scores.max(), float(bank.x[np.argmax(scores)]))


def echo_locate(model: PipeSetup, t: np.ndarray, h: np.ndarray, fs: float = FS,
                cutoff: float = CUTOFF, a_uncertainty: float = A_UNCERTAINTY) -> float:
    """Strongest pulse in the residual rate = the echo's mid-ramp (Tc/2 after its onset)."""
    dr = residual_rate(model, t, h, fs, cutoff, a_uncertainty)
    t_peak = t[int(np.argmax(np.abs(dr)))]
    t_echo = t_peak - model.t_close - model.Tc / 2
    return float(model.L - model.a * t_echo / 2)
