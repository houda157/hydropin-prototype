"""Report charts from the scoreboard and replays (needs matplotlib: .venv-sim).

    python -m detection.report_charts                       # dashboard/scoreboard.json, else scoreboard_sim.json
    python -m detection.report_charts --board path/scoreboard.json --replays path/replays

Writes report/figures/bench_ttd_hist.png (time to detect), bench_confusion.png (true tap vs the
detector's most likely tap, misses included) and bench_example_run.png (one detected leak run:
pressures, flow, P(leak), leak-on and alarm markers). Charts made from the simulated scoreboard are
stamped SIMULATION.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "report" / "figures"
ACCENT, BLUE, PURPLE, GREY = "#e4472a", "#1f6feb", "#8250df", "#9b9b95"


def _stamp(fig, board: dict) -> None:
    txt = "SIMULATION" if board.get("simulation") else "measured on the bench"
    fig.text(0.99, 0.01, f"{txt} - {board.get('headline', 'all runs')}", ha="right", va="bottom", fontsize=7,
             color=ACCENT if board.get("simulation") else "#1f8a4c")


def ttd_hist(board: dict, path: Path) -> None:
    head_ids = {r["id"] for r in board["runs"] if not any(r.get("split") for r in board["runs"]) or r.get("split") == "test"}
    rows = [r for r in board["runs"] if r["id"] in head_ids and r.get("detected")]
    d = [r["delay_s"] for r in rows]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    if d:
        ax.hist(d, bins=np.arange(0, max(d) + 2.5, 1.0), color=BLUE, edgecolor="white")
        ax.axvline(np.median(d), color=ACCENT, lw=1.2, ls="--", label=f"median {np.median(d):.1f} s")
        ax.legend(fontsize=8)
    s = board["summary"]
    ax.set_xlabel("time from tap opened to LEAK (s)")
    ax.set_ylabel("runs")
    ax.set_title(f"Time to detect: {s['detected']}/{s['leak_runs']} leaks reached LEAK", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    _stamp(fig, board)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def confusion(board: dict, path: Path) -> None:
    cm = board["confusion"]["taps"]
    rows = ["L1", "L2", "L3"]
    cols = ["L1", "L2", "L3", "missed"]
    M = np.array([[cm[r][c] for c in cols] for r in rows])
    fig, ax = plt.subplots(figsize=(4.4, 3.2))
    ax.imshow(M, cmap="Blues")
    for i in range(len(rows)):
        for j in range(len(cols)):
            ax.text(j, i, str(M[i, j]), ha="center", va="center", fontsize=10,
                    color="white" if M[i, j] > M.max() / 2 else "black")
    ax.set_xticks(range(len(cols)), ["L1 (A)", "L2 (B)", "L3 (B)", "missed"], fontsize=8)
    ax.set_yticks(range(len(rows)), ["L1 (A)", "L2 (B)", "L3 (B)"], fontsize=8)
    ax.set_xlabel("detector's most likely tap")
    ax.set_ylabel("tap really opened")
    b = board["confusion"]["branches"]
    ok = b["A"]["A"] + b["B"]["B"]
    tot = sum(sum(v.values()) for v in b.values())
    ax.set_title(f"Right branch {ok}/{tot}; L2 vs L3 share one sensor", fontsize=9)
    _stamp(fig, board)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def example_run(board: dict, replays: Path, path: Path) -> None:
    pick = next((r for r in board["runs"] if r.get("detected") and r.get("split") in (None, "test")
                 and (replays / f"{r['id']}.json").exists()), None)
    if pick is None:
        return
    rep = json.loads((replays / f"{pick['id']}.json").read_text(encoding="utf-8"))
    fr = rep["frames"]
    t = [f["t_s"] for f in fr]
    fig, axes = plt.subplots(3, 1, figsize=(6.4, 5.0), sharex=True)
    axes[0].plot(t, [f["pt1_bar"] for f in fr], color=BLUE, lw=1, label="PT1 (branch A)")
    axes[0].plot(t, [f["pt2_bar"] for f in fr], color=PURPLE, lw=1, label="PT2 (branch B)")
    axes[0].set_ylabel("bar")
    axes[0].legend(fontsize=7, loc="lower left")
    axes[1].plot(t, [f["flow_lpm"] for f in fr], color=GREY, lw=1, label="F0 flow")
    axes[1].plot(t, [f["flow_base_lpm"] for f in fr], color="#151515", lw=0.8, ls="--", label="baseline")
    axes[1].set_ylabel("L/min")
    axes[1].legend(fontsize=7, loc="upper left")
    axes[2].plot(t, [f["p_leak"] for f in fr], color=ACCENT, lw=1.2)
    axes[2].axhline(0.5, color=GREY, lw=0.6, ls=":")
    axes[2].set_ylabel("P(leak)")
    axes[2].set_xlabel("s")
    on = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_on"), None)
    off = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_off"), None)
    for ax in axes:
        if on is not None:
            ax.axvline(on, color="#151515", lw=0.8)
        if off is not None:
            ax.axvline(off, color="#151515", lw=0.8, ls="--")
        if pick.get("delay_s") is not None and on is not None:
            ax.axvline(on + pick["delay_s"], color=ACCENT, lw=0.8)
        ax.grid(alpha=0.25)
    tap = rep["label"].split("_", 1)[1]
    axes[0].set_title(f"{tap} opened at {on:.0f} s, LEAK on branch {pick['branch']} after {pick['delay_s']} s "
                      f"(black: tap on/off, red: alarm)", fontsize=8)
    _stamp(fig, board)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", type=Path)
    ap.add_argument("--replays", type=Path, default=ROOT / "dashboard" / "replays")
    ap.add_argument("--out", type=Path, default=FIG)
    a = ap.parse_args(argv)
    board_path = a.board or next(p for p in (ROOT / "dashboard" / "scoreboard.json",
                                             ROOT / "dashboard" / "scoreboard_sim.json") if p.exists())
    board = json.loads(board_path.read_text(encoding="utf-8"))
    a.out.mkdir(parents=True, exist_ok=True)
    ttd_hist(board, a.out / "bench_ttd_hist.png")
    if "confusion" in board:
        confusion(board, a.out / "bench_confusion.png")
    example_run(board, a.replays, a.out / "bench_example_run.png")
    print(f"charts from {board_path.name} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
