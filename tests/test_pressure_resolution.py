"""Pressure from the raw ADC counts, not the firmware's 0.01 bar rounding; fault alerts debounced.

With quiet sensors (2-3 mbar after oversampling) the firmware's rounded values repeat for
seconds, which the detector used to call "PTx_stuck" (M2 excluded, branch lost, Telegram spam).
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import simulator.bench_rev1 as sim
from backend.bench_live import BenchLive
from backend.main import create_app
from detection.bench_detector import run_messages
from detection.campaign import load_runs


def _firmware_rounding(msgs):
    """Values rounded like firmware rev 1 (0.01), raw ADC counts untouched."""
    out = []
    for m in msgs:
        v = dict(m["values"])
        for k in ("flow_main_lpm", "pressure_bar", "pressure_b_bar"):
            v[k] = round(v[k], 2)
        out.append({**m, "values": v})
    return out


def _quiet_run(monkeypatch, scenario="leak_L1"):
    monkeypatch.setattr(sim, "NOISE_P_BAR", 0.002)
    monkeypatch.setattr(sim, "WANDER_P_BAR", 0.002)
    return _firmware_rounding(sim.simulate(sim.build(scenario, duration_s=150)))


def test_quiet_sensors_are_not_called_stuck(monkeypatch):
    frames = run_messages(_quiet_run(monkeypatch))
    stuck = [f for f in frames if any(x.endswith("_stuck") for x in f["faults"])]
    assert stuck == []
    assert frames[-1]["state"] == "LEAK" and frames[-1]["branch"] == "A"


def test_detector_reads_pressure_from_raw_counts(monkeypatch):
    msgs = _quiet_run(monkeypatch, "baseline")
    frame = run_messages(msgs[:1])[0]
    assert frame["pt1_bar"] != msgs[0]["values"]["pressure_bar"]      # not the rounded value
    assert abs(frame["pt1_bar"] - msgs[0]["values"]["pressure_bar"]) <= 0.005


def test_a_flickering_fault_is_notified_once():
    live = BenchLive(send_notifications=False)
    base = {"state": "HEALTHY", "p_leak": 0.0, "leak_lpm": 0.0, "lost_l": 0.0, "branch": None}
    notices = []
    for i in range(40):                      # 20 s of a fault that comes and goes every sample
        faults = ["PT2_unplugged"] if i % 2 == 0 else []
        notices += live._notices({**base, "faults": faults, "ts": f"2026-11-27T09:00:{i // 2:02d}.000Z"})
    assert len([n for n in notices if "PT2_unplugged" in n]) == 1


def test_replays_rebuilt_from_the_database_keep_raw_counts(tmp_path):
    db = tmp_path / "bench.db"
    app = create_app(db_path=db, start_mqtt=False, static_dir=None)
    with TestClient(app) as client:
        client.post("/api/runs", json={"label": "none"})
        msgs = sim.simulate(sim.build("baseline", duration_s=20), start=datetime.now(timezone.utc))
        for m in msgs:
            client.post("/api/ingest", json=m)
        rid = client.get("/api/runs").json()[0]["id"]
        client.post(f"/api/runs/{rid}/stop")
    run = load_runs(db, min_readings=1)
    assert run and run[0]["msgs"][0]["raw"]["pressure_adc"] == msgs[0]["raw"]["pressure_adc"]
