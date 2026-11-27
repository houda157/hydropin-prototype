"""Live wrapper around the rev 1 bench detector: frames, notifications on state changes.

Telegram goes out on: LEAK (rising edge), a new sensor fault, and "resolved" (LEAK -> HEALTHY).
Sending runs in a daemon thread so a slow or failing Telegram never blocks ingest.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from detection.bench_detector import BenchConfig, BenchDetector, load_config

from . import notify

FAULT_NOTICE_COOLDOWN_S = 600.0


def _seconds(ts: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _send_async(text: str) -> None:
    threading.Thread(target=notify.send_telegram, args=(text,), daemon=True).start()


class BenchLive:
    def __init__(self, cfg: BenchConfig | None = None, send_notifications: bool = False):
        if cfg is None:
            cfg = load_config()          # data/model.json (trained) > data/bench_detector.json > defaults
        self.detector = BenchDetector(cfg)
        self.lock = threading.Lock()
        self.send_notifications = send_notifications
        self._prev_state: str | None = None
        self._prev_faults: set[str] = set()
        self._fault_sent: dict[str, float] = {}     # fault name -> frame time of its last notice

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
        now = _seconds(frame["ts"])
        for f in sorted(faults - self._prev_faults):
            # a fault that comes and goes (loose wire, noise at a threshold) is notified once per cooldown
            last = self._fault_sent.get(f)
            if last is None or now is None or now - last >= FAULT_NOTICE_COOLDOWN_S:
                out.append(f"HydroPin sensor fault: {f} ({frame['ts']})")
                if now is not None:
                    self._fault_sent[f] = now
        self._prev_state, self._prev_faults = state, faults
        return out

    def reset_baseline(self) -> None:
        with self.lock:
            self.detector.reset_baseline()

    def state_at(self, now: str) -> dict[str, Any] | None:
        with self.lock:
            return self.detector.state_at(now)
