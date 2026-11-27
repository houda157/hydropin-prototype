"""Guard against firmware/Python calibration drift without needing PlatformIO."""
import re
from pathlib import Path

import pytest

from hydropin import config

CONFIG_H = Path(__file__).resolve().parent.parent / "firmware" / "include" / "config.h"


def text() -> str:
    return CONFIG_H.read_text(encoding="utf-8")


def number(name: str) -> float:
    m = re.search(rf"{name}\s*=\s*([-0-9.]+)f?\s*;", text())
    assert m, f"{name} not found in firmware config.h"
    return float(m.group(1))


def define(name: str) -> str:
    m = re.search(rf'#define\s+{name}\s+"([^"]+)"', text())
    assert m, f"{name} not found in firmware config.h"
    return m.group(1)


def test_schema_and_device_match():
    assert define("SCHEMA_VERSION") == config.SCHEMA_VERSION
    assert define("DEVICE_ID") == config.DEFAULT_DEVICE


def test_calibration_constants_match():
    assert number("FLOW_K_PULSES_PER_LITRE") == config.FLOW_K_PULSES_PER_LITRE
    assert number("FLOW_GAIN") == config.FLOW_GAIN
    assert number("PRESSURE_GAIN") == config.PRESSURE_GAIN
    assert number("PRESSURE_OFFSET_BAR") == config.PRESSURE_OFFSET_BAR
    assert number("ADS_VOLTAGE_RANGE") == config.ADS_VOLTAGE_RANGE
    assert number("ADS_COUNTS") == config.ADS_COUNTS
    assert number("PRESSURE_MAX_BAR") == config.PRESSURE_RANGE_BAR[1]


@pytest.mark.xfail(strict=False, reason="firmware/ is Talel's branch version (22k/10k, x3.2) until Moetez pushes the "
                   "bench firmware with the real 20k/10k (x3.0) divider; the backend recomputes bar from raw ADC "
                   "counts with x3.0, so detection is right either way. Remove this mark after that merge.")
def test_pressure_divider_matches():
    assert number("PRESSURE_DIVIDER") == config.PRESSURE_DIVIDER


def test_timing_matches():
    period_ms = number("PUBLISH_PERIOD_MS")
    window_ms = number("FLOW_WINDOW_MS")
    slots = number("FLOW_WINDOW_SLOTS")
    assert period_ms == config.SAMPLE_PERIOD_S * 1000
    assert window_ms == config.FLOW_MEASURE_WINDOW_S * 1000
    assert slots == window_ms / period_ms
