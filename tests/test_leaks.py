"""Leak episodes: opened by the detector, closed when the sensors are back to normal, and
"I fixed it" from the farmer app (docs/design/2026-11-27-farmer-app-design.md)."""
from fastapi.testclient import TestClient

from backend import storage
from backend.leaks import track_leak
from backend.main import create_app
from simulator.bench_rev1 import build, simulate

T0 = "2026-11-27T06:12:00.000Z"


def _frame(state, ts, branch="B", base=1.5, leak=0.3, lost=0.1):
    return {"ts": ts, "state": state, "branch": branch, "flow_base_lpm": base, "leak_lpm": leak, "lost_l": lost}


def _app(db):
    return create_app(db_path=db, start_mqtt=False, static_dir=None)


def test_episode_opens_on_leak_and_closes_on_healthy(tmp_path):
    msgs = simulate(build("leak_L1", leak_stop_s=130.0, duration_s=200))
    with TestClient(_app(tmp_path / "b.db")) as client:
        for m in msgs:
            assert client.post("/api/ingest", json=m).status_code == 200
        leaks = client.get("/api/leaks").json()
    assert len(leaks) == 1
    assert leaks[0]["branch"] == "A" and leaks[0]["status"] == "fixed" and leaks[0]["ended_ts"]
    assert leaks[0]["max_leak_lpm"] > 0 and leaks[0]["base_lpm"] > 0


def test_fixed_goes_checking_then_fixed(tmp_path):
    db = tmp_path / "s.db"
    storage.init_db(db)
    with storage.db_session(db) as conn:
        lid = storage.open_leak(conn, T0, "B", 1.5)
        assert storage.mark_leak_fixed(conn, lid, "2026-11-27T09:00:00.000Z")["status"] == "checking"
        storage.close_leak(conn, lid, "2026-11-27T09:00:05.000Z")
        assert storage.list_leaks(conn)[0]["status"] == "fixed"


def test_pump_stop_keeps_episode_open(tmp_path):
    db = tmp_path / "p.db"
    storage.init_db(db)
    with storage.db_session(db) as conn:
        for f in [_frame("LEAK", T0), _frame("PUMP_OFF", "2026-11-27T06:20:00.000Z"),
                  _frame("HEALTHY", "2026-11-27T07:00:00.000Z")]:
            track_leak(conn, f)
        row = storage.list_leaks(conn)[0]
        assert row["status"] == "open" and row["ended_ts"] is None and row["pump_stopped"] == 1
        assert storage.mark_leak_fixed(conn, row["id"], "2026-11-27T08:00:00.000Z")["status"] == "fixed"


def test_update_keeps_the_largest_leak_and_latest_volume(tmp_path):
    db = tmp_path / "u.db"
    storage.init_db(db)
    with storage.db_session(db) as conn:
        track_leak(conn, _frame("LEAK", T0, leak=0.4, lost=0.2))
        track_leak(conn, _frame("LEAK", "2026-11-27T06:12:01.000Z", leak=0.3, lost=0.5))
        row = storage.list_leaks(conn)[0]
    assert row["max_leak_lpm"] == 0.4 and row["lost_l"] == 0.5 and row["base_lpm"] == 1.5


def test_fixed_is_idempotent_and_unknown_is_404(tmp_path):
    db = tmp_path / "f.db"
    app = _app(db)
    with storage.db_session(db) as conn:
        lid = storage.open_leak(conn, T0, "B", 1.5)
    with TestClient(app) as client:
        first = client.post(f"/api/leaks/{lid}/fixed").json()
        second = client.post(f"/api/leaks/{lid}/fixed").json()
        assert first["status"] == "checking" and first["user_fixed_ts"]
        assert second["user_fixed_ts"] == first["user_fixed_ts"]
        missing = client.post("/api/leaks/999/fixed")
        assert missing.status_code == 404 and missing.json() == {"detail": "leak not found"}


def test_open_episode_survives_backend_restart(tmp_path):
    db = tmp_path / "r.db"
    storage.init_db(db)
    with storage.db_session(db) as conn:          # backend #1
        track_leak(conn, _frame("LEAK", T0))
    storage.init_db(db)                           # backend #2 starts on the same database
    with storage.db_session(db) as conn:
        track_leak(conn, _frame("LEAK", "2026-11-27T06:15:00.000Z"))
        assert len(storage.list_leaks(conn)) == 1


def test_final_fix2_relearn_during_a_leak_cannot_confirm_the_repair(tmp_path):
    """Baseline reset or a new detector process during a leak: HEALTHY afterwards proves nothing."""
    db = tmp_path / "relearn.db"
    storage.init_db(db)
    with storage.db_session(db) as conn:
        for state, ts in [("LEAK", T0), ("SETTLING", "2026-11-27T06:13:00.000Z"),
                          ("LEARNING", "2026-11-27T06:13:20.000Z"), ("HEALTHY", "2026-11-27T06:14:00.000Z")]:
            track_leak(conn, _frame(state, ts))
        row = storage.list_leaks(conn)[0]
    assert row["status"] == "open" and row["ended_ts"] is None and row["pump_stopped"] == 1


def test_final_fix2_baseline_reset_through_the_api(tmp_path):
    msgs = simulate(build("leak_L2", duration_s=220))          # the tap stays open to the end
    with TestClient(_app(tmp_path / "reset.db")) as client:
        reset_done = False
        for m in msgs:
            r = client.post("/api/ingest", json=m).json()
            if not reset_done and r["frame"] and r["frame"]["state"] == "LEAK":
                client.post("/api/baseline/reset")
                reset_done = True
        leaks = client.get("/api/leaks").json()
    assert reset_done and leaks and leaks[0]["status"] == "open"
