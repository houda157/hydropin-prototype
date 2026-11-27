"""The dashboard's 3D bench files (tools/export_bench3d.py) match what dashboard/app.js reads."""
import json

from tools.export_bench3d import BUNDLE, OUT, extract_bd, slim, VIEWER

D = OUT.parent


def test_board_json_has_every_state_the_dashboard_asks_for():
    b = json.loads(OUT.read_text(encoding="utf-8"))
    width = 6 + len(b["nodes"]) + len(b["links"])           # P1 P2 F0 leak return pmax | nodes | links
    assert "none|0" in b["states"]
    for tap in ("L1", "L2", "L3"):
        for d in b["D"]:
            assert f"{tap}|{d}" in b["states"]
    assert all(len(row) == width for row in b["states"].values())
    assert b["setting"] == {"r": 65, "v": 78.0}


def test_board_json_is_up_to_date_with_the_twin_viewer():
    fresh = slim(extract_bd(VIEWER.read_text(encoding="utf-8")))
    assert json.loads(OUT.read_text(encoding="utf-8")) == json.loads(json.dumps(fresh))


def test_dashboard_bundle_is_the_rebuilt_one_with_set_live():
    shipped = (D / BUNDLE.name).read_bytes()
    assert shipped == BUNDLE.read_bytes(), "run python -m tools.export_bench3d after rebuilding the bundle"
    assert b"setLive" in shipped
