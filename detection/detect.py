"""Explainable leak detector (M0): normalized-share residual + CUSUM.

Why shares:
  * total demand and pump ripple scale every branch, so absolute flow drifts;
  * a global gain error (the +-10% case) moves all branches together;
  * a leak on L1 raises L1's *share* of the branch flow and leaves the others.
So the detector watches share residuals, uses the manifold pressure drop only as
a confidence signal, and never reads the label column.

`StreamingDetector` is the single implementation; batch detection is just a loop
over it, so live and offline behaviour cannot silently diverge.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from hydropin import config

from .baseline import BRANCH_COLUMNS, Baseline, feature_frame

STREAM_KEYS = [f"share_{c}" for c in config.BRANCH_CHANNELS] + [
    "pressure_bar",
    "total_lpm",
    "main_lpm",
    *BRANCH_COLUMNS,
]


@dataclass
class DetectorConfig:
    window: int = 20
    cusum_k: float = 0.8
    cusum_h: float = 8.0
    min_branch_z: float = 2.5
    release_z: float = 0.3
    release_n: int = 10


@dataclass
class DetectionResult:
    frame: pd.DataFrame
    events: list[dict[str, Any]] = field(default_factory=list)


def estimate_leak_lpm(flow_branch: float, total: float, share0: float) -> float:
    """Invert share inflation to a leak flow (total includes the leak)."""
    if share0 >= 0.99 or share0 <= 0:
        return 0.0
    leak = (flow_branch - share0 * total) / (1.0 - share0)
    return max(0.0, float(leak))


class StreamingDetector:
    def __init__(self, baseline: Baseline, cfg: DetectorConfig | None = None):
        self.baseline = baseline
        self.cfg = cfg or DetectorConfig(window=baseline.window)
        self._buf: deque[dict[str, float]] = deque(maxlen=self.cfg.window)
        self._s = 0.0
        self._state = False
        self._release = 0

    def reset(self) -> None:
        self._buf.clear()
        self._s = 0.0
        self._state = False
        self._release = 0

    def update(self, row: dict[str, float]) -> dict[str, Any]:
        cfg = self.cfg
        self._buf.append({k: float(row[k]) for k in STREAM_KEYS})
        n = len(self._buf)
        mean = {k: sum(item[k] for item in self._buf) / n for k in STREAM_KEYS}
        z = {
            col: (mean[col] - self.baseline.mu[col]) / self.baseline.sigma[col] for col in self.baseline.columns
        }
        branch_z = {c: z[f"share_{c}"] for c in config.BRANCH_CHANNELS}
        best_branch = max(branch_z, key=branch_z.get)
        best_z = branch_z[best_branch]
        zp = z["pressure_bar"]

        self._s = max(0.0, self._s + best_z - cfg.cusum_k)
        candidate = self._s >= cfg.cusum_h and best_z >= cfg.min_branch_z

        if candidate:
            self._state = True
            self._release = 0
        elif self._state:
            if best_z < cfg.release_z:
                self._release += 1
                if self._release >= cfg.release_n:
                    self._state = False
                    self._release = 0
            else:
                self._release = 0

        share0 = self.baseline.mu[f"share_{best_branch}"]
        size = estimate_leak_lpm(mean[f"flow_{best_branch}_lpm"], mean["total_lpm"], share0)
        confidence = float(min(1.0, max(0.0, (max(best_z, 0.0) / 6.0 + max(-zp, 0.0) / 3.0) / 2.0)))
        return {
            "z_l1": z["share_l1"],
            "z_l2": z["share_l2"],
            "z_l3": z["share_l3"],
            "z_pressure": zp,
            "z_main": z["main_lpm"],
            "z_total": z["total_lpm"],
            "cusum": self._s,
            "alarm": self._state,
            "branch": best_branch if self._state else "none",
            "leak_lpm_est": size if self._state else 0.0,
            "confidence": confidence if self._state else 0.0,
        }


class Detector:
    def __init__(self, baseline: Baseline, cfg: DetectorConfig | None = None):
        self.baseline = baseline
        self.cfg = cfg or DetectorConfig(window=baseline.window)

    def detect_frame(self, df: pd.DataFrame) -> DetectionResult:
        feats = feature_frame(df)
        stream = StreamingDetector(self.baseline, self.cfg)
        records = [stream.update(feats.iloc[i].to_dict()) for i in range(len(df))]
        out = df.copy()
        for key in (
            "z_l1",
            "z_l2",
            "z_l3",
            "z_pressure",
            "z_main",
            "z_total",
            "cusum",
            "alarm",
            "branch",
            "leak_lpm_est",
            "confidence",
        ):
            out[key] = [rec[key] for rec in records]
        return DetectionResult(frame=out, events=extract_events(out))


def extract_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    alarm = df["alarm"].to_numpy(dtype=bool)
    start: int | None = None
    for i, a in enumerate(alarm):
        if a and start is None:
            start = i
        elif not a and start is not None:
            events.append(_event(df, start, i - 1))
            start = None
    if start is not None:
        events.append(_event(df, start, len(df) - 1))
    return events


def _event(df: pd.DataFrame, a: int, b: int) -> dict[str, Any]:
    seg = df.iloc[a : b + 1]
    branch_counts = seg.loc[seg["branch"] != "none", "branch"].value_counts()
    return {
        "start_ts": str(seg["ts"].iloc[0]),
        "end_ts": str(seg["ts"].iloc[-1]),
        "start_index": int(a),
        "end_index": int(b),
        "duration_s": float((b - a + 1) * config.SAMPLE_PERIOD_S),
        "branch": str(branch_counts.index[0]) if len(branch_counts) else "none",
        "leak_lpm_est": float(seg["leak_lpm_est"].max()),
        "confidence": float(seg["confidence"].max()),
    }
