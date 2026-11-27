"""M2 PCA/SVD: figures + validation report."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from hydropin_sim.methods import m2_pca as m2  # noqa: E402
from hydropin_sim.methods.signatures import location_xy  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import m2_pca as oracle  # noqa: E402
from oracles.m2_cases import FARM  # noqa: E402

OUT = ROOT / "results" / "m2-pca"


def fig_alarm(M):
    E = M["E"]
    F, idx, ratio = E["F"], E["idx"], E["ratio"]
    leak, frac = F.leak[idx], F.leak_frac[idx]
    groups = [("healthy", ~leak), ("1–2 %", leak & (frac < 0.02)), ("2–5 %", leak & (frac >= 0.02) & (frac < 0.05)),
              ("5–10 %", leak & (frac >= 0.05) & (frac < 0.1)), ("10–20 %", leak & (frac >= 0.1))]
    fig, ax = st.figure(w=8.2, h=4.2)
    rng = np.random.default_rng(0)
    for i, (name, m) in enumerate(groups):
        y = ratio[m]
        col = "#b9b8b2" if i == 0 else st.SEQ_BLUE[min(2 + i, 6)]
        ax.scatter(i + rng.uniform(-0.28, 0.28, m.sum()), y, s=8, color=col, alpha=0.8, zorder=3)
        ax.plot([i - 0.32, i + 0.32], [np.median(y)] * 2, color=st.TEXT, lw=1.6, zorder=4)
    ax.axhline(1.0, color=st.CRITICAL, lw=1.0, ls=(0, (4, 3)))
    ax.text(4.45, 1.12, "alarm threshold", ha="right", fontsize=8, color=st.TEXT_2)
    ax.set_yscale("log")
    ax.set_xticks(range(len(groups)), [g[0] for g in groups])
    ax.set_xlabel("Test windows, by leak size (% of the shift flow)")
    ax.set_ylabel("Alarm ratio max(SPE/SPE₉₉, T²/T²₉₉)")
    ax.set_title("M2 separates healthy windows from leaks")
    st.subtitle(ax, f"{len(idx):,} unseen test windows · black bar = median · false alarms {M['fpr'] * 100:.1f} %")
    return st.save(fig, OUT / "alarm.png")


def fig_error(M):
    fig, ax = st.figure(w=7.6, h=4.0)
    for i, (key, name) in enumerate((("small", "1–2 %"), ("mid", "2–5 %"), ("large", "≥ 5 %"))):
        e = np.sort(M[key]["errs"][np.isfinite(M[key]["errs"])])
        ax.step(e, np.arange(1, len(e) + 1) / len(e) * 100, where="post", color=st.SERIES[i],
                label=f"leaks {name} (median {np.median(e):.0f} m)")
    ax.set_xscale("symlog", linthresh=5)
    ax.set_xlim(0, 300)
    ax.set_ylim(0, 102)
    ax.set_xlabel("Distance between the true leak and M2's location (m)")
    ax.set_ylabel("Share of detected leaks (%)")
    ax.set_title("How close M2 gets")
    st.subtitle(ax, "Cumulative distribution · M2 narrows the search to a pipe or block; M3/drone pinpoint")
    ax.legend(loc="lower right")
    return st.save(fig, OUT / "error.png")


def fig_map(M):
    E = M["E"]
    F, idx, best = E["F"], E["idx"], E["best"]
    leak, frac, alarm = F.leak[idx], F.leak_frac[idx], E["ratio"] > 1
    cand = np.where(leak & alarm & (frac > 0.04) & (F.leak_kind[idx] == 2))[0]
    k = int(cand[0])
    i = idx[k]
    mdl, X = E["models"][F.shift[i]]
    _, p = m2.localise(mdl, X(np.array([i])))
    xy = {n.id: (n.x, n.y) for n in FARM.nodes}
    fig, ax = st.figure(w=9.4, h=3.6)
    for pp in FARM.pipes:
        (x1, y1), (x2, y2) = xy[pp.start], xy[pp.end]
        ax.plot([x1, x2], [y1, y2], color="#cfcec8", lw=1.6, zorder=1)
    for lb in FARM.lateral_blocks:
        x0, y0 = xy[lb.node]
        for kk in range(lb.n_laterals):
            yy = y0 + (kk - 4.5)
            ax.plot([x0 + 1, x0 + lb.lateral_length], [yy, yy], color="#ecebe7", lw=0.5, zorder=0)
    locs = np.array([location_xy(FARM, n) for n in mdl.locations])
    sc = ax.scatter(locs[:, 0], locs[:, 1], s=40 + 900 * p, c=p, cmap=st.SEQ_CMAP, vmin=0, vmax=p.max(),
                    edgecolors=st.SURFACE, linewidths=1.5, zorder=4)
    tx, ty = F.leak_xy[i]
    ax.scatter([tx], [ty], marker="*", s=220, color=st.CRITICAL, edgecolors=st.SURFACE, linewidths=1.2, zorder=6)
    ax.annotate(f"true leak ({F.leak_id[i]}, {frac[k] * 100:.0f} % of the flow)", (tx, ty), xytext=(12, 10),
                textcoords="offset points", fontsize=8.2, color=st.TEXT_2)
    cb = fig.colorbar(sc, cax=ax.inset_axes([1.01, 0.05, 0.015, 0.9]))
    cb.set_label("M2 location probability", color=st.TEXT_2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=st.TEXT_2, labelsize=8)
    ax.set_aspect("equal")
    ax.set_xlim(-18, 385)
    ax.set_ylim(-12, 48)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title("One alarm, as the farmer's map would show it")
    st.subtitle(ax, f"Shift {mdl.shift.replace('SECTOR', 'sector ').replace('+', ' + ')} · bubble size = probability")
    return st.save(fig, OUT / "map.png")


def main():
    checks = oracle.checks()
    M = oracle.metrics()
    f1, f2, f3 = fig_alarm(M), fig_error(M), fig_map(M)
    write_report(
        OUT / "README.md", 7, "M2 – PCA/SVD detection and localisation",
        "M2 is trained per irrigation shift on healthy windows only and tested on 800 unseen windows of the "
        "simulated dataset. It flags a change when the pressure/flow pattern leaves the healthy subspace, then "
        "matches the residual against leak signatures computed by the digital twin.",
        built=[
            ("methods/features.py", "Zeroing, temperature compensation, window means; change vs the last healthy irrigation of the same shift", "§3.1, §3.3"),
            ("methods/signatures.py", "Leak signatures from the twin (every location that carries water in a shift)", "§4.1"),
            ("methods/m2_pca.py", "Per-shift SVD, SPE and T² with 99 % thresholds, cosine localisation, MethodOutput", "§4.1"),
            ("sensors/dataset.py", "Dataset extended (added fields only): paired healthy baseline window per sample", "§2.9"),
        ],
        checks=checks,
        figures=[
            (f1.name, "Alarm ratio of every test window, by leak size."),
            (f2.name, "Localisation error of detected leaks."),
            (f3.name, "Example alarm on the farm map: M2's location probabilities and the true leak."),
        ],
        findings=[
            "**First attempt failed, and the reason matters for the product.** Trained on absolute readings across many random farm states, M2 detected only 15 % of 5–10 % leaks. On a pump-fed farm, a leak moves pressure and flow *along the pump curve*, exactly like cleaner drippers or smoother pipes, so across different farms they look the same. A deployed system compares each irrigation with the **last healthy irrigation of the same shift on the same farm**. The dataset now has that paired baseline (another day, water temperature ±2 °C, new noise).",
            f"With change-vs-baseline features: **{M['small']['tpr'] * 100:.0f} % of 1–2 % leaks, {M['mid']['tpr'] * 100:.0f} % of 2–5 % and {M['large']['tpr'] * 100:.0f} % of ≥ 5 % leaks are detected**, with **{M['fpr'] * 100:.1f} % false alarms**.",
            f"Localisation: for leaks ≥ 5 %, the right sector is found **{M['large']['sector'] * 100:.0f} %** of the time and the median error is **{M['large']['err_med']:.0f} m** (90 % within {M['large']['err_p90']:.0f} m). The exact location is right in {M['large']['top1'] * 100:.0f} % of cases. With 9 sensors, neighbouring blocks of a sub-main have almost the same signature. **M2 points to a pipe or a block; M3 and the drone pinpoint.**",
            "The number of PCA components is now chosen above the noise floor. Healthy changes are mostly isotropic sensor noise plus one structured direction (water temperature through viscosity). The '95 % of variance' rule kept noise directions and blinded the method. Math note §4.1 updated accordingly.",
        ],
        assumptions=[
            "A healthy baseline of the same shift exists from a recent irrigation (same clogging and roughness, water temperature within ±2 °C). In the field: the last irrigation not flagged by any method.",
            "9 pressure sensors in the default positions (sensor placement optimises them) + the pump flow meter.",
            "Leak signatures from the nominal twin with a 5 % leak; real signatures scale roughly linearly with leak size.",
            "Thresholds at 99 % of healthy validation windows per shift (SPE and T² each at 99.5 %).",
        ],
        decisions=[
            "Product rule: keep a rolling healthy baseline per shift (the platform stores the last unflagged irrigation of each shift).",
        ],
    )
    print(f"M2: {sum(c.passed for c in checks)}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
