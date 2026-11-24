import numpy as np
import pandas as pd
import pytest

from hydropin import config
from tools.calibrate import flow_calibration, pressure_calibration
from tools.label_csv import apply_label
from tools.validate_dataset import validate_frame


def frame(n=10, freq="500ms"):
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC"),
            "device": "esp32-test",
            "seq": range(n),
            "label": "none",
            "flow_main_lpm": 1.7,
            "flow_l1_lpm": 0.55,
            "flow_l2_lpm": 0.45,
            "flow_l3_lpm": 0.65,
            "pressure_bar": 2.0,
        }
    )


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


def test_label_csv_accepts_seconds_and_iso_onset():
    df = frame(n=4)
    by_seconds = apply_label(df, "leak_L2", 1.0)
    assert by_seconds["label"].tolist() == ["none", "none", "leak_L2", "leak_L2"]

    by_iso = apply_label(df, "leak_L1", "2026-01-01T00:00:01.000Z")
    assert by_iso["label"].tolist() == ["none", "none", "leak_L1", "leak_L1"]


def test_label_csv_rejects_unknown_label_and_unsorted_time():
    df = frame(n=3)
    with pytest.raises(ValueError):
        apply_label(df, "leak_L9", 0.0)
    bad = df.iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValueError):
        apply_label(bad, "leak_L1", 0.0)


def test_validate_dataset_accepts_clean_2hz_data():
    rep = validate_frame(frame(), expected_hz=2.0)
    assert rep.ok, rep.errors
    assert rep.median_dt_s == pytest.approx(0.5)
    assert rep.duplicates == 0


def test_validate_dataset_rejects_wrong_rate_duplicates_and_labels():
    wrong_rate = validate_frame(frame(freq="2s"), expected_hz=2.0)
    assert not wrong_rate.ok
    assert any("sample interval" in e for e in wrong_rate.errors)

    dup = frame()
    dup.loc[1, "seq"] = dup.loc[0, "seq"]
    assert not validate_frame(dup).ok

    bad_label = frame()
    bad_label["label"] = "leak_L9"
    assert not validate_frame(bad_label).ok
