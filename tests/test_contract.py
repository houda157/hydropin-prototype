import json

import pytest

from hydropin import config
from hydropin.messages import SCHEMA_PATH, MessageError, make_message, parse_message, to_row, validate_message


def good_message(**overrides):
    flows = {"main": 3.0, "l1": 1.2, "l2": 0.9, "l3": 1.5}
    kwargs = dict(device="esp32-test", seq=7, flows_lpm=flows, pressure_bar=6.0)
    kwargs.update(overrides)
    return make_message(**kwargs)


def test_schema_file_is_valid_json():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    assert schema["properties"]["schema"]["const"] == config.SCHEMA_VERSION


def test_make_and_validate_roundtrip():
    msg = good_message()
    assert validate_message(msg) is msg
    assert msg["values"]["flow_main_lpm"] == 3.0
    assert msg["values"]["pressure_bar"] == 6.0
    assert msg["raw"]["flow_main_pulses"] >= 0
    assert 0 <= msg["raw"]["pressure_adc"] <= 32767


def test_parse_message_from_json_bytes():
    msg = good_message()
    parsed = parse_message(json.dumps(msg).encode())
    assert parsed["device"] == "esp32-test"


def test_to_row_is_flat_and_complete():
    row = to_row(good_message())
    for col in ("ts", "device", "seq", "scenario", "label", "pressure_bar", "dropout"):
        assert col in row
    for ch in config.FLOW_CHANNELS:
        assert f"flow_{ch}_lpm" in row
        assert f"raw_flow_{ch}_pulses" in row


def test_bad_label_rejected():
    with pytest.raises(MessageError):
        good_message(label="leak_L9")


def test_missing_channel_rejected():
    with pytest.raises(MessageError):
        good_message(flows_lpm={"main": 1.0, "l1": 0.1, "l2": 0.1})


def test_out_of_physical_range_rejected():
    msg = good_message()
    msg["values"]["pressure_bar"] = 999.0
    with pytest.raises(MessageError):
        validate_message(msg)


def test_schema_rejects_extra_field():
    msg = good_message()
    msg["values"]["secret"] = 1
    with pytest.raises(MessageError):
        validate_message(msg)


def test_flow_calibration_is_three_halves():
    raw = config.pulses_to_flow_lpm(pulses=7.5, dt_s=1.0)  # 1 L/min datasheet
    assert raw == pytest.approx(1.0)
    assert config.calibrate_flow(raw) == pytest.approx(1.5)


def test_pressure_calibration_pt1_roundtrip():
    counts = config.pressure_bar_to_adc(6.0)
    assert config.adc_to_pressure_bar(counts) == pytest.approx(6.0, abs=1e-3)


def test_pressure_calibration_pt2_roundtrip():
    for bar in (-1.0, 0.0, 1.6):
        counts = config.pressure_b_bar_to_adc(bar)
        assert config.adc_to_pressure_b_bar(counts) == pytest.approx(bar, abs=1e-3)


def test_pulse_quantization_is_documented_not_hidden():
    # With a 2 s flow window one pulse is 0.1 L/min after the *1.5 gain, which
    # is the smallest leak the bench can resolve. At 0.5 s it would be 0.4.
    one_pulse_lpm = (
        config.pulses_to_flow_lpm(1, dt_s=config.FLOW_MEASURE_WINDOW_S) * config.FLOW_GAIN
    )
    assert one_pulse_lpm == pytest.approx(0.1, abs=1e-9)


def test_make_message_raw_pulses_use_the_2s_flow_window():
    flows = {"main": 3.0, "l1": 1.2, "l2": 0.9, "l3": 1.5}
    msg = make_message(device="esp32-test", seq=1, flows_lpm=flows, pressure_bar=2.0)
    assert msg["raw"]["flow_main_pulses"] == 30  # 3.0 / 1.5 * 7.5 * 2
    assert msg["raw"]["flow_l1_pulses"] == 12
    assert msg["raw"]["flow_l2_pulses"] == 9
    assert msg["raw"]["flow_l3_pulses"] == 15
    recovered = (
        config.pulses_to_flow_lpm(msg["raw"]["flow_main_pulses"], config.FLOW_MEASURE_WINDOW_S)
        * config.FLOW_GAIN
    )
    assert recovered == pytest.approx(3.0)


def test_pressure_offset_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "PRESSURE_OFFSET_BAR", -1.5)
    adc = config.pressure_bar_to_adc(2.0)
    assert config.adc_to_pressure_bar(adc) == pytest.approx(2.0, abs=1e-3)


def test_pressure_sensor_full_scale_is_6_bar():
    # PT1: 0..6 bar over 0-10 V through 22k/10k -> 3.125 V at the ADS.
    # That is ~25000 counts, not 32767.
    assert config.PRESSURE_RANGE_BAR == (0.0, 6.0)
    adc = config.pressure_bar_to_adc(6.0)
    assert adc == pytest.approx(25000, abs=2)
    assert config.adc_to_pressure_bar(adc) == pytest.approx(6.0, abs=1e-3)
