"""The MQTT callback must never let an exception escape (paho 2.x would stop the loop thread)."""
import json
from types import SimpleNamespace

from backend import main as backend_main
from backend.main import MQTTListener, create_app
from simulator.bench_rev1 import build, simulate


def test_unexpected_error_is_counted_not_raised(tmp_path, monkeypatch):
    app = create_app(db_path=tmp_path / "b.db", start_mqtt=False, static_dir=None)
    listener = MQTTListener(app, "localhost", 1883)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(backend_main, "ingest_message", boom)
    msg = simulate(build("baseline", duration_s=1))[0]
    listener._on_message(None, None, SimpleNamespace(topic="hydropin/bench/x/telemetry",
                                                     payload=json.dumps(msg).encode()))
    listener._on_message(None, None, SimpleNamespace(topic="t", payload=b"not json"))
    assert listener.errors == 2 and listener.received == 0
