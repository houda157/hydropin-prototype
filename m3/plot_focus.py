"""Report figure: time-reversal focusing ("energy vs position") vs matched-field.

    python -m m3.plot_focus   ->  report/figures/m3_time_reversal.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from m3.locate import matched_field, measure, mfp_bank, time_reversal  # noqa: E402
from m3.moc import leak_cda_for_fraction, load_setup  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SIGMA = 0.02
CASES = [35.0, 90.0, 135.0]


def main() -> None:
    m = load_setup()
    bank = mfp_bank(m)
    fig, ax = plt.subplots(len(CASES), 1, figsize=(7.5, 6.5), sharex=True)
    for a, x in zip(ax, CASES):
        true = m.with_(x_leak=x, leak_cda=leak_cda_for_fraction(m, 0.05, x))
        t, h = measure(true, sigma_m=SIGMA, rng=np.random.default_rng(int(x)))
        tr = time_reversal(m, t, h)
        mf = matched_field(m, t, h, bank=bank)
        a.fill_between(tr.x, tr.score, color="#2d6fa3", alpha=0.25)
        a.plot(tr.x, tr.score, color="#2d6fa3", lw=1.3, label=f"time reversal → {tr.x_est:.1f} m")
        a.plot(mf.x, mf.score, color="#e07b00", lw=1.0, ls="--", label=f"matched-field → {mf.x_est:.1f} m")
        a.axvline(x, color="#c0392b", lw=1.2, label=f"true leak {x:.0f} m")
        a.set_ylabel("focus (norm.)")
        a.set_ylim(0, 1.08)
        a.grid(alpha=0.3)
        a.legend(fontsize=8, loc="upper left")
    ax[-1].set_xlabel("position along the pipe (m)  —  reservoir at 0, valve + sensor at 150")
    ax[0].set_title(f"M3 time reversal: energy focuses at the leak (5 % leak, σ = {SIGMA} m, 2 kHz)", fontsize=10)
    fig.text(0.01, 0.005, "SIMULATION – 150 m PE pipe, a = 350 m/s, 25 ms valve closure", fontsize=8, color="#a00")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    out = ROOT / "report" / "figures" / "m3_time_reversal.png"
    fig.savefig(out, dpi=150)
    print(f"figure -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
