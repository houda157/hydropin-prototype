"""ESP32 reboots (seq restarts at 0) and an unset device clock (no NTP: ts = 1970).

Both happen on bench day: a USB replug or reflash resets the board, and the USB serial
fallback has no internet for NTP. Neither may freeze the dashboard.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import storage
from backend.main import create_app
from hydropin import config
from simulator.bench_rev1 import build, simulate

UNSET = "1970-01-01T00:00:00.000Z"


def _app(tmp_path):
    return create_app(db_path=tmp_path / "bench.db", baseline_path=None, start_mqtt=False, static_dir=None)


def _as_esp32(msgs):
    """Simulated messages dressed as the real board's (device id and scenario)."""
    return [{**m, "device": config.DEFAULT_DEVICE, "scenario": "live", "label": "none"} for m in msgs]


def test_frames_keep_flowing_after_a_reboot(tmp_path):
    t0 = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    first = _as_esp32(simulate(build("baseline", duration_s=30), start=t0))
    # the board resets 5 minutes later: seq and millis() start again from 0
    second = _as_esp32(simulate(build("baseline", duration_s=30, seed=3), start=t0 + timedelta(minutes=5)))
    with TestClient(_app(tmp_path)) as client:
        for m in first + second:
            r = client.post("/api/ingest", json=m)
            assert r.status_code == 200
            assert r.json()["inserted"] is True, m["seq"]
        frames = client.get("/api/frames", params={"limit": 1000}).json()
        assert len(frames) == len(first) + len(second)


def test_redelivery_is_still_ignored_after_a_reboot(tmp_path):
    t0 = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    first = _as_esp32(simulate(build("baseline", duration_s=5), start=t0))
    second = _as_esp32(simulate(build("baseline", duration_s=5), start=t0 + timedelta(minutes=5)))
    with TestClient(_app(tmp_path)) as client:
        for m in first + second:
            client.post("/api/ingest", json=m)
        # MQTT QoS 1 may deliver the same message twice: same seq, same device time
        assert client.post("/api/ingest", json=second[3]).json()["inserted"] is False
        assert client.post("/api/ingest", json=first[3]).json()["inserted"] is False
        assert len(client.get("/api/readings", params={"limit": 1000}).json()) == len(first) + len(second)


def test_second_simulator_run_is_not_dropped(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        now = datetime.now(timezone.utc)
        for start in (now - timedelta(minutes=10), now - timedelta(minutes=5)):
            for m in simulate(build("baseline", duration_s=10), start=start):
                assert client.post("/api/ingest", json=m).json()["inserted"] is True


def test_simulator_has_its_own_device_id():
    msgs = simulate(build("baseline", duration_s=2))
    assert msgs[0]["device"] == config.SIM_DEVICE != config.DEFAULT_DEVICE


def test_unset_device_clock_gets_laptop_time_and_detection_still_works(tmp_path):
    msgs = _as_esp32(simulate(build("leak_L1", duration_s=150)))
    for m in msgs:
        m["ts"] = UNSET                      # firmware before NTP sync (USB fallback, no internet)
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    with TestClient(_app(tmp_path)) as client:
        for m in msgs:
            r = client.post("/api/ingest", json=m)
            assert r.status_code == 200 and r.json()["inserted"] is True
        last = r.json()["frame"]
        assert last["state"] == "LEAK" and last["branch"] == "A"
        rows = client.get("/api/readings", params={"limit": 1000}).json()
    stamps = [datetime.fromisoformat(row["ts"].replace("Z", "+00:00")) for row in rows]
    assert stamps[0] >= before                             # laptop time, not 1970
    gaps = {round((b - a).total_seconds(), 3) for a, b in zip(stamps, stamps[1:])}
    assert gaps == {config.SAMPLE_PERIOD_S}                # spacing from the board's millis()
    assert all(row["device_ts"] == UNSET for row in rows)  # the board's own value is kept


def test_old_database_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE readings (
            device TEXT NOT NULL, seq INTEGER NOT NULL, ts TEXT NOT NULL, scenario TEXT, label TEXT,
            flow_main_lpm REAL, flow_l1_lpm REAL, flow_l2_lpm REAL, flow_l3_lpm REAL,
            pressure_bar REAL, pressure_b_bar REAL, raw_json TEXT,
            dropout INTEGER, ripple INTEGER, clipped INTEGER, received_ts TEXT NOT NULL,
            PRIMARY KEY (device, seq));
        INSERT INTO readings VALUES ('esp32-bench-01', 0, '2026-11-26T09:00:00.000Z', 'live', 'none',
            1.5, 0, 0, 0, 1.0, 1.0, '{}', 0, 0, 0, '2026-11-26T09:00:00.100Z');
    """)
    conn.commit()
    conn.close()
    storage.init_db(db)
    with storage.db_session(db) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM readings")]
    assert len(rows) == 1 and rows[0]["boot"] == 0 and rows[0]["device_ts"] == "2026-11-26T09:00:00.000Z"
