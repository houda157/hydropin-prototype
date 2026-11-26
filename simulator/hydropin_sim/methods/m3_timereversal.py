"""M3 – transient time reversal / matched-field localisation. Math note §5.8–5.9.

Inputs: one high-rate pressure record at the excitation valve, the known valve
manoeuvre, and a frequency-domain model of the line (no leak-free baseline
needed: the intact MODEL is the reference).

Steps (all on the Laplace line Re(s) = σ):
1. Y_m(s)  : measured head change after the pulse
2. U(s)    : forced valve-flow perturbation (from the closure law)
3. R(s)    = Y_m(s) − H_intact(s) U(s)       (what the intact model cannot explain)
4. G(x, s) = (H_leak(x, ΔY) − H_intact) U(s)  (signature of a small leak at x)
5. J(x)    = |Σ R* G|² / (Σ|R|² Σ|G|²);  x̂ = argmax J
6. Ŷ_L     = ΔY · Re⟨G(x̂), R⟩ / ‖G(x̂)‖²       (leak admittance, linear in Y_L)
7. a_id    = 2 L / t_res  from the first reflection of the reservoir (quality check)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np

from hydropin_sim.contracts import MethodOutput
from hydropin_sim.transient.frequency import LineModel, laplace, response

DY_PROBE = 1e-7     # small probe admittance used to build the leak signatures (m2/s)


@dataclass
class M3Result:
    x_hat: float
    y_hat: float
    j: np.ndarray
    x_grid: np.ndarray
    snr: float               # leak-explained residual vs noise, in multiples of the noise
    a_id: float
    fit_time: np.ndarray = field(default_factory=lambda: np.empty(0))
    residual_time: np.ndarray = field(default_factory=lambda: np.empty(0))
    model_time: np.ndarray = field(default_factory=lambda: np.empty(0))


def identify_wave_speed(tt: np.ndarray, yy: np.ndarray, length: float, smooth: float = 0.005) -> float:
    """a_id = 2L / (time between the pulse front and the return of the upstream reflection). Math note §5.9 step 5."""
    dt = float(tt[1] - tt[0])
    w = max(3, int(round(smooth / dt)))
    ys = np.convolve(yy, np.ones(w) / w, mode="same")
    dy = np.gradient(ys, dt)
    thr = 0.3 * float(np.max(np.abs(dy)))
    over = np.where(np.abs(dy) > thr)[0]
    if len(over) == 0:
        return float("nan")
    win = int(0.015 / dt)

    def peak(i_first):            # steepest point of the front that starts at i_first
        seg = slice(i_first, min(i_first + win, len(dy)))
        return i_first + int(np.argmax(np.abs(dy[seg])))

    i0 = peak(int(over[0]))
    sign0 = np.sign(dy[i0])
    later = np.where((np.arange(len(dy)) > i0 + int(0.05 / dt)) & (-sign0 * dy > thr))[0]
    if len(later) == 0:
        return float("nan")
    i1 = peak(int(later[0]))
    return 2 * length / (tt[i1] - tt[i0])


def _invlap(F: np.ndarray, tt: np.ndarray, sigma: float, n: int) -> np.ndarray:
    dt = float(tt[1] - tt[0])
    return np.fft.irfft(F, n=n)[:len(tt)] / dt * np.exp(sigma * (tt - tt[0]))


def _highpass(x: np.ndarray, w: int) -> np.ndarray:
    """x minus its centred moving average over w samples: removes slow model mismatch."""
    k = np.ones(w) / w
    return x - np.convolve(x, k, mode="same")


def localise(t: np.ndarray, y: np.ndarray, t0: float, u: np.ndarray, model: LineModel,
             dx: float = 0.25, noise_sd: Optional[float] = None, sigma: Optional[float] = None,
             t_window: Optional[float] = None, tau_sensor: float = 0.0, gate: float = 0.03,
             hp_window: float = 0.02, calibrate: bool = True, model_floor: float = 0.0015) -> M3Result:
    """Time reversal / matched-field localisation of one leak on a single line.

    The comparison is done in the time domain on the Laplace-inverted model, which
    is the time-reversal form of math note §5.9 (correlating the time-reversed
    measurement with the model = the normalised inner product J(x)). Two practical
    guards: the pulse itself is gated out (first `gate` seconds after t0, blind
    zone a·gate/2 next to the valve), and slow model mismatch is removed with a
    high-pass (moving average over `hp_window`). The SNR uses the noise PLUS a
    model-mismatch floor (`model_floor`, m): below it, the linear model itself
    is the limit, not the sensor (measured in the M3 study on healthy lines).
    """
    dt = float(t[1] - t[0])
    pre = t < t0
    y0 = float(np.mean(y[pre][-max(10, int(0.02 / dt)):]))
    if noise_sd is None:
        noise_sd = float(np.std(y[pre])) if pre.sum() > 20 else 0.0
    keep = t >= t0 - 0.01
    if t_window is not None:
        keep &= t <= t0 + t_window
    tt, yy, uu = t[keep], y[keep] - y0, u[keep]
    a_id = identify_wave_speed(tt, yy, model.length)
    if calibrate and np.isfinite(a_id) and abs(a_id / model.a - 1) < 0.15:
        model = replace(model, a=a_id)             # use the wave speed measured in the field
    T = tt[-1] - tt[0]
    sigma = 3.0 / T if sigma is None else sigma
    n = 2 * len(tt)
    s, _ = laplace(tt, yy, sigma, n_fft=n)
    _, U = laplace(tt, uu, sigma, n_fft=n)
    lag = 1.0 / (1.0 + s * tau_sensor)            # sensor response (math note §3.2)
    H0 = response(model, s) * lag
    y_model = _invlap(H0 * U, tt, sigma, n)
    w = max(3, int(round(hp_window / dt)))
    t_round = 2 * model.length / model.a              # every leak echo arrives within one round trip
    g_mask = (tt > t0 + gate) & (tt < t0 + t_round - gate / 3)
    r = _highpass(yy - y_model, w)[g_mask]
    xs = np.arange(dx, model.length - dx / 2, dx)
    J = np.empty(len(xs))
    corr = np.empty(len(xs))
    gnorm = np.empty(len(xs))
    sigs = []
    for i, x in enumerate(xs):
        g_full = _invlap((response(model, s, [(x, DY_PROBE)]) * lag - H0) * U, tt, sigma, n)
        g = _highpass(g_full, w)[g_mask]
        c = float(np.dot(r, g))
        gn = float(np.dot(g, g))
        J[i] = c * c / (float(np.dot(r, r)) * gn + 1e-300)
        corr[i], gnorm[i] = c, gn
        sigs.append(g_full)
    # a leak can only lower the echo sign we expect: keep correlations of the right sign
    J_signed = np.where(corr > 0, J, 0.0)
    k = int(np.argmax(J_signed)) if J_signed.max() > 0 else int(np.argmax(J))
    y_hat = float(DY_PROBE * corr[k] / gnorm[k])
    sd = float(np.hypot(noise_sd, model_floor))
    snr = float(corr[k] / np.sqrt(gnorm[k]) / sd)
    return M3Result(float(xs[k]), y_hat, J_signed, xs, snr, a_id, fit_time=tt,
                    residual_time=yy - y_model, model_time=sigs[k])


def to_output(res: M3Result, pipe_id: str, kappa: float, a_model: float) -> MethodOutput:
    """MethodOutput for fusion: score from the SNR, quality from the wave-speed check."""
    score = float(1.0 / (1.0 + np.exp(-(res.snr - kappa))))
    q = float(abs(res.a_id / a_model - 1)) if np.isfinite(res.a_id) else 1.0
    return MethodOutput("M3", score, {pipe_id: 1.0}, quality=q, quality_ok=q < 0.05,
                        details=dict(x_hat=res.x_hat, y_hat=res.y_hat, snr=res.snr, a_id=res.a_id))
