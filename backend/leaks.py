"""Leak episodes from the processed frames. Stateless: the database is the state, so an
episode opened before a backend restart is picked up again."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import storage

# states in which the detector learns a new baseline, with the leak possibly inside it
RELEARN_STATES = ("PUMP_OFF", "SETTLING", "LEARNING")


def track_leak(conn: sqlite3.Connection, frame: dict[str, Any]) -> int | None:
    """LEAK opens or updates the episode; HEALTHY closes it (the sensors confirm the repair).
    PUMP_OFF, SETTLING and LEARNING mean the detector is re-learning its baseline (pump stop,
    baseline reset, new detector process) with the leak possibly inside it: from then on HEALTHY
    proves nothing, so the episode is marked (pump_stopped = 1) and stays open until the farmer
    taps "I fixed it". WATCH and OFFLINE change nothing."""
    state = frame.get("state")
    open_ = storage.get_open_leak(conn)
    if state == "LEAK":
        leak_id = open_["id"] if open_ else storage.open_leak(
            conn, str(frame["ts"]), frame.get("branch"), frame.get("flow_base_lpm"))
        storage.update_leak(conn, leak_id, frame.get("branch"), frame.get("leak_lpm") or 0.0, frame.get("lost_l") or 0.0)
        return leak_id
    if open_ is None:
        return None
    if state in RELEARN_STATES:
        storage.mark_pump_stopped(conn, open_["id"])
    elif state == "HEALTHY" and not open_["pump_stopped"]:
        storage.close_leak(conn, open_["id"], str(frame["ts"]))
    return open_["id"]
