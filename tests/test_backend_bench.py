"""Backend with the rev 1 bench detector: frames, state, events, baseline reset, replay, /ws."""
from fastapi.testclient import TestClient

from backend.main import create_app
from detection.replay import score_replay
from simulator.bench_rev1 import build, simulate


def _app(tmp_path):
    return create_app(db_path=tmp_path / "bench.db", start_mqtt=False, static_dir=None)


def test_leak_run_end_to_end(tmp_path):
    msgs = simulate(build("leak_L1", duration_s=120))
    with TestClient(_app(tmp_path)) as client:
        run = client.post("/api/runs", json={"label": "leak_L1", "opening": "0.5 mm cap",
                                             "measured_leak_lpm": 0.31, "notes": "sim"}).json()
        onset = next(m["ts"] for m in msgs if m["ts_device_ms"] >= 80_000)
        for m in msgs:
            r = client.post("/api/ingest", json=m)
            assert r.status_code == 200
            if m["ts"] == onset:
                ev = client.post("/api/events", json={"type": "leak_on", "tap": "L1", "ts": onset}).json()
                assert ev["run_id"] == run["id"]
        assert r.json()["frame"]["state"] == "LEAK"
        frames = client.get("/api/frames", params={"run_id": run["id"]}).json()
        assert len(frames) == len(msgs)
        assert frames[-1]["branch"] == "A"
        replay = client.get(f"/api/runs/{run['id']}/replay").json()
        assert replay["simulation"] is False and replay["label"] == "leak_L1"
        assert replay["meta"]["measured_leak_lpm"] == 0.31
        score = score_replay(replay)
        assert score["detected"] and score["branch_ok"] and not score["false_alarm"]
        assert client.get("/api/runs").json()[0]["onset_ts"] == onset
        # the message timestamps are in the past, so the bench is OFFLINE "now"
        assert client.get("/api/state").json()["state"] == "OFFLINE"


def test_events_validation_and_listing(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/events", json={"type": "explode"}).status_code == 422
        assert client.post("/api/events", json={"type": "leak_on", "tap": "L9"}).status_code == 422
        assert client.post("/api/events", json={"type": "valve_change", "ts": "nope"}).status_code == 422
        assert client.post("/api/events", json={"type": "valve_change", "notes": "V1 to 30 deg"}).status_code == 200
        assert client.get("/api/events").json()[0]["type"] == "valve_change"


def test_baseline_reset_and_ws(tmp_path):
    msgs = simulate(build("baseline", duration_s=60))
    with TestClient(_app(tmp_path)) as client:
        for m in msgs:
            client.post("/api/ingest", json=m)
        assert client.post("/api/baseline/reset").json()["reset"] is True
        nxt = dict(msgs[-1], seq=msgs[-1]["seq"] + 1)
        assert client.post("/api/ingest", json=nxt).json()["frame"]["state"] == "SETTLING"
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "frames" and data["frames"]
            assert "state" in data["frames"][-1]


def test_blind_run_label_filled_after(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        run = client.post("/api/runs", json={"label": "none", "blind": True}).json()
        assert client.post(f"/api/runs/{run['id']}/meta", json={"label": "leak_L3"}).status_code == 200
        assert client.post(f"/api/runs/{run['id']}/meta", json={"label": "leak_X"}).status_code == 422
        got = client.get("/api/runs").json()[0]
        assert got["label"] == "leak_L3" and got["blind"] == 1


def test_static_dashboard_served(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text("<h1>hp</h1>")
    app = create_app(db_path=tmp_path / "s.db", static_dir=tmp_path / "site")
    with TestClient(app) as client:
        assert "hp" in client.get("/").text
        assert client.get("/health").json()["ok"] is True
