"""Score M2, M1 and their fusion on the farm's test worlds; export dashboard/farm/results.json.

    python -m farm.methods.results     # M2 (+ M1 if farm/methods/out/m1_pred_n*_a*.npy exist)

Two noise cases, both reported:
  * "single": one noisy reading per sensor (the leak dataset as generated);
  * "avg_60": the residual averaged over 60 readings (one minute at 1 Hz), as a farm controller
    would before localising a leak that lasts hours. White noise is assumed (an assumption:
    real drift averages down less). The showcase maps and the drone use this case.

M1 predictions come from `python -m farm.methods.m1_gnn` (torch, .venv-sim), which writes
farm/methods/out/m1_pred_n{3,6,10}_a{1,60}.npy: [n_scenarios x n_sites] probabilities.
Fusion = normalised product of the maps (floor 1e-3, so one method cannot veto).
Everything is simulation; numbers are on test worlds only (worlds 7-9 of each shift).
"""
from __future__ import annotations

import json

import numpy as np

from farm.methods.common import OUT, ROOT, FarmData, load, sensor_sets, site_to_link_probs, sites_adjacent
from farm.methods.m2 import FarmM2

DASH = ROOT / "dashboard" / "farm" / "results.json"
FIG = ROOT / "report" / "figures" / "farm_m1_m2_fused.png"
FLOOR = 1e-3
AVERAGING = {"single": 1, "avg_60": 60}
SHOW_CASE = "avg_60"


def fuse(*maps: np.ndarray) -> np.ndarray:
    P = np.ones_like(maps[0])
    for m in maps:
        P = P * (m + FLOOR)
    P = np.where(maps[0] > 0, P, 0.0)
    s = P.sum(axis=1, keepdims=True)
    return P / np.where(s > 0, s, 1.0)


def metrics(P: np.ndarray, rows: np.ndarray, det: np.ndarray, fd: FarmData) -> dict:
    sizes = fd.sc.size_pct.to_numpy()[rows]
    true_site = fd.site_idx[rows]
    pred = P.argmax(axis=1)
    top1 = (pred == true_site) & det
    hop = np.array([d and sites_adjacent(fd.sites[p], fd.sites[t], fd) for p, t, d in zip(pred, true_site, det)])
    br = np.array([d and fd.site_branch[fd.sites[p]] == fd.site_branch[fd.sites[t]]
                   for p, t, d in zip(pred, true_site, det)])
    out = {}
    groups = (("all", np.ones(len(rows), bool)), ("1", sizes == 1), ("3", sizes == 3),
              ("10", sizes == 10), ("3+10", sizes >= 3))
    for name, m in groups:
        if not m.any():
            continue
        out[name] = {"n": int(m.sum()), "detected_pct": round(100 * det[m].mean(), 1),
                     "right_site_pct": round(100 * top1[m].mean(), 1),
                     "within_one_hop_pct": round(100 * hop[m].mean(), 1),
                     "right_branch_pct": round(100 * br[m].mean(), 1)}
    return out


def showcase_rows(fd: FarmData) -> list[int]:
    """10 test scenarios (world 7 of each shift): a main-pipe leak and one sub-main pipe leak
    per open sector, sizes alternating 10 % / 3 %."""
    sc = fd.sc
    picks = []
    for c in sorted(sc.config_id.unique()):
        sub = sc[(sc.config_id == c) & (sc.world_id % 10 == 7) & (sc.leak_kind == "pipe")]
        wanted = ["main"] + sorted(b for b in sub.branch.unique() if b != "main")
        for b in wanted:
            size = 10.0 if len(picks) % 2 == 0 else 3.0
            cand = sub[(sub.branch == b) & (sub.size_pct == size)]
            if b == "main":
                cand = cand[cand.leak_at == ("MN1", "MN2", "MN3")[c % 3]] if len(cand) else cand
            if len(cand):
                picks.append(int(cand.iloc[len(picks) % len(cand)].scenario_id))
    # add one node leak (a sector head) to reach 10
    extra = sc[(sc.world_id % 10 == 7) & (sc.leak_kind == "node") & (sc.leak_at == "H3") & (sc.size_pct == 10.0)]
    if len(extra):
        picks.append(int(extra.iloc[0].scenario_id))
    return picks[:10]


def plot(summary: dict, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"m2": "#1f6feb", "m1": "#8250df", "fused": "#e4472a"}
    labels = {"m2": "M2 (PCA / fingerprints)", "m1": "M1 (GNN)", "fused": "Fusion"}
    cases = list(summary)
    fig, axes = plt.subplots(1, len(cases), figsize=(4.6 * len(cases), 3.4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, case in zip(axes, cases):
        ns = sorted(summary[case], key=int)
        methods = [m for m in ("m2", "m1", "fused") if all(m in summary[case][n] for n in ns)]
        w = 0.8 / len(methods)
        for j, m in enumerate(methods):
            vals = [summary[case][n][m]["3+10"]["right_branch_pct"] for n in ns]
            xs = np.arange(len(ns)) + (j - (len(methods) - 1) / 2) * w
            ax.bar(xs, vals, w, label=labels[m], color=colors[m])
            for x, v in zip(xs, vals):
                ax.text(x, v + 1, f"{v:.0f}", ha="center", fontsize=7)
        ax.set_xticks(range(len(ns)), [f"{n} sensors" for n in ns])
        ax.set_title({"single": "One reading", "avg_60": "1-minute average"}.get(case, case), fontsize=10)
        ax.set_ylim(0, 108)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("right branch, % of 3-10 % test leaks")
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle("Virtual farm, test worlds only - SIMULATION", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_case(fd: FarmData, sets: dict, avg: int, show: np.ndarray):
    test_rows = np.where(fd.test)[0]
    summary, maps_show = {}, {}
    for n, sensors in sets.items():
        m2 = FarmM2(fd, sensors).fit()
        det = m2.detected(test_rows)
        maps = {"m2": m2.predict(test_rows)}
        smaps = {"m2": m2.predict(show)}
        m1_path = OUT / f"m1_pred_n{n}_a{avg}.npy"
        if m1_path.exists():
            P1 = np.load(m1_path)
            maps["m1"], smaps["m1"] = P1[test_rows], P1[show]
            maps["fused"], smaps["fused"] = fuse(maps["m2"], maps["m1"]), fuse(smaps["m2"], smaps["m1"])
        else:
            maps["fused"], smaps["fused"] = maps["m2"], smaps["m2"]
        summary[n] = {name: metrics(P, test_rows, det, fd) for name, P in maps.items()}
        maps_show[n] = {"sensors": sensors, "detected": m2.detected(show).tolist(), "maps": smaps}
    return summary, maps_show


def main() -> None:
    sets = sensor_sets()
    summary, show_maps, fds = {}, None, {}
    for case, avg in AVERAGING.items():
        fd = load(avg)
        fds[case] = fd
        show = np.array(showcase_rows(fd))
        summary[case], ms = run_case(fd, sets, avg, show)
        if case == SHOW_CASE:
            show_maps, show_fd, show_ids = ms, fd, show

    scen = []
    for j, sid in enumerate(show_ids):
        r = show_fd.sc.iloc[int(sid)]
        entry = {"id": f"farm_{sid}", "scenario_id": int(sid),
                 "title": f"{r.size_pct:g} % leak on {r.leak_at} ({r.branch.replace('_', ' ')})",
                 "true": {"site": r.leak_at, "kind": r.leak_kind, "branch": r.branch,
                          "pipes": show_fd.site_links[r.leak_at], "x": float(r.x), "y": float(r.y),
                          "size_pct": float(r.size_pct), "leak_lps": float(r.leak_lps)},
                 "open_sectors": [int(s) for s in str(r.open_sectors).split(";")],
                 "by_sensors": {}}
        for n, ps in show_maps.items():
            pipes = {}
            for name, M in ps["maps"].items():
                for link, v in site_to_link_probs(M[j], show_fd).items():
                    if v >= 5e-4:
                        pipes.setdefault(link, {})[name] = round(v, 4)
            entry["by_sensors"][n] = {"sensors": ps["sensors"], "detected": bool(ps["detected"][j]),
                                      "top_site": show_fd.sites[int(ps["maps"]["fused"][j].argmax())],
                                      "pipes": pipes}
        scen.append(entry)

    has_m1 = all("m1" in summary[SHOW_CASE][n] for n in summary[SHOW_CASE])
    doc = {"version": "1.1", "simulation": True,
           "source": "farm/methods/results.py on farm/leaks/out (WNTR virtual farm)",
           "split": "worlds 0-6 of each shift train, 7-9 test; metrics on test only",
           "sigma_bar": show_fd.sigma,
           "noise_cases": {"single": "one reading per sensor",
                           "avg_60": "residual averaged over 60 readings (1 min at 1 Hz); white noise assumed"},
           "showcase_case": SHOW_CASE,
           "methods": ["m2", "m1", "fused"] if has_m1 else ["m2", "fused"],
           "m1_note": None if has_m1 else "M1 not run on this farm yet; fused = M2",
           "fusion": "normalised product of the method maps (floor 1e-3)",
           "metrics": summary, "scenarios": scen}
    DASH.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    plot(summary, FIG)
    for case in summary:
        for n in summary[case]:
            for name, s in summary[case][n].items():
                b = s["3+10"]
                print(f"{case:7s} n={n:>2} {name:5s} 3-10%: det {b['detected_pct']:5.1f} site {b['right_site_pct']:5.1f} "
                      f"hop {b['within_one_hop_pct']:5.1f} branch {b['right_branch_pct']:5.1f} | "
                      f"1%: det {s['1']['detected_pct']:5.1f} branch {s['1']['right_branch_pct']:5.1f}")
    print(f"-> {DASH.relative_to(ROOT)}, {FIG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
