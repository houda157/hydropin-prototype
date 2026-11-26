import csv
import io

from fastapi.testclient import TestClient

from backend.main import create_app
from detection.baseline import Baseline
from hydropin.messages import make_message
from simulator.scenarios import build_scenario
from simulator.sim import simulate


def sample(seq=1, label="none"):
    return make_message(
        device="esp32-test",
        seq=seq,
        flows_lpm={"main": 1.7, "l1": 0.55, "l2": 0.45, "l3": 0.65},
        pressure_bar=2.0,
        label=label,
    )


def test_rest_ingest_query_export_and_runs(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", baseline_path=None, start_mqtt=False)
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["ok"] is True
        assert health["detector"] is False

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
    app = create_app(db_path=tmp_path / "labels.db", baseline_path=None, start_mqtt=False)
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


def test_live_detector_raises_alert_on_simulated_leak(tmp_path):
    baseline_df, _ = simulate(build_scenario("baseline", duration_s=120, seed=7))
    baseline_path = tmp_path / "baseline.json"
    Baseline.fit_raw(baseline_df).save(baseline_path)

    _, leak_msgs = simulate(build_scenario("leak_L1", duration_s=120, seed=7))
    app = create_app(db_path=tmp_path / "live.db", baseline_path=baseline_path, start_mqtt=False)
    with TestClient(app) as client:
        for msg in leak_msgs[:140]:
            assert client.post("/api/ingest", json=msg).status_code == 200
        alerts = client.get("/api/alerts").json()
        assert alerts, "expected a live alert"
        assert alerts[0]["branch"] == "l1"
        assert alerts[0]["leak_lpm_est"] > 0.1
