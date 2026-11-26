"""Validate, persist and optionally alert on one telemetry message."""
from __future__ import annotations

import threading
from typing import Any

from hydropin import config
from hydropin.messages import MessageError, validate_message

from . import notify, storage
from .bench_live import BenchLive
from .live_detect import LiveDetector


def ingest_message(
    msg: dict[str, Any],
    db_path: str | None = None,
    detector: LiveDetector | None = None,
    detector_lock: threading.Lock | None = None,
    send_notifications: bool = False,
    bench: BenchLive | None = None,
) -> dict[str, Any]:
    validate_message(msg)
    alert: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None
    with storage.db_session(db_path) as conn:
        run = storage.active_run(conn)
        # Real firmware always sends label="none"; the dashboard marks the leak
        # onset, and only live samples at/after that instant inherit the run
        # label. Simulator/replay messages keep their own labels.
        if msg.get("scenario") == "live" and msg.get("label") == "none":
            if (
                run
                and run.get("onset_ts")
                and run.get("label") in config.LABELS
                and str(msg["ts"]) >= str(run["onset_ts"])
            ):
                msg = {**msg, "label": run["label"]}
        inserted = storage.insert_reading(conn, msg)
        if inserted and detector is not None:
            flows = {c: msg["values"][f"flow_{c}_lpm"] for c in config.FLOW_CHANNELS}
            lock = detector_lock or threading.Lock()
            with lock:
                alert = detector.push(
                    flows,
                    float(msg["values"]["pressure_bar"]),
                    ts=msg["ts"],
                    device=msg["device"],
                )
            if alert is not None:
                storage.insert_alert(conn, alert)
        # rev 1 bench detector (F0 + PT1 + PT2): processed frame for the dashboard and replays
        if inserted and bench is not None:
            frame, _ = bench.push(msg, run_id=run["id"] if run else None)
            frame["id"] = storage.insert_frame(conn, frame)
    if alert is not None and send_notifications:
        notify.send_telegram(alert["message"])
    return {"inserted": inserted, "alert": alert, "frame": frame}


__all__ = ["ingest_message", "MessageError"]
