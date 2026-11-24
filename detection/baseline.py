"""Healthy-bench baseline: robust centre and spread of *normalized* features.

Absolute flow drifts with demand and pump behaviour, and a 10% gain error moves
every channel at once. Branch *shares* (flow_c / sum(branches)) cancel both, so
they are the primary leak signal. Median + MAD is used so one hiccup cannot
widen the normal band forever.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydropin import config

FLOW_COLUMNS = [f"flow_{c}_lpm" for c in config.FLOW_CHANNELS]
BRANCH_COLUMNS = [f"flow_{c}_lpm" for c in config.BRANCH_CHANNELS]
FEATURE_COLUMNS = [f"share_{c}" for c in config.BRANCH_CHANNELS] + ["pressure_bar", "total_lpm", "main_lpm"]
SIGMA_FLOOR = {
    **{f"share_{c}": 0.015 for c in config.BRANCH_CHANNELS},
    "pressure_bar": 0.010,
    "total_lpm": 0.080,
    "main_lpm": 0.080,
}


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    total = out[BRANCH_COLUMNS].sum(axis=1)
    out["total_lpm"] = total
    out["main_lpm"] = out["flow_main_lpm"]
    for c in config.BRANCH_CHANNELS:
        out[f"share_{c}"] = out[f"flow_{c}_lpm"] / total.clip(lower=1e-9)
    return out


def feature_row(flows_lpm: dict[str, float], pressure_bar: float) -> dict[str, float]:
    """One live sample -> the feature row expected by StreamingDetector."""
    total = sum(float(flows_lpm[c]) for c in config.BRANCH_CHANNELS)
    row: dict[str, float] = {
        "pressure_bar": float(pressure_bar),
        "total_lpm": total,
        "main_lpm": float(flows_lpm["main"]),
    }
    for c in config.BRANCH_CHANNELS:
        row[f"flow_{c}_lpm"] = float(flows_lpm[c])
        row[f"share_{c}"] = float(flows_lpm[c]) / max(total, 1e-9)
    return row


def rolling_frame(df: pd.DataFrame, window: int, columns: list[str] | None = None) -> pd.DataFrame:
    cols = columns or FEATURE_COLUMNS
    return df[cols].rolling(window=window, min_periods=1).mean()


@dataclass
class Baseline:
    mu: dict[str, float]
    sigma: dict[str, float]
    window: int = 20
    columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fit(cls, features: pd.DataFrame, window: int = 20, warmup_s: float = 0.0) -> "Baseline":
        warmup = int(round(warmup_s / config.SAMPLE_PERIOD_S))
        use = features.iloc[warmup:] if len(features) > warmup else features
        if use.empty:
            raise ValueError("baseline run is empty")
        roll = rolling_frame(use, window)
        mu: dict[str, float] = {}
        sigma: dict[str, float] = {}
        for col in FEATURE_COLUMNS:
            series = roll[col].to_numpy(dtype=float)
            centre = float(np.median(series))
            mad = float(np.median(np.abs(series - centre)))
            mu[col] = centre
            sigma[col] = max(1.4826 * mad, SIGMA_FLOOR[col])
        return cls(mu=mu, sigma=sigma, window=window, meta={"samples": int(len(use))})

    @classmethod
    def fit_raw(cls, df: pd.DataFrame, window: int = 20, warmup_s: float = 0.0) -> "Baseline":
        return cls.fit(feature_frame(df), window=window, warmup_s=warmup_s)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"window": self.window, "mu": self.mu, "sigma": self.sigma, "columns": self.columns, "meta": self.meta}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Baseline":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            mu=payload["mu"],
            sigma=payload["sigma"],
            window=int(payload.get("window", 20)),
            columns=payload.get("columns", list(FEATURE_COLUMNS)),
            meta=payload.get("meta", {}),
        )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fit a healthy-bench baseline")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="models/baseline.json")
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--warmup", type=float, default=0.0)
    args = parser.parse_args(argv)
    df = pd.read_csv(args.csv, parse_dates=["ts"])
    baseline = Baseline.fit_raw(df, window=args.window, warmup_s=args.warmup)
    path = baseline.save(args.out)
    print(f"baseline saved to {path}")
    print("mu", {k: round(v, 4) for k, v in baseline.mu.items()})
    print("sigma", {k: round(v, 4) for k, v in baseline.sigma.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
