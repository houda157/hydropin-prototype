"""ADS1115 single-ended reads can be a few counts below 0 near 0 V (pump off, unplugged sensor).

The contract keeps raw counts >= 0, so the backend clamps small negatives to 0 instead of
rejecting the whole frame (which showed OFFLINE instead of "PT2 unplugged, not a leak").
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from hydropin.messages import MessageError, normalize_message, parse_message
from simulator.bench_rev1 import build, simulate


def _app(tmp_path):
    return create_app(db_path=tmp_path / "bench.db", baseline_path=None, start_mqtt=False, static_dir=None)


def test_slightly_negative_counts_are_clamped_not_rejected(tmp_path):
    msgs = simulate(build("unplug_PT2", duration_s=130))
    for m in msgs:
        if m["ts_device_ms"] >= 100_000:          # PT2 unplugged: 0 V through the 10k shunt
            m["raw"]["pressure_b_adc"] = -2
    with TestClient(_app(tmp_path)) as client:
        for m in msgs:
            r = client.post("/api/ingest", json=m)
            assert r.status_code == 200, r.text
        frame = r.json()["frame"]
    assert "PT2_unplugged" in frame["faults"]
    assert frame["state"] != "LEAK"


def test_mqtt_path_clamps_too():
    m = simulate(build("baseline", duration_s=1))[0]
    m["raw"]["pressure_adc"] = -3
    assert parse_message(json.dumps(m))["raw"]["pressure_adc"] == 0


def test_large_negative_counts_are_still_an_error():
    m = simulate(build("baseline", duration_s=1))[0]
    m["raw"]["pressure_adc"] = -5000
    with pytest.raises(MessageError):
        parse_message(json.dumps(m))


def test_normalize_leaves_good_messages_alone():
    m = simulate(build("baseline", duration_s=1))[0]
    assert normalize_message(m) == m
