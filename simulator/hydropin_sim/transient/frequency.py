"""Frequency-domain (Laplace) model of a single line. Math note §5.8.

State [h, q] (head and flow perturbations) is propagated from the upstream end
(x = 0) to the valve (x = L) with pipe transfer matrices and point matrices
(leaks). Everything is evaluated at complex frequencies s = σ + iω so that
records that do not decay (little friction) can still be matched: multiplying
a time signal by e^{-σt} before the FFT equals evaluating its Laplace transform
on the line Re(s) = σ.

Upstream boundary:  reservoir (h_0 = 0)  or  pump/admittance (q_0 = -Y_up h_0).
Valve boundary:     q_L = Y_v h_L + u  (u = forced valve-flow perturbation).
Head response at the valve:  H(s) = h_L / u = w_1 / (w_2 - Y_v w_1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass
class LineModel:
    length: float
    d: float
    a: float                      # elastic wave speed (m/s)
    r_lin: float                  # linearised friction resistance per unit length, f Q0 / (g D A^2)
    y_valve: float                # valve admittance after the excitation (m2/s)
    y_up: Optional[float] = None  # upstream admittance; None = reservoir (h = 0)
    g: float = 9.81
    rho: float = 998.2
    k_w: float = 2.2e9
    c1_d_over_e: float = 0.0      # c1 D / e, for the viscoelastic wave speed
    j_k: Sequence[float] = ()
    tau_k: Sequence[float] = ()
    j0: float = 0.0

    @property
    def area(self) -> float:
        return np.pi * self.d ** 2 / 4


def wave_speed_s(m: LineModel, s: np.ndarray) -> np.ndarray:
    """Complex wave speed: 1/a(s)² = 1/a² + ρ (c1 D/e) Σ J_k/(1 + s τ_k). Math note §5.8."""
    inv = np.full(s.shape, 1.0 / m.a ** 2, dtype=complex)
    for jk, tk in zip(m.j_k, m.tau_k):
        inv = inv + m.rho * m.c1_d_over_e * jk / (1.0 + s * tk)
    return 1.0 / np.sqrt(inv)


def pipe_matrix(m: LineModel, s: np.ndarray, length: float) -> np.ndarray:
    """Transfer matrix of a pipe section (shape (len(s), 2, 2)). Math note §5.8."""
    a = wave_speed_s(m, s)
    A = m.area
    mu = np.sqrt(s ** 2 + s * m.g * A * m.r_lin) / a
    zc = mu * a ** 2 / (s * m.g * A)
    ch, sh = np.cosh(mu * length), np.sinh(mu * length)
    M = np.empty(s.shape + (2, 2), dtype=complex)
    M[:, 0, 0] = ch
    M[:, 0, 1] = -zc * sh
    M[:, 1, 0] = -sh / zc
    M[:, 1, 1] = ch
    return M


def leak_matrix(y_l: float, n: int) -> np.ndarray:
    """Point matrix of a leak: q_d = q_u − Y_L h. Math note §5.8."""
    M = np.zeros((n, 2, 2), dtype=complex)
    M[:, 0, 0] = 1.0
    M[:, 1, 1] = 1.0
    M[:, 1, 0] = -y_l
    return M


def response(m: LineModel, s: np.ndarray, leaks: Sequence[tuple[float, float]] = ()) -> np.ndarray:
    """H(s) = h_L / u with leaks [(x, Y_L), ...] sorted from upstream."""
    n = len(s)
    v = np.zeros((n, 2), dtype=complex)
    if m.y_up is None:
        v[:, 1] = 1.0
    else:
        v[:, 0] = 1.0
        v[:, 1] = -m.y_up
    x_prev = 0.0
    for x, y in sorted(leaks):
        v = np.einsum("nij,nj->ni", pipe_matrix(m, s, x - x_prev), v)
        v = np.einsum("nij,nj->ni", leak_matrix(y, n), v)
        x_prev = x
    v = np.einsum("nij,nj->ni", pipe_matrix(m, s, m.length - x_prev), v)
    return v[:, 0] / (v[:, 1] - m.y_valve * v[:, 0])


def laplace(t: np.ndarray, y: np.ndarray, sigma: float, n_fft: Optional[int] = None):
    """Discrete Laplace transform on Re(s) = σ via FFT of y e^{-σt}. Returns (s, Y)."""
    dt = float(t[1] - t[0])
    n = n_fft or len(t)
    Y = np.fft.rfft(y * np.exp(-sigma * (t - t[0])), n=n) * dt
    w = 2 * np.pi * np.fft.rfftfreq(n, dt)
    s = sigma + 1j * w
    # shift the time origin back to t[0]
    return s, Y * np.exp(-s * 0.0)
