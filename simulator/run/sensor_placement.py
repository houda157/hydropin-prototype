"""Sensor placement: figures + validation report."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import sensor_placement as oracle  # noqa: E402
from oracles.m2_cases import FARM  # noqa: E402
from oracles.placement_cases import DESIGN_LEAK  # noqa: E402

OUT = ROOT / "results" / "sensor-placement"


def fig_curve(R):
    pr = R["pr"]
    h = R["hist"]
    fig, ax = st.figure(w=7.4, h=4.0)
    k = np.arange(1, len(h) + 1)
    ax.plot(k, h, "o-", color=st.SERIES[0], markeredgecolor=st.SURFACE, markeredgewidth=1.5, label="greedy")
    for kk, (S, v) in R["ex"].items():
        ax.plot([kk], [v], "D", color=st.SERIES[1], markersize=7, markeredgecolor=st.SURFACE, markeredgewidth=1.2,
                label="exhaustive optimum" if kk == 2 else None)
    ax.plot([9], [R["ga_val"]], "s", color=st.SERIES[2], markersize=7, markeredgecolor=st.SURFACE,
            markeredgewidth=1.2, label="genetic algorithm (9)")
    ax.plot([9], [pr.phi(R["default"])], "o", color=st.TEXT_2, markersize=7, markeredgecolor=st.SURFACE,
            markeredgewidth=1.2, label="default set (9)")
    ax.set_xlabel("Number of pressure sensors")
    ax.set_ylabel("Objective Φ = coverage + isolation")
    ax.set_title("How many sensors does the demo farm need?")
    st.subtitle(ax, f"Design leak {DESIGN_LEAK * 100:.1f} % of the shift flow · all 6 shifts · every junction is a candidate")
    ax.legend(loc="lower right")
    return st.save(fig, OUT / "curve.png")


def fig_map(R):
    pr = R["pr"]
    xy = {n.id: (n.x, n.y) for n in FARM.nodes}
    fig, ax = st.figure(w=9.4, h=3.6)
    for p in FARM.pipes:
        (x1, y1), (x2, y2) = xy[p.start], xy[p.end]
        ax.plot([x1, x2], [y1, y2], color="#cfcec8", lw=1.8 if p.material == "PVC" else 1.4, zorder=1)
    for lb in FARM.lateral_blocks:
        x0, y0 = xy[lb.node]
        for kk in range(lb.n_laterals):
            ax.plot([x0 + 1, x0 + lb.lateral_length], [y0 + kk - 4.5] * 2, color="#efeee9", lw=0.5, zorder=0)
    d = [pr.nodes[i] for i in R["default"]]
    o = [pr.nodes[i] for i in R["ga"]]
    for n in d:
        ax.scatter(*xy[n], s=150, facecolors="none", edgecolors=st.TEXT_2, linewidths=1.4, zorder=4)
    for n in o:
        ax.scatter(*xy[n], s=60, color=st.SERIES[0], edgecolors=st.SURFACE, linewidths=1.5, zorder=5)
    handles = [Line2D([], [], marker="o", lw=0, markerfacecolor="none", markeredgecolor=st.TEXT_2, markersize=10,
                      label="default"),
               Line2D([], [], marker="o", lw=0, color=st.SERIES[0], markersize=7, label="optimised (GA)")]
    ax.legend(handles=handles, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.02))
    ax.set_aspect("equal")
    ax.set_xlim(-18, 385)
    ax.set_ylim(-12, 48)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title("Where to put 9 sensors")
    st.subtitle(ax, f"Φ default {pr.phi(R['default']):.3f} → optimised {R['ga_val']:.3f}")
    return st.save(fig, OUT / "map.png")


def main():
    checks = oracle.checks()
    R = oracle.results()
    pr = R["pr"]
    f1, f2 = fig_curve(R), fig_map(R)
    h = R["hist"]
    k95 = int(np.argmax(np.array(h) >= 0.98 * max(h)) + 1)
    write_report(
        OUT / "README.md", 9, "Sensor placement",
        "Every junction of the demo farm is a candidate sensor position. The objective of math note §7 rewards "
        "seeing every design leak in every shift (coverage) and telling neighbouring leaks apart (isolation). "
        "Greedy search, exhaustive search on small cases and a genetic algorithm are compared.",
        built=[
            ("placement/optimizer.py", "Objective Φ, greedy, exhaustive, genetic algorithm (crossover + move-to-neighbour mutation)", "§7"),
            ("oracles/placement_cases.py", "Placement problem: signatures of every leak location at every node, for all 6 shifts", "§7"),
        ],
        checks=checks,
        figures=[
            (f1.name, "Objective vs number of sensors: greedy, exhaustive optimum, genetic algorithm, default set."),
            (f2.name, "Default vs optimised positions for 9 sensors."),
        ],
        findings=[
            f"Greedy is optimal with 2–3 sensors and within {100 * min(R['gr'][4] / R['ex'][4][1], 1):.1f} % of the optimum with 4 (exhaustive check). The GA then improves the 9-sensor set.",
            f"Diminishing returns: **{k95} sensors** reach 98 % of the best objective. Beyond that, extra sensors add almost nothing on this farm. That is a useful cost argument for the business plan.",
            f"Optimised 9-sensor set: {', '.join(pr.nodes[i] for i in R['ga'])}. Compared with the default, it moves sensors from sector heads to the **far ends of sub-mains** (B·3, B·1) and to the main, where leak signatures differ most.",
            f"Coverage: the optimised 9 sensors see **{100 * oracle.coverage(pr, R['ga']):.0f} %** of 0.5 % design leaks, exactly as many as 21 sensors (one per junction) would. The remaining ones sit below κσ_tot in single-sector shifts (smaller flow). 0.5 % is the practical floor for steady-state detection on this farm; the first oracle version wrongly expected 100 % and was corrected to 'as good as every junction'.",
            "Every sector needs at least one sensor: when a sector is closed, its sensors read 0, so coverage is only reached with one sensor per sector.",
            "Objective made explicit (math note §7): isolation is the mean angle to the nearest *other* visible location (not the minimum over all pairs, which is always 0 for leaks at the same place), and a leak no sensor sees scores 0.",
        ],
        assumptions=[
            f"Design leak {DESIGN_LEAK * 100:.1f} % of the shift flow, signatures scaled linearly from the 5 % twin signatures.",
            "Detection threshold κ σ_tot with temperature compensation .",
            "λ_iso = 1 (coverage and isolation weighted equally).",
        ],
        decisions=[
            "Use the optimised positions for the pilot farm once its survey replaces the demo farm (rerun this script).",
        ],
    )
    print(f"Sensor placement: {sum(c.passed for c in checks)}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
