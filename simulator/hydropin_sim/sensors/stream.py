"""Fake MQTT stream in the exact format of the real ESP32 nodes (contracts.SensorMessage)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Iterable

import numpy as np

from hydropin_sim.contracts import SensorMessage, SensorSeries
from hydropin_sim.sensors.model import M_PER_BAR

TOPIC = "hydropin/{farm}/{node}"


def to_messages(series: SensorSeries, farm: str, start: dt.datetime, temp_c: Iterable[float],
                battery_v: float = 3.9, seq0: int = 0) -> list[SensorMessage]:
    """One message per reading; lost packets (NaN) are simply not sent."""
    msgs = []
    for k, (t, v, tc) in enumerate(zip(series.time, series.value, temp_c)):
        if np.isnan(v):
            continue
        ts = (start + dt.timedelta(seconds=float(t))).astimezone(dt.timezone.utc)
        msgs.append(SensorMessage(farm=farm, node=series.node_id, seq=seq0 + k,
                                  ts=ts.isoformat().replace("+00:00", "Z"),
                                  p_bar=round(float(v) / M_PER_BAR, 5), temp_c=round(float(tc), 2),
                                  battery_v=battery_v, simulated=True))
    return msgs


def to_mqtt(msg: SensorMessage) -> tuple[str, str]:
    """(topic, JSON payload) ready for any MQTT client."""
    return TOPIC.format(farm=msg.farm, node=msg.node), json.dumps(msg.model_dump(), separators=(",", ":"))
