import numpy as np
import pytest

from hydropin import config
from tools.calibrate import flow_calibration, pressure_calibration


def test_flow_calibration_reports_both_options():
    r = flow_calibration(pulses=900, litres=2.0, seconds=60)
    assert r["pulses_per_litre"] == pytest.approx(450.0)
    assert r["measured_lpm"] == pytest.approx(2.0)
    assert r["raw_lpm_nominal"] == pytest.approx(2.0)
    assert r["gain_with_nominal_k"] == pytest.approx(1.0)

    r2 = flow_calibration(pulses=1350, litres=2.0, seconds=60)
    assert r2["pulses_per_litre"] == pytest.approx(675.0)
    assert r2["raw_lpm_nominal"] == pytest.approx(3.0)
    assert r2["gain_with_nominal_k"] == pytest.approx(2.0 / 3.0)


def test_pressure_calibration_recovers_gain_and_offset():
    volts = np.array([0.5, 1.0, 1.5, 2.0])
    bars = 3.0 * volts + 0.5
    adc = volts / (config.ADS_VOLTAGE_RANGE * config.PRESSURE_DIVIDER) * config.ADS_COUNTS
    r = pressure_calibration(adc, bars)
    assert r["gain"] == pytest.approx(3.0, rel=1e-9)
    assert r["offset_bar"] == pytest.approx(0.5, abs=1e-9)
    assert r["r2"] == pytest.approx(1.0, abs=1e-9)
    assert r["max_abs_residual_bar"] == pytest.approx(0.0, abs=1e-9)
