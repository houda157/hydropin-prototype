"""Leak episodes from the processed frames. Stateless: the database is the state, so an
episode opened before a backend restart is picked up again."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import storage


def track_leak(conn: sqlite3.Connection, frame: dict[str, Any]) -> int | None:
    """LEAK opens or updates the episode; PUMP_OFF marks it (HEALTHY can no longer prove a
    repair after the baseline is re-learned); HEALTHY closes it; other states change nothing."""
    state = frame.get("state")
    open_ = storage.get_open_leak(conn)
    if state == "LEAK":
        leak_id = open_["id"] if open_ else storage.open_leak(
            conn, str(frame["ts"]), frame.get("branch"), frame.get("flow_base_lpm"))
        storage.update_leak(conn, leak_id, frame.get("branch"), frame.get("leak_lpm") or 0.0, frame.get("lost_l") or 0.0)
        return leak_id
    if open_ is None:
        return None
    if state == "PUMP_OFF":
        storage.mark_pump_stopped(conn, open_["id"])
    elif state == "HEALTHY" and not open_["pump_stopped"]:
        storage.close_leak(conn, open_["id"], str(frame["ts"]))
    return open_["id"]
