"""Leak echo: the simplest M3 locator, and a cross-check for time reversal and the CNN.

The valve closure sends a pressure wave upstream. At the leak, part of it reflects back as
a negative step and reaches the sensor (at the valve) after 2 d / a, where d is the
leak's distance from the sensor:  d = a * t_echo / 2.

This version compares the measured trace with a leak-free reference (from the model or from
a run before the leak). The pipe's own features (the reservoir) only return after 2L/a,
so any change before that comes from the leak.
"""
from __future__ import annotations

import numpy as np


def echo_distance(t: np.ndarray, h: np.ndarray, h_ref: np.ndarray, a: float, t_front: float,
                  rel_threshold: float = 0.05, L: float | None = None) -> dict:
    """Distance (m) from the sensor to the first reflector that differs from the reference.

    t_front: time the wave leaves the sensor (valve closure start).
    rel_threshold: onset = first sample where |diff| exceeds this fraction of the largest
    |diff| seen before the reservoir reflection returns.
    """
    diff = (h - h_ref) - np.mean((h - h_ref)[t < t_front])     # remove steady offset
    t_end = t_front + 2 * L / a if L else t[-1]
    window = (t >= t_front) & (t < t_end)
    peak = np.abs(diff[window]).max()
    if peak == 0:
        return {"distance_m": None, "t_echo_s": None, "amplitude_m": 0.0}
    hit = window & (np.abs(diff) > rel_threshold * peak)
    i = int(np.argmax(hit))
    # linear interpolation between the samples around the threshold crossing
    thr = rel_threshold * peak
    i0 = max(i - 1, 0)
    y0, y1 = abs(diff[i0]), abs(diff[i])
    frac = 0.0 if y1 == y0 else (thr - y0) / (y1 - y0)
    t_hit = t[i0] + frac * (t[i] - t[i0])
    t_echo = t_hit - t_front
    return {"distance_m": a * t_echo / 2, "t_echo_s": t_echo, "amplitude_m": float(peak)}
