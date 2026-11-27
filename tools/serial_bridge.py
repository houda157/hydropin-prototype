"""USB serial fallback: read the ESP32's JSON lines and forward them to the laptop backend.

    python -m tools.serial_bridge --port COM5                       # publish to the local MQTT broker
    python -m tools.serial_bridge --port COM5 --post http://localhost:8000   # or POST /api/ingest (no broker)
    python -m tools.serial_bridge --port COM5 --dry-run             # only print what would be sent

Use it when the bench WiFi misbehaves. Every line that starts with "{" is parsed and validated
against the frozen contract (hydropin/messages.py); log lines such as "[mqtt] connecting" and
invalid frames are skipped and counted. The firmware must print each frame as one JSON line on
Serial at 115200 baud (role 1: `Serial.println(payload);` after `serializeJson`).
Needs pyserial (`pip install pyserial`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from typing import Callable, Iterable

from hydropin import config
from hydropin.messages import MessageError, parse_message


def bridge_lines(lines: Iterable[str | bytes], send: Callable[[dict], None], log=print) -> dict:
    """Validate and forward every JSON frame in `lines`. Returns counts."""
    n = {"sent": 0, "skipped": 0, "invalid": 0, "send_failed": 0}
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("{"):
            n["skipped"] += 1
            continue
        try:
            msg = parse_message(line)
        except MessageError as exc:
            n["invalid"] += 1
            log(f"invalid frame: {exc}")
            continue
        try:
            send(msg)
            n["sent"] += 1
        except Exception as exc:  # never stop the bridge on one failed send
            n["send_failed"] += 1
            log(f"send failed: {exc}")
    return n


def mqtt_sender(host: str, port: int) -> Callable[[dict], None]:
    import paho.mqtt.client as mqtt
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hydropin-serial-bridge")
    client.connect(host, port, keepalive=30)
    client.loop_start()

    def send(msg: dict) -> None:
        client.publish(config.telemetry_topic(msg["device"]), json.dumps(msg), qos=0)
    return send


def http_sender(base: str) -> Callable[[dict], None]:
    url = config.fast_local_url(base.rstrip("/")) + "/api/ingest"

    def send(msg: dict) -> None:
        req = urllib.request.Request(url, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    return send


def serial_lines(port: str, baud: int):
    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial is missing: pip install pyserial")
    while True:
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                print(f"reading {port} at {baud} baud (Ctrl+C to stop)")
                while True:
                    line = ser.readline()
                    if line:
                        yield line
        except serial.SerialException as exc:      # unplugged / ESP32 reset: retry
            print(f"serial error: {exc}; retrying in 2 s")
            time.sleep(2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--post", help="backend base URL: POST /api/ingest instead of MQTT")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        send = lambda m: print(json.dumps(m)[:160])  # noqa: E731
    elif a.post:
        send = http_sender(a.post)
    else:
        send = mqtt_sender(a.broker, a.mqtt_port)
    try:
        counts = bridge_lines(serial_lines(a.port, a.baud), send)
    except KeyboardInterrupt:
        return 0
    print(counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
