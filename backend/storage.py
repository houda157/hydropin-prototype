"""SQLite persistence: readings, alerts and labelled runs.

Idempotent ingestion is enforced by PRIMARY KEY(device, seq), so MQTT QoS 1
redelivery cannot duplicate rows.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(os.environ.get("HYDROPIN_DB", "data/hydropin.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    device TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    scenario TEXT,
    label TEXT,
    flow_main_lpm REAL, flow_l1_lpm REAL, flow_l2_lpm REAL, flow_l3_lpm REAL,
    pressure_bar REAL, pressure_b_bar REAL,
    raw_json TEXT,
    dropout INTEGER, ripple INTEGER, clipped INTEGER,
    received_ts TEXT NOT NULL,
    PRIMARY KEY (device, seq)
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    device TEXT,
    branch TEXT,
    leak_lpm_est REAL,
    confidence REAL,
    method TEXT,
    message TEXT,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ts TEXT NOT NULL,
    stopped_ts TEXT,
    onset_ts TEXT,
    label TEXT NOT NULL,
    notes TEXT
);
"""

RAW_FIELDS = {
    "raw_flow_main_pulses": "flow_main_pulses",
    "raw_flow_l1_pulses": "flow_l1_pulses",
    "raw_flow_l2_pulses": "flow_l2_pulses",
    "raw_flow_l3_pulses": "flow_l3_pulses",
    "raw_pressure_adc": "pressure_adc",
    "raw_pressure_b_adc": "pressure_b_adc",
}

READING_COLUMNS = [
    "ts",
    "device",
    "seq",
    "scenario",
    "label",
    "flow_main_lpm",
    "flow_l1_lpm",
    "flow_l2_lpm",
    "flow_l3_lpm",
    "pressure_bar",
    "pressure_b_bar",
    "dropout",
    "ripple",
    "clipped",
    *RAW_FIELDS,
]

DB_COLUMNS = [c for c in READING_COLUMNS if c not in RAW_FIELDS]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db_session(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | Path | None = None) -> Path:
    with db_session(path) as conn:
        conn.executescript(SCHEMA)
        # Migration for databases created before run onset support existed.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "onset_ts" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN onset_ts TEXT")
        rcols = {row["name"] for row in conn.execute("PRAGMA table_info(readings)")}
        if "clipped" not in rcols:
            conn.execute("ALTER TABLE readings ADD COLUMN clipped INTEGER")
        if "pressure_b_bar" not in rcols:
            conn.execute("ALTER TABLE readings ADD COLUMN pressure_b_bar REAL")
    return Path(path or DB_PATH)


def insert_reading(conn: sqlite3.Connection, msg: dict[str, Any]) -> bool:
    values = msg["values"]
    raw = json.dumps(msg.get("raw", {}), separators=(",", ":"))
    quality = msg.get("quality", {})
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO readings
        (device, seq, ts, scenario, label, flow_main_lpm, flow_l1_lpm, flow_l2_lpm,
         flow_l3_lpm, pressure_bar, pressure_b_bar, raw_json, dropout, ripple,
         clipped, received_ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            msg["device"],
            msg["seq"],
            msg["ts"],
            msg.get("scenario", ""),
            msg["label"],
            values["flow_main_lpm"],
            values["flow_l1_lpm"],
            values["flow_l2_lpm"],
            values["flow_l3_lpm"],
            values["pressure_bar"],
            values.get("pressure_b_bar"),
            raw,
            int(bool(quality.get("dropout", False))),
            int(bool(quality.get("ripple", False))),
            int(bool(quality.get("clipped", False))),
            utc_now(),
        ),
    )
    return cur.rowcount > 0


def insert_alert(conn: sqlite3.Connection, alert: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT INTO alerts (ts, device, branch, leak_lpm_est, confidence, method, message, created_ts)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            alert.get("ts", utc_now()),
            alert.get("device"),
            alert.get("branch"),
            float(alert.get("leak_lpm_est", 0.0)),
            float(alert.get("confidence", 0.0)),
            alert.get("method", "M0-share-cusum"),
            alert.get("message", ""),
            utc_now(),
        ),
    )
    return int(cur.lastrowid)


def query_readings(
    conn: sqlite3.Connection,
    limit: int = 500,
    since: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if since:
        where.append("ts > ?")
        params.append(since)
    if device:
        where.append("device = ?")
        params.append(device)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT * FROM (SELECT * FROM readings{clause} ORDER BY ts DESC LIMIT ?) "
        "ORDER BY ts ASC"
    )
    params.append(max(1, int(limit)))
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_alerts(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
    return [dict(r) for r in rows]


def create_run(conn: sqlite3.Connection, label: str, notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_ts, label, notes) VALUES (?,?,?)",
        (utc_now(), label, notes),
    )
    return int(cur.lastrowid)


def stop_run(conn: sqlite3.Connection, run_id: int) -> bool:
    cur = conn.execute(
        "UPDATE runs SET stopped_ts = ? WHERE id = ? AND stopped_ts IS NULL",
        (utc_now(), int(run_id)),
    )
    return cur.rowcount > 0


def set_run_onset(conn: sqlite3.Connection, run_id: int, onset_ts: str) -> bool:
    cur = conn.execute(
        "UPDATE runs SET onset_ts = ? WHERE id = ?",
        (onset_ts, int(run_id)),
    )
    return cur.rowcount > 0


def active_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM runs WHERE stopped_ts IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
    return [dict(r) for r in rows]


def readings_csv(conn: sqlite3.Connection, limit: int = 100000) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(READING_COLUMNS)
    cols = ", ".join([*DB_COLUMNS, "raw_json"])
    for row in conn.execute(f"SELECT {cols} FROM readings ORDER BY ts ASC LIMIT ?", (int(limit),)):
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except ValueError:
            raw = {}
        writer.writerow(
            [row[c] for c in DB_COLUMNS] + [raw.get(RAW_FIELDS[c]) for c in RAW_FIELDS]
        )
    return buf.getvalue()
