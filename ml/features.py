"""Causal, run-local features for leak classification.

Every feature at time t only uses samples <= t. Runs are featurized separately
so a rolling window never crosses a run boundary (a classic leakage bug).
"""
from __future__ import annotations

import pandas as pd

from hydropin import config

FLOW_COLUMNS = [f"flow_{c}_lpm" for c in config.FLOW_CHANNELS]
BRANCH_COLUMNS = [f"flow_{c}_lpm" for c in config.BRANCH_CHANNELS]
BASE_COLUMNS = FLOW_COLUMNS + ["pressure_bar"]
WINDOWS = (5, 15, 30)
LONG_WINDOW = 60


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    total = out[BRANCH_COLUMNS].sum(axis=1)
    out["total_lpm"] = total
    out["main_minus_sum"] = out["flow_main_lpm"] - total
    for c in config.BRANCH_CHANNELS:
        out[f"share_{c}"] = out[f"flow_{c}_lpm"] / total.clip(lower=1e-9)

    for w in WINDOWS:
        for col in BASE_COLUMNS:
            mean = out[col].rolling(w, min_periods=1).mean()
            out[f"{col}_m{w}"] = mean
            out[f"{col}_d{w}"] = out[col] - mean
        for c in config.BRANCH_CHANNELS:
            share = out[f"share_{c}"]
            mean = share.rolling(w, min_periods=1).mean()
            out[f"share_{c}_m{w}"] = mean
            out[f"share_{c}_d{w}"] = share - mean

    for c in config.BRANCH_CHANNELS:
        med = out[f"share_{c}"].rolling(LONG_WINDOW, min_periods=5).median()
        out[f"share_{c}_dev{LONG_WINDOW}"] = out[f"share_{c}"] - med

    for col in BASE_COLUMNS:
        out[f"{col}_slope30"] = (out[col] - out[col].shift(30)) / 30.0

    out = out.fillna(0.0)
    return out


def feature_columns() -> list[str]:
    cols: list[str] = ["total_lpm", "main_minus_sum"]
    for c in config.BRANCH_CHANNELS:
        cols.append(f"share_{c}")
    for w in WINDOWS:
        for col in BASE_COLUMNS:
            cols += [f"{col}_m{w}", f"{col}_d{w}"]
        for c in config.BRANCH_CHANNELS:
            cols += [f"share_{c}_m{w}", f"share_{c}_d{w}"]
    for c in config.BRANCH_CHANNELS:
        cols.append(f"share_{c}_dev{LONG_WINDOW}")
    for col in BASE_COLUMNS:
        cols.append(f"{col}_slope30")
    return cols
