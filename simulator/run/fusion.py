"""Fusion and decision: figures + validation report."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import fusion as oracle  # noqa: E402

OUT = ROOT / "results" / "fusion"


def fig_reliability(M):
    P, y = M["P"], M["y"]
    edges = np.linspace(0, 1, 11)
    xs, ys, ns = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (P >= a) & (P <= b if b == 1 else P < b)
        if m.sum() >= 3:
            xs.append(P[m].mean())
            ys.append(y[m].mean())
            ns.append(m.sum())
    fig, ax = st.figure(w=6.2, h=4.6)
    ax.plot([0, 1], [0, 1], color=st.MUTED, lw=0.9, ls=(0, (3, 3)), label="perfect calibration")
    ax.scatter(xs, ys, s=[20 + n / 3 for n in ns], color=st.SERIES[0], edgecolors=st.SURFACE, linewidths=1.5,
               zorder=4, label="fused M1 + M2 (dot size = windows)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect("equal")
    ax.set_xlabel("Fused P(leak)")
    ax.set_ylabel("Observed share of leaky windows")
    ax.set_title("Is P(leak) honest?")
    st.subtitle(ax, f"Reliability on 800 test windows · ECE = {M['ece']:.3f}")
    ax.legend(loc="upper left")
    return st.save(fig, OUT / "reliability.png")


def fig_actions(M):
    y, frac, act = M["y"], M["frac"], M["act"]
    groups = [("healthy", y == 0), ("1–2 %", (y > 0) & (frac < 0.02)), ("2–5 %", (y > 0) & (frac >= 0.02) & (frac < 0.05)),
              ("≥ 5 %", (y > 0) & (frac >= 0.05))]
    cols = {"log": "#cfcec8", "watch": st.WARNING, "alert": st.CRITICAL}
    fig, ax = st.figure(w=7.4, h=3.8)
    for i, (name, m) in enumerate(groups):
        left = 0.0
        for a in ("log", "watch", "alert"):
            share = float(np.mean(act[m] == a)) * 100
            if share > 0:
                ax.barh(i, share, left=left, height=0.55, color=cols[a], edgecolor=st.SURFACE, linewidth=2)
                if share >= 6:
                    ax.text(left + share / 2, i, f"{a} {share:.0f} %", ha="center", va="center", fontsize=8,
                            color=st.TEXT if a != "alert" else st.SURFACE)
                left += share
    ax.set_yticks(range(len(groups)), [g[0] for g in groups])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of test windows (%)")
    ax.set_title("What the farmer receives")
    st.subtitle(ax, "log (no message) · watch (run an M3 test) · alert (SMS + drone) · τ₁ = 0.3, τ₂ = 0.8")
    ax.grid(axis="y", visible=False)
    return st.save(fig, OUT / "actions.png")


def main():
    checks = oracle.checks()
    M = oracle.metrics()
    fm = M["X"]["fm"]
    f1, f2 = fig_reliability(M), fig_actions(M)
    write_report(
        OUT / "README.md", 10, "Fusion and decision",
        "M1 and M2 outputs on the 800 test windows are fused as in math note §6: quality gate, log-odds fusion of "
        "the scores, weighted product of the location maps, bootstrap band, and the log/watch/alert decision. "
        "Weights are learned on validation windows only.",
        built=[
            ("fusion/decision.py", "Quality gate (own gate + outlier rule with ≥ 3 methods), log-odds fusion, location fusion, bootstrap band, decide(), weight learning", "§6"),
            ("oracles/fusion_cases.py", "M1 + M2 outputs on validation (learning) and test (evaluation)", "§6"),
        ],
        checks=checks,
        figures=[
            (f1.name, "Reliability diagram of the fused probability."),
            (f2.name, "Decisions sent to the farmer, by leak size."),
        ],
        findings=[
            f"Learned detection weights: M1 {fm.w['M1']:.2f}, M2 {fm.w['M2']:.2f} (both informative). Location weights: M1 {fm.v['M1']:.1f}, M2 {fm.v['M2']:.1f}.",
            f"**Calibration cannot really be judged yet.** On this dataset almost every window gets P ≈ 0 or P ≈ 1 (leaks of 1–20 % are separated perfectly), so the ECE of {M['ece']:.3f} is trivially low. The next dataset should include 0.1–1 % leaks, where the methods hesitate; that is where τ₁/τ₂ and the 'watch' action (automatic M3 test) matter.",
            f"Healthy windows end in an alert **{M['fa_alert'] * 100:.1f} %** of the time; leaks ≥ 5 % **{M['alert_big'] * 100:.0f} %**. Small leaks (1–2 %) are also alerted, because both methods see them clearly in this dataset.",
            f"Location: right sector **{M['acc']['fused'] * 100:.0f} %** fused vs {M['acc']['M2'] * 100:.0f} % M2 alone and {M['acc']['M1'] * 100:.0f} % M1 alone. Exact location {M['top1']['fused'] * 100:.0f} % fused vs {M['top1']['M2'] * 100:.0f} % M2: the weights maximise the probability given to the true location, which slightly lowers the top-1 rate. As M1 gets more data, its location weight should fall automatically.",
            "The quality gate works as designed: a method failing its own gate is dropped, and with three methods a silent M3 (e.g. wave damped by trapped air) is treated as an outlier instead of vetoing the alert.",
            "The prior of the training data (≈ 50 % leaky windows) is not the field prior. In operation, apply the Bayes prior shift logit P_field = logit P − logit p₀,train + logit p₀,field, with p₀,field estimated from the pilot farm.",
        ],
        assumptions=[
            "M3 is not part of the learned weights yet (it runs on demand on single lines; its weight is set to 1 until bench data exist).",
            "Thresholds τ₁ = 0.3 and τ₂ = 0.8 from params.yaml.",
            "Bootstrap of the validation set (40 resamples) for the 5–95 % band.",
        ],
        decisions=[
            "Regenerate the dataset with leaks down to 0.1 % (one parameter in steady/scenarios.py) to calibrate τ₁, τ₂ and the watch zone.",
            "Agree on the farmer-facing actions: log / watch (automatic M3 test) / alert (SMS + map + optional drone).",
        ],
    )
    print(f"Fusion: {sum(c.passed for c in checks)}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
