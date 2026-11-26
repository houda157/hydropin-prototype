"""Build, parse and validate telemetry messages against the contract.

The same JSON object travels over MQTT and is stored in SQLite / CSV. Keeping
one parser avoids the classic bug where the firmware and the backend disagree
about field names or units.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contract" / "message.schema.json"


class MessageError(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_message(
    *,
    device: str,
    seq: int,
    flows_lpm: dict[str, float],
    pressure_bar: float,
    pressure_b_bar: float | None = None,
    ts: str | None = None,
    ts_device_ms: int | None = None,
    label: str = "none",
    scenario: str = "baseline",
    dropout: bool = False,
    ripple: bool = False,
    clipped: bool = False,
    dt_s: float = config.FLOW_MEASURE_WINDOW_S,
    raw: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a message from *calibrated* physical values.

    Raw pulse / ADC fields are reconstructed so the message is auditable, unless
    an explicit ``raw`` block is supplied (the simulator does this so real pulse
    quantization is preserved). ``dt_s`` is the *flow measurement window*, not the
    publish period: the contract's pulse fields are counts over the 2 s window.
    """
    missing = [c for c in config.FLOW_CHANNELS if c not in flows_lpm]
    if missing:
        raise MessageError(f"missing flow channels: {missing}")
    if label not in config.LABELS:
        raise MessageError(f"label must be one of {config.LABELS}")

    values: dict[str, float] = {f"flow_{c}_lpm": round(float(flows_lpm[c]), 4) for c in config.FLOW_CHANNELS}
    values["pressure_bar"] = round(float(pressure_bar), 4)
    if pressure_b_bar is not None:
        values["pressure_b_bar"] = round(float(pressure_b_bar), 4)
    if raw is None:
        raw = {
            f"flow_{c}_pulses": config.flow_lpm_to_pulses(float(flows_lpm[c]), dt_s) for c in config.FLOW_CHANNELS
        }
        raw["pressure_adc"] = config.pressure_bar_to_adc(float(pressure_bar))
        if pressure_b_bar is not None:
            raw["pressure_b_adc"] = config.pressure_b_bar_to_adc(float(pressure_b_bar))

    return {
        "schema": config.SCHEMA_VERSION,
        "device": device,
        "seq": int(seq),
        "ts": ts or utc_now_iso(),
        "ts_device_ms": ts_device_ms,
        "label": label,
        "scenario": scenario,
        "raw": raw,
        "values": values,
        "quality": {"dropout": bool(dropout), "ripple": bool(ripple), "clipped": bool(clipped)},
    }


def _schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_message(msg: Any) -> dict[str, Any]:
    """Validate with jsonschema, then add physical-range checks."""
    if not isinstance(msg, dict):
        raise MessageError("message must be a JSON object")
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - optional dependency
        jsonschema = None

    if jsonschema is not None:
        try:
            jsonschema.validate(msg, _schema())
        except jsonschema.ValidationError as exc:
            raise MessageError(f"schema violation: {exc.message}") from exc

    values = msg["values"]
    for ch in config.FLOW_CHANNELS:
        lo, hi = config.FLOW_RANGE_LPM
        v = values[f"flow_{ch}_lpm"]
        if not (lo <= v <= hi):
            raise MessageError(f"flow_{ch}_lpm out of physical range: {v}")
    p = values["pressure_bar"]
    lo, hi = config.PRESSURE_RANGE_BAR
    if not (lo <= p <= hi):
        raise MessageError(f"pressure_bar out of physical range: {p}")
    if "pressure_b_bar" in values:
        pb = values["pressure_b_bar"]
        lo, hi = config.PRESSURE_B_RANGE_BAR
        if not (lo <= pb <= hi):
            raise MessageError(f"pressure_b_bar out of physical range: {pb}")
    return msg


def parse_message(payload: str | bytes) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        msg = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MessageError(f"invalid JSON: {exc}") from exc
    return validate_message(msg)


def to_row(msg: dict[str, Any]) -> dict[str, Any]:
    """Flatten a message for CSV / DataFrame storage."""
    values = msg["values"]
    raw = msg.get("raw", {})
    quality = msg.get("quality", {})
    row: dict[str, Any] = {
        "ts": msg["ts"],
        "device": msg["device"],
        "seq": msg["seq"],
        "scenario": msg.get("scenario", ""),
        "label": msg["label"],
    }
    for ch in config.FLOW_CHANNELS:
        row[f"flow_{ch}_lpm"] = values[f"flow_{ch}_lpm"]
    row["pressure_bar"] = values["pressure_bar"]
    row["pressure_b_bar"] = values.get("pressure_b_bar")
    for ch in config.FLOW_CHANNELS:
        row[f"raw_flow_{ch}_pulses"] = raw.get(f"flow_{ch}_pulses")
    row["raw_pressure_adc"] = raw.get("pressure_adc")
    row["raw_pressure_b_adc"] = raw.get("pressure_b_adc")
    row["dropout"] = bool(quality.get("dropout", False))
    row["ripple"] = bool(quality.get("ripple", False))
    row["clipped"] = bool(quality.get("clipped", False))
    return row


CSV_COLUMNS = [
    "ts",
    "device",
    "seq",
    "scenario",
    "label",
    *[f"flow_{c}_lpm" for c in config.FLOW_CHANNELS],
    "pressure_bar",
    "pressure_b_bar",
    *[f"raw_flow_{c}_pulses" for c in config.FLOW_CHANNELS],
    "raw_pressure_adc",
    "raw_pressure_b_adc",
    "dropout",
    "ripple",
    "clipped",
]
