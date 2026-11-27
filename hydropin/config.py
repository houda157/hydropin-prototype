"""Single source of truth for units, calibration and transport.

Mirror of firmware/include/config.h. If you change a constant here, change it
there too (the contract test asserts the two stay compatible).

Calibration (bench wiring rev 1, 2026-11-23):
    flow_lpm     = (pulses / dt_s) / 7.5 * 1.5       # provisional, calibrate
    PT1 (branch A): 0..6 bar, 0-10 V, R1=22k series + R2=10k shunt
        V_sensor = V_ads * 3.2
        pressure_bar = 0.0 + 0.6 * V_sensor
    PT2 (branch B): -1..1.6 bar, 0-10 V, R3=22k series + R4=10k shunt
        V_sensor = V_ads * 3.2
        pressure_b_bar = -1.0 + 0.26 * V_sensor
    Flow main: 5 V pulse, R5=10k series + R6=20k shunt -> 3.33 V at GPIO27.

The flow gain is still provisional; fit it with a measured volume. The pressure
fits above are from the sensor datasheet range + the actual 22k/10k divider.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = "1.0"

# --- transport -------------------------------------------------------------
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_BASE_TOPIC = "hydropin/bench"
DEFAULT_DEVICE = "esp32-bench-01"     # the real board (firmware DEVICE_ID)
SIM_DEVICE = "sim-bench-01"          # simulator/bench_rev1.py, so simulated runs never mix with the board's



def fast_local_url(url: str) -> str:
    """``http://localhost:...`` -> ``http://127.0.0.1:...``.

    On Windows, "localhost" tries IPv6 (::1) first; uvicorn listens on IPv4 only, so every
    request waited about 2 s before falling back. That is slower than the board's 2 messages
    per second, so the serial bridge and the simulator fell further and further behind.
    """
    return re.sub(r"^(https?://)localhost(?=[:/]|$)", r"\g<1>127.0.0.1", url)


PUBLISH_HZ = 2.0
SAMPLE_PERIOD_S = 1.0 / PUBLISH_HZ
# Flow is counted over a longer window than the publish period: at 2 Hz one
# pulse would be 0.4 L/min, which cannot see small leaks. A 2 s sliding window
# gives 0.1 L/min resolution while still publishing every 0.5 s.
FLOW_MEASURE_WINDOW_S = 2.0


def telemetry_topic(device: str = "+") -> str:
    return f"{MQTT_BASE_TOPIC}/{device}/telemetry"


def status_topic(device: str = "+") -> str:
    return f"{MQTT_BASE_TOPIC}/{device}/status"


# --- flow sensor (YF-S201 class, Hall effect) ------------------------------
FLOW_K_PULSES_PER_LITRE = 450.0                       # datasheet nominal
FLOW_PULSES_PER_LPM = FLOW_K_PULSES_PER_LITRE / 60.0  # 7.5 Hz per L/min
FLOW_GAIN = 1.5                                       # "flow * 3/2"

# --- pressure sensors (0-10 V through 22k/10k into ADS1115) ----------------
# Divider: 22k series + 10k shunt -> V_ads = V_sensor * 10/32 = V_sensor / 3.2.
# At 10 V the ADS pin sees 3.125 V, inside the +/-4.096 V PGA range (gain=1).
ADS_VOLTAGE_RANGE = 4.096
ADS_COUNTS = 32767.0

# PT1, branch A: 0..6 bar over 0-10 V.
PRESSURE_DIVIDER = 3.2
PRESSURE_GAIN = 0.6                                   # 6 bar / 10 V
PRESSURE_OFFSET_BAR = 0.0
PRESSURE_RANGE_BAR = (0.0, 6.0)

# PT2, branch B: -1..1.6 bar over 0-10 V.
PRESSURE_B_DIVIDER = 3.2
PRESSURE_B_GAIN = 0.26                                # 2.6 bar / 10 V
PRESSURE_B_OFFSET_BAR = -1.0
PRESSURE_B_RANGE_BAR = (-1.0, 1.6)

FLOW_CHANNELS = ("main", "l1", "l2", "l3")
BRANCH_CHANNELS = ("l1", "l2", "l3")
LABELS = ("none", "leak_L1", "leak_L2", "leak_L3")

# Physical sanity ranges used by validation (not hard clamps).
FLOW_RANGE_LPM = (0.0, 60.0)


def pulses_to_flow_lpm(pulses: float, dt_s: float = SAMPLE_PERIOD_S) -> float:
    """Raw datasheet flow, before the bench gain."""
    if dt_s <= 0:
        raise ValueError("dt_s must be > 0")
    return (pulses / dt_s) / FLOW_PULSES_PER_LPM


def calibrate_flow(raw_lpm: float) -> float:
    return raw_lpm * FLOW_GAIN


def adc_to_sensor_volts(adc_counts: float, divider: float | None = None) -> float:
    divider = PRESSURE_DIVIDER if divider is None else divider
    return adc_counts / ADS_COUNTS * ADS_VOLTAGE_RANGE * divider


def sensor_volts_to_bar(
    sensor_volts: float,
    gain: float | None = None,
    offset: float | None = None,
) -> float:
    gain = PRESSURE_GAIN if gain is None else gain
    offset = PRESSURE_OFFSET_BAR if offset is None else offset
    return sensor_volts * gain + offset


def adc_to_pressure_bar(adc_counts: float) -> float:
    return sensor_volts_to_bar(adc_to_sensor_volts(adc_counts))


def adc_to_pressure_b_bar(adc_counts: float) -> float:
    volts = adc_to_sensor_volts(adc_counts, PRESSURE_B_DIVIDER)
    return sensor_volts_to_bar(volts, PRESSURE_B_GAIN, PRESSURE_B_OFFSET_BAR)


def flow_lpm_to_pulses(flow_lpm: float, dt_s: float = SAMPLE_PERIOD_S) -> int:
    """Inverse of the calibration chain; used by the simulator."""
    raw = flow_lpm / FLOW_GAIN
    return max(0, int(round(raw * FLOW_PULSES_PER_LPM * dt_s)))


def pressure_bar_to_adc(pressure_bar: float) -> int:
    """Inverse of the PT1 calibration chain; used by the simulator."""
    sensor_volts = (pressure_bar - PRESSURE_OFFSET_BAR) / PRESSURE_GAIN
    adc = sensor_volts / (ADS_VOLTAGE_RANGE * PRESSURE_DIVIDER) * ADS_COUNTS
    return int(round(max(0.0, min(ADS_COUNTS, adc))))


def pressure_b_bar_to_adc(pressure_b_bar: float) -> int:
    """Inverse of the PT2 calibration chain."""
    sensor_volts = (pressure_b_bar - PRESSURE_B_OFFSET_BAR) / PRESSURE_B_GAIN
    adc = sensor_volts / (ADS_VOLTAGE_RANGE * PRESSURE_B_DIVIDER) * ADS_COUNTS
    return int(round(max(0.0, min(ADS_COUNTS, adc))))


def calibration_dict() -> dict:
    """The calibration constants above in the brief's data/calibration.json shape.

    This module stays the source of truth; data/calibration.json is a read-only mirror for the
    report and other tools. Regenerate it after any change:
        python -c "import json, hydropin.config as c; open('data/calibration.json','w').write(json.dumps(c.calibration_dict(), indent=1) + '\n')"
    tests/test_calibration_json.py fails if the two drift apart.
    """
    lsb_v = ADS_VOLTAGE_RANGE / ADS_COUNTS
    return {
        "version": "rev1",
        "note": "Mirror of hydropin/config.py (source of truth) and firmware/include/config.h. "
                "bar = offset_bar + slope_bar_per_v * (raw * lsb_v * divider). Flow gain is provisional.",
        "pressure": {
            "PT1": {"adc_channel": "A0", "branch": "A", "range_bar": list(PRESSURE_RANGE_BAR), "lsb_v": lsb_v,
                    "divider": PRESSURE_DIVIDER, "offset_bar": PRESSURE_OFFSET_BAR,
                    "slope_bar_per_v": PRESSURE_GAIN},
            "PT2": {"adc_channel": "A1", "branch": "B", "range_bar": list(PRESSURE_B_RANGE_BAR), "lsb_v": lsb_v,
                    "divider": PRESSURE_B_DIVIDER, "offset_bar": PRESSURE_B_OFFSET_BAR,
                    "slope_bar_per_v": PRESSURE_B_GAIN},
        },
        "flow": {"F0": {"gpio": 27, "pulses_per_litre": FLOW_K_PULSES_PER_LITRE, "hz_per_lpm": FLOW_PULSES_PER_LPM,
                        "gain": FLOW_GAIN, "window_s": FLOW_MEASURE_WINDOW_S, "provisional": True}},
    }
