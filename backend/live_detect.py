"""Streaming leak detector used by the backend.

Emits one alert on the rising edge of an alarm (not every sample), so Telegram
and the dashboard are not spammed.
"""
from __future__ import annotations

from typing import Any

from detection.baseline import Baseline, feature_row
from detection.detect import DetectorConfig, StreamingDetector

from .storage import utc_now


class LiveDetector:
    def __init__(self, baseline: Baseline, cfg: DetectorConfig | None = None):
        self.stream = StreamingDetector(baseline, cfg)
        self._previous_alarm = False

    def push(
        self,
        flows_lpm: dict[str, float],
        pressure_bar: float,
        *,
        ts: str | None = None,
        device: str | None = None,
    ) -> dict[str, Any] | None:
        rec = self.stream.update(feature_row(flows_lpm, pressure_bar))
        alert = None
        if rec["alarm"] and not self._previous_alarm:
            branch = str(rec["branch"])
            size = float(rec["leak_lpm_est"])
            alert = {
                "ts": ts or utc_now(),
                "device": device,
                "branch": branch,
                "leak_lpm_est": round(size, 3),
                "confidence": round(float(rec["confidence"]), 3),
                "method": "M0-share-cusum",
                "message": f"Leak suspected on {branch.upper()} (~{size:.2f} L/min)",
            }
        self._previous_alarm = bool(rec["alarm"])
        return alert
