"""Twin vs real: measured bench values next to the bench twin's predictions.

    python -m twin.compare --db data/hydropin.db [--pred twin/predictions.json]

Measured (from the campaign database, labels used for grouping only):
  * healthy operating point: mean PT1, PT2, F0 over the 30 s before "leak on" of every leak run
    (and over quiet runs);
  * per tap: mean change in PT1, PT2 and F0 while the tap is open (10 s after "leak on" to
    "leak off"), against those 30 s.

Twin predictions (twin/predictions.json, written by the calibrated bench twin):
  {"simulation": true, "healthy": {"pt1_bar": .., "pt2_bar": .., "flow_lpm": ..},
   "leaks": {"L1": {"dpt1_bar": .., "dpt2_bar": .., "dflow_lpm": ..}, "L2": {...}, "L3": {...}}}

Writes twin/out/twin_vs_real.json and report/figures/twin_vs_real.png. Without predictions the
chart shows the measured values only and says the twin is missing.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "twin" / "out" / "twin_vs_real.json"
FIG = ROOT / "report" / "figures" / "twin_vs_real.png"
TAPS = ("L1", "L2", "L3")


def measured(db: Path) -> dict:
    from detection.bench_detector import run_messages
    from detection.campaign import load_runs
    from detection.replay import build_replay

    healthy, drops = [], defaultdict(list)
    for r in load_runs(db):
        rep = build_replay(run_messages(r["msgs"]), r["events"], run_id=r["id"], label=r["label"],
                           simulation=False, source="bench", meta=r["meta"])
        fr = [f for f in rep["frames"] if f["pt2_bar"] is not None]
        on = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_on"), None)
        off = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_off"), None)
        if on is None:
            if r["label"] == "none" and not rep["events"]:
                q = [(f["pt1_bar"], f["pt2_bar"], f["flow_lpm"]) for f in fr if f["state"] == "HEALTHY"]
                if len(q) > 20:
                    healthy.append(np.mean(q, axis=0))
            continue
        base = [(f["pt1_bar"], f["pt2_bar"], f["flow_lpm"]) for f in fr if on - 30 <= f["t_s"] < on and f["state"] in ("HEALTHY", "WATCH")]
        leak = [(f["pt1_bar"], f["pt2_bar"], f["flow_lpm"]) for f in fr if f["t_s"] >= on + 10 and (off is None or f["t_s"] <= off)]
        if len(base) < 10 or len(leak) < 10:
            continue
        b = np.mean(base, axis=0)
        healthy.append(b)
        drops[r["label"].split("_", 1)[1]].append(np.mean(leak, axis=0) - b)
    out = {"healthy": None, "leaks": {}}
    if healthy:
        h = np.mean(healthy, axis=0)
        out["healthy"] = {"pt1_bar": round(float(h[0]), 4), "pt2_bar": round(float(h[1]), 4), "flow_lpm": round(float(h[2]), 4),
                          "n_runs": len(healthy)}
    for t in TAPS:
        if drops[t]:
            d = np.mean(drops[t], axis=0)
            out["leaks"][t] = {"dpt1_bar": round(float(d[0]), 4), "dpt2_bar": round(float(d[1]), 4),
                               "dflow_lpm": round(float(d[2]), 4), "n_runs": len(drops[t])}
    return out


def plot(meas: dict, pred: dict | None, path: Path, source: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(9.5, 3.0))
    for ax, key, title in zip(axes, ("dpt1_bar", "dpt2_bar", "dflow_lpm"),
                              ("PT1 change (bar)", "PT2 change (bar)", "F0 change (L/min)")):
        taps = [t for t in TAPS if t in meas["leaks"]]
        x = np.arange(len(taps))
        ax.bar(x - 0.18, [meas["leaks"][t][key] for t in taps], 0.36, color="#1f6feb", label="measured")
        if pred:
            ax.bar(x + 0.18, [pred["leaks"].get(t, {}).get(key, np.nan) for t in taps], 0.36, color="#e4472a",
                   label="twin (simulation)")
        ax.set_xticks(x, taps)
        ax.set_title(title, fontsize=9)
        ax.axhline(0, color="#151515", lw=0.6)
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(fontsize=7)
    note = "" if pred else "  (twin predictions missing: twin/predictions.json)"
    fig.suptitle(f"Twin vs real, per tap - measured from {source}{note}", fontsize=9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path("data/hydropin.db"))
    ap.add_argument("--pred", type=Path, default=ROOT / "twin" / "predictions.json")
    ap.add_argument("--fig", type=Path, default=FIG)
    a = ap.parse_args(argv)
    meas = measured(a.db)
    pred = json.loads(a.pred.read_text(encoding="utf-8")) if a.pred.exists() else None
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"measured": meas, "twin": pred, "db": a.db.as_posix()}, indent=1), encoding="utf-8")
    if meas["leaks"]:
        plot(meas, pred, a.fig, a.db.name)
    print(json.dumps(meas, indent=1))
    print(f"-> {OUT.relative_to(ROOT)}" + (f", {a.fig}" if meas["leaks"] else " (no leak runs: no chart)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
