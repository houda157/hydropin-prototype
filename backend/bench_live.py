"""Live wrapper around the rev 1 bench detector: frames, notifications on state changes.

Telegram goes out on: LEAK (rising edge), a new sensor fault, and "resolved" (LEAK -> HEALTHY).
Sending runs in a daemon thread so a slow or failing Telegram never blocks ingest.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from detection.bench_detector import BenchConfig, BenchDetector

from . import notify

DEFAULT_CONFIG = Path("data/bench_detector.json")


def _send_async(text: str) -> None:
    threading.Thread(target=notify.send_telegram, args=(text,), daemon=True).start()


class BenchLive:
    def __init__(self, cfg: BenchConfig | None = None, send_notifications: bool = False):
        if cfg is None and DEFAULT_CONFIG.exists():
            cfg = BenchConfig.from_json(DEFAULT_CONFIG)
        self.detector = BenchDetector(cfg)
        self.lock = threading.Lock()
        self.send_notifications = send_notifications
        self._prev_state: str | None = None
        self._prev_faults: set[str] = set()

    def push(self, msg: dict[str, Any], run_id: int | None = None) -> tuple[dict[str, Any], list[str]]:
        with self.lock:
            frame = self.detector.update_message(msg)
        frame["run_id"] = run_id
        notices = self._notices(frame)
        if notices and self.send_notifications:
            for text in notices:
                _send_async(text)
        return frame, notices

    def _notices(self, frame: dict[str, Any]) -> list[str]:
        out = []
        state = frame["state"]
        if state == "LEAK" and self._prev_state != "LEAK":
            br = frame.get("branch") or "?"
            out.append(f"HydroPin LEAK on branch {br}: p={frame['p_leak']:.2f}, "
                       f"~{frame['leak_lpm']:.2f} L/min above baseline ({frame['ts']})")
        if self._prev_state == "LEAK" and state == "HEALTHY":
            out.append(f"HydroPin resolved: back to HEALTHY, {frame['lost_l']:.2f} L lost ({frame['ts']})")
        faults = set(frame.get("faults") or []) - {"data_gap"}
        for f in sorted(faults - self._prev_faults):
            out.append(f"HydroPin sensor fault: {f} ({frame['ts']})")
        self._prev_state, self._prev_faults = state, faults
        return out

    def reset_baseline(self) -> None:
        with self.lock:
            self.detector.reset_baseline()

    def state_at(self, now: str) -> dict[str, Any] | None:
        with self.lock:
            return self.detector.state_at(now)
