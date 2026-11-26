"""Check real bench CSVs before they are used for training or evaluation.

    python -m tools.validate_dataset --dir data/real
    python -m tools.validate_dataset --csv data/real/leak_L1_01.csv --strict

It checks the things that silently ruin a dataset: wrong sample rate, missing
columns, unknown labels, duplicates, gaps, NaNs, out-of-range values and raw
pulse/ADC values that no longer match the calibrated columns.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from hydropin import config

FLOW_COLUMNS = [f"flow_{c}_lpm" for c in config.FLOW_CHANNELS]
RAW_COLUMNS = [f"raw_flow_{c}_pulses" for c in config.FLOW_CHANNELS]
REQUIRED = ["ts", "device", "seq", "label", *FLOW_COLUMNS, "pressure_bar"]


@dataclass
class Report:
    path: str
    rows: int = 0
    labels: dict[str, int] = field(default_factory=dict)
    median_dt_s: float | None = None
    max_gap_s: float | None = None
    gaps: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_frame(df: pd.DataFrame, expected_hz: float = 2.0) -> Report:
    rep = Report(path="", rows=int(len(df)))
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        rep.errors.append(f"missing columns: {missing}")
        return rep

    labels = df["label"].astype(str)
    counts = labels.value_counts().to_dict()
    rep.labels = {str(k): int(v) for k, v in counts.items()}
    unknown = sorted(set(rep.labels) - set(config.LABELS))
    if unknown:
        rep.errors.append(f"unknown labels: {unknown}")

    for col in FLOW_COLUMNS + ["pressure_bar"]:
        values = pd.to_numeric(df[col], errors="coerce")
        bad = int((~np.isfinite(values)).sum())
        if bad:
            rep.errors.append(f"{col}: {bad} non-numeric/NaN values")
    flows = df[FLOW_COLUMNS].apply(pd.to_numeric, errors="coerce")
    pressure = pd.to_numeric(df["pressure_bar"], errors="coerce")
    lo, hi = config.FLOW_RANGE_LPM
    out_flow = int(((flows < lo) | (flows > hi)).sum().sum())
    if out_flow:
        rep.errors.append(f"{out_flow} flow values outside {config.FLOW_RANGE_LPM} L/min")
    lo, hi = config.PRESSURE_RANGE_BAR
    out_p = int(((pressure < lo) | (pressure > hi)).sum())
    if out_p:
        rep.errors.append(f"{out_p} pressure values outside {config.PRESSURE_RANGE_BAR} bar")

    pressure_b = None
    if "pressure_b_bar" in df.columns and df["pressure_b_bar"].notna().any():
        pressure_b = pd.to_numeric(df["pressure_b_bar"], errors="coerce")
        bad = int((~np.isfinite(pressure_b)).sum())
        if bad:
            rep.errors.append(f"pressure_b_bar: {bad} non-numeric/NaN values")
        lo, hi = config.PRESSURE_B_RANGE_BAR
        out_pb = int(((pressure_b < lo) | (pressure_b > hi)).sum())
        if out_pb:
            rep.errors.append(
                f"{out_pb} pressure_b_bar values outside {config.PRESSURE_B_RANGE_BAR} bar"
            )

    ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    if ts.isna().any():
        rep.errors.append(f"{int(ts.isna().sum())} unparseable timestamps")
        return rep
    if not ts.is_monotonic_increasing:
        rep.errors.append("timestamps are not monotonically increasing; sort before training")
        return rep

    dup = int(df.duplicated(subset=["device", "seq"]).sum())
    rep.duplicates = dup
    if dup:
        rep.errors.append(f"{dup} duplicate (device, seq) rows")

    if len(ts) > 1:
        dt = ts.diff().dt.total_seconds().dropna()
        expected_dt = 1.0 / expected_hz
        rep.median_dt_s = float(dt.median())
        rep.max_gap_s = float(dt.max())
        if rep.median_dt_s < 0.5 * expected_dt or rep.median_dt_s > 2.0 * expected_dt:
            rep.errors.append(
                f"median sample interval {rep.median_dt_s:.3f}s is not ~{expected_hz:.1f} Hz "
                f"(expected {expected_dt:.3f}s)"
            )
        elif abs(rep.median_dt_s - expected_dt) > 0.1 * expected_dt:
            rep.warnings.append(
                f"median sample interval {rep.median_dt_s:.3f}s differs from {expected_dt:.3f}s"
            )
        rep.gaps = int((dt > 3.0 * expected_dt).sum())
        if rep.gaps:
            rep.warnings.append(
                f"{rep.gaps} gaps > {3.0 * expected_dt:.1f}s (max {rep.max_gap_s:.2f}s)"
            )

    # Raw pulse -> calibrated flow consistency. Startup windows are shorter and
    # dropout rows copy the previous raw block, so ignore both.
    if all(c in df.columns for c in RAW_COLUMNS):
        mask = pd.Series(True, index=df.index)
        if "dropout" in df.columns:
            mask &= ~df["dropout"].astype(bool)
        mask &= pd.Series(np.arange(len(df)) >= 4, index=df.index)
        mismatches = 0
        for c in config.FLOW_CHANNELS:
            raw = pd.to_numeric(df[f"raw_flow_{c}_pulses"], errors="coerce")
            expected = (
                raw / config.FLOW_MEASURE_WINDOW_S / config.FLOW_PULSES_PER_LPM * config.FLOW_GAIN
            )
            tol = np.maximum(0.15, 0.10 * flows[f"flow_{c}_lpm"].abs())
            mismatches += int(((expected - flows[f"flow_{c}_lpm"]).abs() > tol)[mask].sum())
        if mismatches:
            rep.warnings.append(
                f"{mismatches} raw-pulse/flow mismatches (window, gain or quantization drift)"
            )

    if "raw_pressure_adc" in df.columns:
        adc = pd.to_numeric(df["raw_pressure_adc"], errors="coerce")
        expected = adc / config.ADS_COUNTS * config.ADS_VOLTAGE_RANGE * config.PRESSURE_DIVIDER
        expected = expected * config.PRESSURE_GAIN + config.PRESSURE_OFFSET_BAR
        tol = np.maximum(0.05, 0.02 * pressure.abs())
        mismatches = int(((expected - pressure).abs() > tol).sum())
        if mismatches:
            rep.warnings.append(
                f"{mismatches} raw-ADC/pressure mismatches (divider, gain or offset drift)"
            )

    if pressure_b is not None and "raw_pressure_b_adc" in df.columns:
        adc_b = pd.to_numeric(df["raw_pressure_b_adc"], errors="coerce")
        expected_b = (
            adc_b / config.ADS_COUNTS * config.ADS_VOLTAGE_RANGE * config.PRESSURE_B_DIVIDER
        )
        expected_b = expected_b * config.PRESSURE_B_GAIN + config.PRESSURE_B_OFFSET_BAR
        tol_b = np.maximum(0.05, 0.02 * pressure_b.abs())
        mismatches_b = int(((expected_b - pressure_b).abs() > tol_b).sum())
        if mismatches_b:
            rep.warnings.append(
                f"{mismatches_b} raw-ADC/pressure_b mismatches (divider, gain or offset drift)"
            )

    return rep


def _print_report(reports: list[Report]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover
        for r in reports:
            print(r)
        return
    console = Console()
    table = Table(title="real-data validation", header_style="bold magenta")
    table.add_column("file", style="cyan", no_wrap=True)
    table.add_column("rows", justify="right")
    table.add_column("labels")
    table.add_column("dt (s)", justify="right")
    table.add_column("gaps", justify="right")
    table.add_column("dup", justify="right")
    table.add_column("errors", justify="right")
    table.add_column("warnings", justify="right")
    for r in reports:
        dt = f"{r.median_dt_s:.3f}" if r.median_dt_s is not None else "-"
        table.add_row(
            r.path,
            str(r.rows),
            ", ".join(f"{k}:{v}" for k, v in sorted(r.labels.items())),
            dt,
            str(r.gaps),
            str(r.duplicates),
            str(len(r.errors)),
            str(len(r.warnings)),
        )
    console.print(table)
    for r in reports:
        for msg in r.errors:
            console.print(f"[red]ERROR[/] {r.path}: {msg}")
        for msg in r.warnings:
            console.print(f"[yellow]WARN[/] {r.path}: {msg}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate real hydropin CSVs")
    parser.add_argument("--dir", default="data/real")
    parser.add_argument("--csv", action="append", default=[])
    parser.add_argument("--expected-hz", type=float, default=2.0)
    parser.add_argument("--strict", action="store_true", help="also fail on warnings")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.csv]
    if not paths:
        paths = sorted(Path(args.dir).glob("*.csv"))
    if not paths:
        print(f"no CSV files found (dir={args.dir})")
        return 1

    reports: list[Report] = []
    for path in paths:
        try:
            df = pd.read_csv(path, parse_dates=["ts"])
        except Exception as exc:  # noqa: BLE001 - report, do not crash the batch
            rep = Report(path=path.name, errors=[f"cannot read CSV: {exc}"])
            reports.append(rep)
            continue
        rep = validate_frame(df, expected_hz=args.expected_hz)
        rep.path = path.name
        reports.append(rep)

    _print_report(reports)
    errors = sum(len(r.errors) for r in reports)
    warnings = sum(len(r.warnings) for r in reports)
    if errors or (args.strict and warnings):
        print(f"FAILED: {errors} errors, {warnings} warnings")
        return 1
    print(f"OK: {len(reports)} files, {sum(r.rows for r in reports)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
