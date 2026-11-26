"""M3 solver validation figure + numbers for the report and the mentor review.

    python -m m3.validate   ->  report/figures/m3_validation.png, m3/out/validation.json
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from m3.echo import echo_distance  # noqa: E402
from m3.moc import joukowsky_head, leak_cda_for_fraction, load_setup, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    base = load_setup()
    T2 = 2 * base.L / base.a

    # 1. Joukowsky + period, frictionless, instantaneous closure
    s1 = base.with_(f=0.0, Tc=0.0, duration=4.0)
    r1 = simulate(s1)
    m = (r1.t > s1.t_close + 0.02) & (r1.t < s1.t_close + T2 - 0.02)
    dh = r1.H_valve[m].mean() - r1.H0
    sig = np.sign(r1.H_valve[r1.t > s1.t_close + s1.dt] - r1.H0)
    flips = r1.t[r1.t > s1.t_close + s1.dt][1:][np.diff(sig) != 0]
    period = 2 * np.diff(flips).mean()

    # 2. Realistic closure (25 ms, friction), with and without a 5 % leak at 100 m
    x_leak = 100.0
    ref = simulate(base)
    leak = simulate(base.with_(x_leak=x_leak, leak_cda=leak_cda_for_fraction(base, 0.05, x_leak)))
    t, h = leak.sampled(2000)
    _, h_ref = ref.sampled(2000)
    e = echo_distance(t, h, h_ref, base.a, base.t_close, L=base.L)
    x_est = base.L - e["distance_m"]

    numbers = {
        "simulation": True,
        "setup": {"L_m": base.L, "D_m": base.D, "a_mps": base.a, "darcy_f": base.f,
                  "H_res_m": base.H_res, "V0_mps": base.V0, "closure_ms": base.Tc * 1000,
                  "dx_m": base.dx, "dt_ms": base.dt * 1000, "fs_hz": 2000},
        "joukowsky": {"expected_m": joukowsky_head(s1), "simulated_m": dh,
                      "rel_error": dh / joukowsky_head(s1) - 1},
        "period": {"expected_s": 4 * s1.L / s1.a, "simulated_s": period,
                   "rel_error": period / (4 * s1.L / s1.a) - 1},
        "echo": {"x_leak_true_m": x_leak, "x_leak_est_m": x_est, "error_m": x_est - x_leak,
                 "echo_amplitude_m": e["amplitude_m"], "leak_fraction": 0.05,
                 "note": "noise-free; vs a leak-free reference trace"},
        "min_head_m": min(r1.min_head, leak.min_head),
    }
    out = ROOT / "m3" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps(numbers, indent=1), encoding="utf-8")

    fig, ax = plt.subplots(3, 1, figsize=(7.5, 8.6))
    a0 = ax[0]
    a0.plot(r1.t, r1.H_valve, color="#2d6fa3", lw=1.2, label="MOC, valve head")
    a0.axhline(r1.H0 + joukowsky_head(s1), color="#e07b00", ls="--", lw=1,
               label=f"Joukowsky a·V/g = {joukowsky_head(s1):.2f} m")
    a0.set_title(f"1. Instantaneous closure, no friction: ΔH error {numbers['joukowsky']['rel_error']:.1e}, "
                 f"period {period:.3f} s (4L/a = {4 * s1.L / s1.a:.3f} s)", fontsize=9)
    a0.set_ylabel("head (m)")
    a0.legend(fontsize=8, loc="upper right")

    a1 = ax[1]
    a1.plot(ref.t, ref.H_valve, color="#888", lw=1.2, label="no leak")
    a1.plot(leak.t, leak.H_valve, color="#2d6fa3", lw=1.0, label=f"5 % leak at {x_leak:.0f} m")
    a1.set_xlim(0, 1.2)
    a1.set_title(f"2. 25 ms closure with friction (f = {base.f}): the leak changes the trace", fontsize=9)
    a1.set_ylabel("head (m)")
    a1.legend(fontsize=8, loc="upper right")

    a2 = ax[2]
    diff = (h - h_ref) - np.mean((h - h_ref)[t < base.t_close])
    a2.plot(t * 1000, diff, color="#c0392b", lw=1.2, label="leak trace − reference (2 kHz)")
    t_pred = base.t_close + 2 * (base.L - x_leak) / base.a
    a2.axvline(t_pred * 1000, color="#555", ls=":",
               label=f"expected: closure + 2d/a = {base.t_close * 1000:.0f} + {(t_pred - base.t_close) * 1000:.0f} ms")
    t_end = base.t_close + T2
    a2.set_xlim(0, t_end * 1000)
    win = t < t_end - 0.01
    lo, hi = diff[win].min(), diff[win].max()
    pad = 0.2 * (hi - lo)
    a2.set_ylim(lo - pad, hi + pad)
    a2.set_title(f"3. Echo: estimated position {x_est:.2f} m (true {x_leak:.0f} m), "
                 f"echo amplitude {e['amplitude_m']:.2f} m", fontsize=9)
    a2.set_xlabel("time (ms)")
    a2.set_ylabel("Δhead (m)")
    a2.legend(fontsize=8, loc="lower left")
    for a in ax:
        a.grid(alpha=0.3)
    fig.text(0.01, 0.005, f"SIMULATION – PE pipe L = {base.L:.0f} m, a = {base.a:.0f} m/s", fontsize=8, color="#a00")
    fig.tight_layout()
    fig_path = ROOT / "report" / "figures" / "m3_validation.png"
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=150)
    print(json.dumps({k: numbers[k] for k in ("joukowsky", "period", "echo")}, indent=1))
    print(f"figure -> {fig_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
