import csv
import io

from fastapi.testclient import TestClient

from backend.main import create_app
from hydropin.messages import make_message
from simulator.bench_rev1 import build, simulate


def sample(seq=1, label="none"):
    return make_message(
        device="esp32-test",
        seq=seq,
        flows_lpm={"main": 1.7, "l1": 0.55, "l2": 0.45, "l3": 0.65},
        pressure_bar=2.0,
        label=label,
    )


def test_rest_ingest_query_export_and_runs(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", start_mqtt=False)
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["ok"] is True
        assert health["bench_detector"] is True

        msg = sample()
        first = client.post("/api/ingest", json=msg)
        assert first.status_code == 200
        assert first.json()["inserted"] is True

        duplicate = client.post("/api/ingest", json=msg)
        assert duplicate.json()["inserted"] is False

        rows = client.get("/api/readings").json()
        assert len(rows) == 1
        assert rows[0]["flow_main_lpm"] == 1.7

        bad = sample(seq=2)
        bad["label"] = "leak_L9"
        assert client.post("/api/ingest", json=bad).status_code == 422

        exported = client.get("/api/export.csv")
        assert exported.status_code == 200
        assert "flow_main_lpm" in exported.text
        assert "1.7" in exported.text
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        assert rows[0]["clipped"] == "0"
        assert rows[0]["raw_pressure_adc"] == "8889"
        assert rows[0]["raw_flow_main_pulses"] == "17"

        run = client.post("/api/runs", json={"label": "leak_L2", "notes": "unit"}).json()
        assert run["id"] > 0
        assert client.get("/api/runs").json()[0]["label"] == "leak_L2"
        assert client.post(f"/api/runs/{run['id']}/stop").json()["stopped"] is True
        assert client.post(f"/api/runs/{run['id']}/stop").status_code == 404

        with client.websocket_connect("/ws/live") as ws:
            payload = ws.receive_json()
            assert "type" in payload


def test_live_labels_follow_marked_onset(tmp_path):
    app = create_app(db_path=tmp_path / "labels.db", start_mqtt=False)
    with TestClient(app) as client:
        run = client.post("/api/runs", json={"label": "leak_L1", "notes": "onset test"}).json()
        before = make_message(
            device="esp32-test",
            seq=1,
            flows_lpm={"main": 1.7, "l1": 0.55, "l2": 0.45, "l3": 0.65},
            pressure_bar=2.0,
            scenario="live",
            ts="2026-11-24T12:00:00.000Z",
        )
        assert client.post("/api/ingest", json=before).status_code == 200
        assert client.post(f"/api/runs/{run['id']}/onset", json={"ts": "nope"}).status_code == 422
        marked = client.post(
            f"/api/runs/{run['id']}/onset", json={"ts": "2026-11-24T12:00:01.000Z"}
        )
        assert marked.status_code == 200
        assert marked.json()["onset_ts"] == "2026-11-24T12:00:01.000Z"
        after = make_message(
            device="esp32-test",
            seq=2,
            flows_lpm={"main": 1.7, "l1": 0.55, "l2": 0.45, "l3": 0.65},
            pressure_bar=2.0,
            scenario="live",
            ts="2026-11-24T12:00:02.000Z",
        )
        assert client.post("/api/ingest", json=after).status_code == 200
        rows = client.get("/api/readings").json()
        assert [r["label"] for r in rows] == ["none", "leak_L1"]
        assert client.get("/api/runs").json()[0]["onset_ts"] == "2026-11-24T12:00:01.000Z"


def test_bench_leak_is_recorded_as_an_alert(tmp_path):
    """The bench detector's LEAK rising edge is stored in the alerts table (and sent to Telegram)."""
    msgs = simulate(build("leak_L1", leak_size="large", seed=7, duration_s=150.0))
    app = create_app(db_path=tmp_path / "live.db", start_mqtt=False)
    with TestClient(app) as client:
        for msg in msgs:
            assert client.post("/api/ingest", json=msg).status_code == 200
        alerts = client.get("/api/alerts").json()
        assert len(alerts) == 1, "one alert per LEAK episode"
        assert alerts[0]["branch"] == "A"
        assert alerts[0]["leak_lpm_est"] > 0.1
        assert alerts[0]["message"].startswith("HydroPin LEAK")
