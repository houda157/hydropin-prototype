"""Read recorded bench runs back from the backend database (shared by training and export).

A run = one row of `runs` that was stopped, its readings (as contract messages, so the detector
re-runs from the raw values) and its ground-truth events. Labels and events go to scoring and to
the train/test split only; the detector never sees them.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _raw(raw_json: str | None) -> dict[str, Any]:
    """Raw counts as sent by the board (the detector recomputes bar from them)."""
    try:
        return json.loads(raw_json or "{}")
    except ValueError:
        return {}


def load_runs(db: str | Path, min_readings: int = 20) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    out = []
    try:
        runs = conn.execute("SELECT * FROM runs WHERE stopped_ts IS NOT NULL ORDER BY id").fetchall()
        for run in runs:
            rd = conn.execute("SELECT * FROM readings WHERE ts >= ? AND ts <= ? ORDER BY ts",
                              (run["started_ts"], run["stopped_ts"])).fetchall()
            if len(rd) < min_readings:
                continue
            msgs = [{"ts": r["ts"], "device": r["device"], "seq": r["seq"], "raw": _raw(r["raw_json"]),
                     "values": {"flow_main_lpm": r["flow_main_lpm"], "pressure_bar": r["pressure_bar"],
                                "pressure_b_bar": r["pressure_b_bar"]}} for r in rd]
            evs = [dict(e) for e in conn.execute("SELECT ts, type, tap FROM events WHERE run_id = ? ORDER BY ts",
                                                  (run["id"],))]
            label = run["label"]
            if label.startswith("leak_") and not any(e["type"] == "leak_on" for e in evs) and run["onset_ts"]:
                evs.append({"ts": run["onset_ts"], "type": "leak_on", "tap": label.split("_")[1]})
            cols = run.keys()
            meta = {k: run[k] for k in ("opening", "measured_leak_lpm", "blind", "notes", "started_ts") if k in cols}
            out.append({"id": f"bench_run_{run['id']}", "run_id": int(run["id"]), "label": label,
                        "msgs": msgs, "events": evs, "meta": meta})
    finally:
        conn.close()
    return out
