"""Apply a leak label from a known onset time to a real telemetry CSV.

    python -m tools.label_csv --csv data/real/run.csv --label leak_L1 --onset 2026-11-24T12:00:30Z
    python -m tools.label_csv --csv data/real/run.csv --label leak_L2 --onset 45

`--onset` accepts an ISO-8601 timestamp or a number of seconds from the first
sample. Samples before onset are labelled `none` unless `--before` says
otherwise. This is the post-hoc equivalent of the dashboard's "Mark leak onset".
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from hydropin import config


def _onset_timestamp(ts: pd.Series, onset: str | float) -> pd.Timestamp:
    first = ts.iloc[0]
    try:
        seconds = float(onset)
    except (TypeError, ValueError):
        parsed = pd.Timestamp(str(onset))
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        return parsed
    return first + pd.Timedelta(seconds=seconds)


def apply_label(
    df: pd.DataFrame,
    label: str,
    onset: str | float,
    before: str = "none",
) -> pd.DataFrame:
    if label not in config.LABELS:
        raise ValueError(f"label must be one of {config.LABELS}")
    if before not in config.LABELS:
        raise ValueError(f"before must be one of {config.LABELS}")
    if "ts" not in df.columns:
        raise ValueError("CSV has no ts column")
    ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    if ts.isna().any():
        raise ValueError("CSV has unparseable timestamps")
    if not ts.is_monotonic_increasing:
        raise ValueError("timestamps are not sorted; sort the CSV first")

    onset_ts = _onset_timestamp(ts, onset)
    out = df.copy()
    out["label"] = before
    out.loc[ts >= onset_ts, "label"] = label
    return out


def _format_ts(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, utc=True)
    return ts.dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label a real run from a leak onset")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out")
    parser.add_argument("--label", required=True, choices=config.LABELS)
    parser.add_argument("--onset", required=True, help="ISO-8601 or seconds from first sample")
    parser.add_argument("--before", default="none", choices=config.LABELS)
    args = parser.parse_args(argv)

    path = Path(args.csv)
    df = pd.read_csv(path)
    try:
        out = apply_label(df, args.label, args.onset, before=args.before)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    out_path = Path(args.out) if args.out else path.with_name(f"{path.stem}_labelled.csv")
    out["ts"] = _format_ts(out["ts"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    counts = out["label"].value_counts().to_dict()
    print(f"wrote {out_path} ({len(out)} rows)")
    print("labels:", {str(k): int(v) for k, v in counts.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
