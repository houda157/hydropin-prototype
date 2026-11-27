"""The committed dashboard/m3 files match the format in dashboard/m3/FORMAT.md."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dashboard" / "m3"

pytestmark = pytest.mark.skipif(not (OUT / "index.json").exists(), reason="run python -m m3.export_dashboard")


def _cases():
    return json.loads((OUT / "index.json").read_text(encoding="utf-8"))["cases"]


def test_index():
    idx = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
    assert idx["simulation"] is True and idx["version"] == "1.1"
    assert len(idx["cases"]) == 4
    for c in idx["cases"]:
        assert (OUT / c["file"]).exists()


@pytest.mark.parametrize("case", _cases() if (OUT / "index.json").exists() else [], ids=lambda c: c["id"])
def test_case_file(case):
    d = json.loads((OUT / case["file"]).read_text(encoding="utf-8"))
    assert d["simulation"] is True and d["id"] == case["id"]
    f = d["frames"]
    assert len(f["H_m"]) == len(f["t_s"]) > 100 and all(len(row) == len(f["x_m"]) for row in f["H_m"])
    s = d["sensor"]
    assert len(s["H_m"]) == len(s["model_H_m"]) == 2600 and s["fs_hz"] == 2000
    # the curve is stored every 1 m, so its highest stored point can sit just beside the true peak
    assert len(d["tr"]["x_m"]) == len(d["tr"]["energy"]) and 0.99 <= max(d["tr"]["energy"]) <= 1.0
    x_true = d["leak"]["x_true_m"]
    assert abs(d["tr"]["x_est_m"] - x_true) < 2.0          # time reversal finds the leak
    assert abs(d["mfp"]["x_est_m"] - x_true) < 2.0
    assert d["timing"]["echo_expected_s"] < d["timing"]["reservoir_return_s"]
    assert set(d["error_m"]) >= {"tr", "mfp", "echo"}
