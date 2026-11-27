"""Validate and persist one telemetry message, run the bench detector, record LEAK alerts."""
from __future__ import annotations

from typing import Any

from hydropin import config
from hydropin.messages import MessageError, normalize_message, validate_message

from . import leaks, storage
from .bench_live import BenchLive


def ingest_message(
    msg: dict[str, Any],
    db_path: str | None = None,
    bench: BenchLive | None = None,
) -> dict[str, Any]:
    msg = normalize_message(msg)
    validate_message(msg)
    alert: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None
    with storage.db_session(db_path) as conn:
        placed = storage.place_reading(conn, msg)
        if placed is None:                      # MQTT redelivery of a stored message
            return {"inserted": False, "alert": None, "frame": None}
        boot, ts = placed
        device_ts = msg["ts"]
        if ts != device_ts:                     # board clock not set yet: laptop time
            msg = {**msg, "ts": ts}
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
        inserted = storage.insert_reading(conn, msg, boot=boot, device_ts=device_ts)
        # bench detector (F0 + PT1 + PT2): processed frame for the dashboard and replays.
        # Telegram is sent by BenchLive itself; the LEAK rising edge is also kept as an alert row.
        if inserted and bench is not None:
            frame, notices = bench.push(msg, run_id=run["id"] if run else None)
            frame["id"] = storage.insert_frame(conn, frame)
            leaks.track_leak(conn, frame)
            leak_notice = next((n for n in notices if n.startswith("HydroPin LEAK")), None)
            if leak_notice is not None:
                alert = {"ts": frame["ts"], "device": msg["device"], "branch": frame.get("branch"),
                         "leak_lpm_est": frame.get("leak_lpm") or 0.0, "confidence": frame.get("p_leak") or 0.0,
                         "method": "bench: flow + M2 fusion", "message": leak_notice}
                alert["id"] = storage.insert_alert(conn, alert)
    return {"inserted": inserted, "alert": alert, "frame": frame}


__all__ = ["ingest_message", "MessageError"]
