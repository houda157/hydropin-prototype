"""Single source of truth for units, calibration and transport.

Mirror of firmware/include/config.h. If you change a constant here, change it
there too (the contract test asserts the two stay compatible).

Calibration (provisional, MUST be verified on the bench):
    flow_lpm       = (pulses / dt_s) / 7.5 * 1.5      # user: "flow * 3/2"
    sensor_volts   = adc_counts / 32767 * 4.096 * 3.2 # ADS1115 + 3.2 divider
    pressure_bar   = sensor_volts * 3.0 + 0.0         # user: "pressure * 3"

The pressure offset is 0 for a true 0..5 V sensor. If the sensor idles at
0.5 V (common for ratiometric transmitters), fit the offset on the bench with
`python -m tools.calibrate pressure ...` and set PRESSURE_OFFSET_BAR.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"

# --- transport -------------------------------------------------------------
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_BASE_TOPIC = "hydropin/bench"
DEFAULT_DEVICE = "esp32-bench-01"

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

# --- pressure sensor (analog 0..5 V through 3.2 divider into ADS1115) ------
# Divider: 22k series + 10k shunt -> V_ads = V_sensor * 10/32 = V_sensor / 3.2.
# At 5 V the ADS pin sees 1.5625 V, safely inside the +/-4.096 V PGA range.
ADS_VOLTAGE_RANGE = 4.096
ADS_COUNTS = 32767.0
PRESSURE_DIVIDER = 3.2
PRESSURE_GAIN = 3.0                                   # "pressure * 3" (bar per volt)
PRESSURE_OFFSET_BAR = 0.0                             # fit on the bench; 0 for 0..5 V

FLOW_CHANNELS = ("main", "l1", "l2", "l3")
BRANCH_CHANNELS = ("l1", "l2", "l3")
LABELS = ("none", "leak_L1", "leak_L2", "leak_L3")

# Physical sanity ranges used by validation (not hard clamps).
FLOW_RANGE_LPM = (0.0, 60.0)
# 0..5 V sensor * 3.0 bar/V = 15 bar full scale. A 16 bar reading is physically
# impossible on this divider/sensor, so do not accept it.
PRESSURE_RANGE_BAR = (0.0, 15.0)


def pulses_to_flow_lpm(pulses: float, dt_s: float = SAMPLE_PERIOD_S) -> float:
    """Raw datasheet flow, before the bench gain."""
    if dt_s <= 0:
        raise ValueError("dt_s must be > 0")
    return (pulses / dt_s) / FLOW_PULSES_PER_LPM


def calibrate_flow(raw_lpm: float) -> float:
    return raw_lpm * FLOW_GAIN


def adc_to_sensor_volts(adc_counts: float) -> float:
    return adc_counts / ADS_COUNTS * ADS_VOLTAGE_RANGE * PRESSURE_DIVIDER


def sensor_volts_to_bar(sensor_volts: float) -> float:
    return sensor_volts * PRESSURE_GAIN + PRESSURE_OFFSET_BAR


def adc_to_pressure_bar(adc_counts: float) -> float:
    return sensor_volts_to_bar(adc_to_sensor_volts(adc_counts))


def flow_lpm_to_pulses(flow_lpm: float, dt_s: float = SAMPLE_PERIOD_S) -> int:
    """Inverse of the calibration chain; used by the simulator."""
    raw = flow_lpm / FLOW_GAIN
    return max(0, int(round(raw * FLOW_PULSES_PER_LPM * dt_s)))


def pressure_bar_to_adc(pressure_bar: float) -> int:
    """Inverse of the calibration chain; used by the simulator."""
    sensor_volts = (pressure_bar - PRESSURE_OFFSET_BAR) / PRESSURE_GAIN
    adc = sensor_volts / (ADS_VOLTAGE_RANGE * PRESSURE_DIVIDER) * ADS_COUNTS
    return int(round(max(0.0, min(ADS_COUNTS, adc))))
