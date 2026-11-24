"""Evaluate the M0 detector on labelled runs.

    python -m detection.evaluate --dir data/raw
    python -m detection.evaluate --baseline data/raw/baseline_seed1.csv --runs data/raw/leak_L1_seed2.csv

The evaluation is intentionally strict: it scores every sample (not just
events), reports detection delay, branch attribution and false alarms per
minute, and refuses to hide calibration-drift failures.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from hydropin import config

from .baseline import Baseline
from .detect import Detector, DetectorConfig


@dataclass
class RunEval:
    name: str
    true_label: str
    samples: int
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    onset_s: float | None = None
    first_alarm_s: float | None = None
    delay_s: float | None = None
    branch_true: str = "none"
    branch_pred: str = "none"
    branch_ok: bool | None = None
    false_alarms_per_min: float = 0.0


def evaluate_run(name: str, df: pd.DataFrame, detector: Detector) -> RunEval:
    result = detector.detect_frame(df)
    pred = result.frame["alarm"].to_numpy(dtype=bool)
    true = (df["label"].to_numpy() != "none").astype(bool)

    tp = int(np.sum(pred & true))
    fp = int(np.sum(pred & ~true))
    fn = int(np.sum(~pred & true))
    tn = int(np.sum(~pred & ~true))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    true_labels = [lab for lab in pd.unique(df["label"]) if lab != "none"]
    ev = RunEval(
        name=name,
        true_label=str(true_labels[0]) if true_labels else "none",
        samples=len(df),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        false_alarms_per_min=fp / max(1e-9, len(df) * config.SAMPLE_PERIOD_S / 60.0),
    )

    true_idx = np.flatnonzero(true)
    if len(true_idx):
        ev.onset_s = float(true_idx[0] * config.SAMPLE_PERIOD_S)
        true_branch = str(df["label"].iloc[true_idx[0]]).replace("leak_", "").lower()
        ev.branch_true = true_branch
    pred_idx = np.flatnonzero(pred)
    if len(pred_idx):
        ev.first_alarm_s = float(pred_idx[0] * config.SAMPLE_PERIOD_S)
        if ev.onset_s is not None:
            ev.delay_s = ev.first_alarm_s - ev.onset_s
        alarm_seg = result.frame.loc[pred, "branch"]
        alarm_seg = alarm_seg[alarm_seg != "none"]
        if len(alarm_seg):
            ev.branch_pred = str(alarm_seg.mode().iloc[0])
    if ev.branch_true != "none" and ev.branch_pred != "none":
        ev.branch_ok = ev.branch_pred == ev.branch_true
    return ev


def evaluate_dir(directory: str | Path = "data/raw", cfg: DetectorConfig | None = None) -> tuple[list[RunEval], dict]:
    directory = Path(directory)
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSV runs in {directory}; run the simulator first")

    baselines = [f for f in files if f.name.startswith("baseline")]
    if not baselines:
        raise FileNotFoundError("need at least one baseline_*.csv run")
    baseline_df = pd.read_csv(baselines[0], parse_dates=["ts"])
    baseline = Baseline.fit_raw(baseline_df, window=(cfg or DetectorConfig()).window)
    detector = Detector(baseline, cfg)

    results: list[RunEval] = []
    for f in files:
        df = pd.read_csv(f, parse_dates=["ts"])
        results.append(evaluate_run(f.stem, df, detector))

    leak_evals = [r for r in results if r.true_label != "none"]
    tp = sum(r.tp for r in leak_evals)
    fp = sum(r.fp for r in leak_evals)
    fn = sum(r.fn for r in leak_evals)
    micro = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
    }
    micro["f1"] = (
        2 * micro["precision"] * micro["recall"] / (micro["precision"] + micro["recall"])
        if micro["precision"] + micro["recall"]
        else 0.0
    )
    return results, micro


def print_report(results: list[RunEval], micro: dict) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover
        for r in results:
            print(asdict(r))
        print(micro)
        return

    console = Console()
    table = Table(title="M0 detector evaluation", header_style="bold magenta")
    table.add_column("run", style="cyan", no_wrap=True)
    table.add_column("true")
    table.add_column("alarm%", justify="right")
    table.add_column("P", justify="right")
    table.add_column("R", justify="right")
    table.add_column("F1", justify="right")
    table.add_column("delay", justify="right")
    table.add_column("branch", justify="right")
    table.add_column("FA/min", justify="right")
    for r in results:
        alarm_pct = 100.0 * (r.tp + r.fp) / max(1, r.samples)
        delay = f"{r.delay_s:.1f}s" if r.delay_s is not None else "-"
        branch = "n/a"
        if r.branch_true != "none":
            branch = f"{r.branch_pred}/{r.branch_true}" + ("" if r.branch_ok else " X")
        colour = "green" if r.true_label == "none" and r.fp == 0 else ("red" if r.fn else "white")
        table.add_row(
            r.name,
            r.true_label,
            f"{alarm_pct:.1f}",
            f"{r.precision:.2f}",
            f"{r.recall:.2f}",
            f"{r.f1:.2f}",
            delay,
            branch,
            f"{r.false_alarms_per_min:.2f}",
            style=colour,
        )
    console.print(table)
    console.print(
        f"[bold]micro[/] over leak runs: P={micro['precision']:.3f} R={micro['recall']:.3f} "
        f"F1={micro['f1']:.3f} (TP={micro['tp']} FP={micro['fp']} FN={micro['fn']})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the hydropin M0 detector")
    parser.add_argument("--dir", default="data/raw")
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--max-fa-per-min", type=float, default=1.0)
    parser.add_argument("--strict", action="store_true", help="exit 1 if quality gates fail")
    args = parser.parse_args(argv)

    results, micro = evaluate_dir(args.dir)
    print_report(results, micro)

    if not args.strict:
        return 0
    failures = []
    if micro["recall"] < args.min_recall:
        failures.append(f"recall {micro['recall']:.2f} < {args.min_recall}")
    healthy = [r for r in results if r.true_label == "none"]
    for r in healthy:
        if r.false_alarms_per_min > args.max_fa_per_min:
            failures.append(f"{r.name}: {r.false_alarms_per_min:.2f} FA/min")
    leak_runs = [r for r in results if r.true_label != "none"]
    for r in leak_runs:
        if r.branch_ok is False:
            failures.append(f"{r.name}: wrong branch {r.branch_pred} != {r.branch_true}")
    if failures:
        print("QUALITY GATES FAILED:")
        for f in failures:
            print(" -", f)
        return 1
    print("quality gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
