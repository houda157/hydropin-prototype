import json
from pathlib import Path

from hydropin import config


def test_calibration_json_mirrors_config():
    path = Path(__file__).resolve().parents[1] / "data" / "calibration.json"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(config.calibration_dict())), \
        "data/calibration.json is stale: regenerate it (see hydropin.config.calibration_dict)"


def test_calibration_json_converts_like_config():
    c = config.calibration_dict()["pressure"]["PT2"]
    raw = 20000
    bar = c["offset_bar"] + c["slope_bar_per_v"] * raw * c["lsb_v"] * c["divider"]
    assert abs(bar - (-1.0 + 0.26 * raw / 32767.0 * 4.096 * 3.0)) < 1e-9
