"""Record live telemetry to CSV while labelling it from the keyboard.

    python -m tools.live_label                       # -> data/real/run_<utc>.csv
    python -m tools.live_label --out data/real/run01.csv --host 10.48.156.245

Keys (take effect on the next sample, ~0.5 s):
    0  pressure_label = high        3  flow_label = low
    1  pressure_label = low         4  flow_label = normal
    2  pressure_label = normal      q  quit (Ctrl-C works too)

Pressure and flow are independent axes: each key changes only its own column,
and the value sticks until another key for that axis is pressed. Every row is
the normal telemetry CSV row (same columns as messages.to_row, so the existing
`label` leak column is untouched) plus `pressure_label` and `flow_label`.
Rows are flushed as they arrive, so a crash never loses recorded data.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from hydropin import config
from hydropin.messages import CSV_COLUMNS, MessageError, parse_message, to_row

PRESSURE_LABELS = ("high", "low", "normal")
FLOW_LABELS = ("low", "normal")
KEYMAP = {
    "0": ("pressure_label", "high"),
    "1": ("pressure_label", "low"),
    "2": ("pressure_label", "normal"),
    "3": ("flow_label", "low"),
    "4": ("flow_label", "normal"),
}
COLUMNS = [*CSV_COLUMNS, "pressure_label", "flow_label"]


class Recorder:
    def __init__(self, out_path: Path, pressure: str, flow: str):
        self.lock = threading.Lock()
        self.labels = {"pressure_label": pressure, "flow_label": flow}
        self.rows = 0
        self.errors = 0
        self.last: dict[str, Any] | None = None
        self.connected = False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not out_path.exists() or out_path.stat().st_size == 0
        self._fh = out_path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            self._writer.writeheader()
            self._fh.flush()

    def set_label(self, column: str, value: str) -> None:
        with self.lock:
            self.labels[column] = value

    def on_message(self, payload: bytes) -> None:
        try:
            msg = parse_message(payload)
        except MessageError:
            with self.lock:
                self.errors += 1
            return
        row = to_row(msg)
        with self.lock:
            row.update(self.labels)
            self._writer.writerow(row)
            self._fh.flush()
            self.rows += 1
            self.last = row

    def close(self) -> None:
        with self.lock:
            self._fh.close()


# ---- single-key input without Enter (Linux/macOS termios, Windows msvcrt) ----
class KeyReader:
    def __enter__(self) -> "KeyReader":
        if os.name == "nt":
            return self
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc: object) -> None:
        if os.name != "nt":
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def read(self, timeout: float) -> str | None:
        if os.name == "nt":
            import msvcrt

            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.02)
            return None
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None


def _status(rec: Recorder) -> str:
    with rec.lock:
        last, labels, rows, errors, conn = rec.last, dict(rec.labels), rec.rows, rec.errors, rec.connected
    if last:
        vals = (
            f"P1 {last['pressure_bar']:5.2f} bar  P2 {last['pressure_b_bar'] or 0:5.2f} bar  "
            f"flow {last['flow_main_lpm']:5.2f} L/min"
        )
    else:
        vals = "waiting for telemetry..."
    mqtt_state = "mqtt ok" if conn else "mqtt DOWN"
    return (
        f"\r\x1b[K{vals}  rows {rows}  bad {errors}  {mqtt_state}  |  "
        f"pressure: {labels['pressure_label'].upper():6}  flow: {labels['flow_label'].upper():6}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record + keyboard-label live telemetry")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--out", default=f"data/real/run_{stamp}.csv")
    parser.add_argument("--host", default=config.MQTT_HOST)
    parser.add_argument("--port", type=int, default=config.MQTT_PORT)
    parser.add_argument("--device", default="+", help="device id, default: all devices")
    parser.add_argument("--pressure", default="normal", choices=PRESSURE_LABELS, help="starting label")
    parser.add_argument("--flow", default="normal", choices=FLOW_LABELS, help="starting label")
    args = parser.parse_args(argv)

    if not sys.stdin.isatty():
        print("error: needs an interactive terminal for key presses")
        return 1

    out_path = Path(args.out)
    rec = Recorder(out_path, args.pressure, args.flow)
    topic = f"{config.MQTT_BASE_TOPIC}/{args.device}/telemetry"

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"hydropin-labeller-{os.getpid()}",
    )

    def on_connect(c: Any, _u: Any, _f: Any, reason: Any, _p: Any = None) -> None:
        ok = not getattr(reason, "is_failure", False)
        with rec.lock:
            rec.connected = ok
        if ok:
            c.subscribe(topic, qos=0)

    def on_disconnect(*_a: Any) -> None:
        with rec.lock:
            rec.connected = False

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = lambda _c, _u, m: rec.on_message(m.payload)
    client.connect_async(args.host, args.port, keepalive=30)
    client.loop_start()

    print(f"recording {topic} @ {args.host}:{args.port} -> {out_path}")
    print("[0] high P  [1] low P  [2] normal P  [3] low flow  [4] normal flow  [q] quit")
    try:
        with KeyReader() as keys:
            while True:
                sys.stdout.write(_status(rec))
                sys.stdout.flush()
                key = keys.read(0.25)
                if key is None:
                    continue
                if key.lower() == "q":
                    break
                if key in KEYMAP:
                    column, value = KEYMAP[key]
                    rec.set_label(column, value)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        rec.close()

    print(f"\nwrote {rec.rows} rows to {out_path} ({rec.errors} invalid messages skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
