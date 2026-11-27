"""FastAPI app factory + optional MQTT listener.

    uvicorn backend.main:app --reload
    $env:HYDROPIN_MQTT="1"; uvicorn backend.main:app

Settings come from the shell or from .env at the repo root (copy .env.example).

The MQTT listener is optional: without a broker the REST API still works and
`POST /api/ingest` can be used for bench tests.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from detection.baseline import Baseline
from hydropin import config
from hydropin.messages import MessageError, parse_message

from . import storage
from .api import router
from .bench_live import BenchLive
from .ingest import ingest_message
from .live_detect import LiveDetector

log = logging.getLogger("hydropin.mqtt")

# Windows can map .js to text/plain in its registry, which browsers refuse for ES modules;
# the farmer app (dashboard/app/) also needs its manifest type.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")

try:  # pragma: no cover - paho is installed in the project env
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None


class MQTTListener:
    def __init__(self, app: FastAPI, host: str, port: int):
        self.app = app
        self.host = host
        self.port = port
        self.received = 0
        self.errors = 0
        self.connected = False
        self._client: Any = None

    def start(self) -> None:
        if mqtt is None:
            return
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"hydropin-backend-{os.getpid()}",
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        try:
            client.connect_async(self.host, self.port, keepalive=30)
            client.loop_start()
        except Exception:
            self.connected = False

    def stop(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self.connected = False

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self.connected = getattr(reason_code, "value", reason_code) == 0
        if self.connected:
            client.subscribe(config.telemetry_topic("+"), qos=1)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self.connected = False

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            msg = parse_message(message.payload)
            ingest_message(
                msg,
                db_path=self.app.state.db_path,
                detector=self.app.state.detector,
                detector_lock=self.app.state.detector_lock,
                bench=self.app.state.bench,
            )
            self.received += 1
            self.app.state.mqtt_received = self.received
        except (MessageError, ValueError, KeyError) as exc:
            self.errors += 1
            log.warning("MQTT message rejected on %s: %s", getattr(message, "topic", "?"), exc)
        except Exception:  # noqa: BLE001 - an exception escaping a paho callback kills the loop thread
            self.errors += 1
            log.exception("MQTT message failed on %s", getattr(message, "topic", "?"))


def create_app(
    db_path: str | Path | None = None,
    baseline_path: str | Path | None = "models/baseline.json",
    start_mqtt: bool = False,
    mqtt_host: str | None = None,
    mqtt_port: int | None = None,
    notify: bool | None = None,
    bench: bool = True,
    static_dir: str | Path | None = Path(__file__).resolve().parents[1] / "dashboard",
) -> FastAPI:
    db = storage.init_db(db_path)
    app = FastAPI(title="hydropin prototype", version="0.2.0")
    app.state.db_path = str(db)
    app.state.detector_lock = threading.Lock()
    app.state.mqtt_received = 0
    app.state.notify = bool(notify) if notify is not None else bool(os.environ.get("HYDROPIN_NOTIFY") == "1")

    baseline = None
    if baseline_path and Path(baseline_path).exists():
        baseline = Baseline.load(baseline_path)
    app.state.detector = LiveDetector(baseline) if baseline is not None else None
    app.state.baseline = baseline
    # rev 1 bench detector: processed frames, /api/state, /ws (Telegram via the same notify switch)
    app.state.bench = BenchLive(send_notifications=app.state.notify) if bench else None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    # static dashboard at / (mounted last so the API routes win), with the two simulation viewers
    # at the same paths the GitHub Pages site uses
    root = Path(__file__).resolve().parents[1]
    if static_dir and Path(static_dir).is_dir() and (Path(static_dir) / "index.html").exists():
        for url, folder in (("/farm-explorer", root / "farm" / "explorer"), ("/twin", root / "simulator" / "demo")):
            if folder.is_dir():
                app.mount(url, StaticFiles(directory=str(folder), html=True), name=url.strip("/"))
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="dashboard")

    listener = (
        MQTTListener(app, mqtt_host or os.environ.get("HYDROPIN_MQTT_HOST") or config.MQTT_HOST,
                     int(mqtt_port or os.environ.get("HYDROPIN_MQTT_PORT") or config.MQTT_PORT))
        if start_mqtt
        else None
    )
    app.state.mqtt_listener = listener

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if listener is not None:
            listener.start()
        yield
        if listener is not None:
            listener.stop()

    app.router.lifespan_context = lifespan
    return app


app = create_app(start_mqtt=os.environ.get("HYDROPIN_MQTT", "0") == "1")
