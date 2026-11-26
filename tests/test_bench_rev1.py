"""Rev 1 bench simulator + detector: contract, states, faults, branch."""
import pytest

from detection.bench_detector import BenchConfig, BenchDetector, run_messages
from hydropin.messages import validate_message
from simulator.bench_rev1 import (CLEAN_SCENARIOS, FAULT_SCENARIOS, build, events_for,
                                  list_scenarios, simulate)

FRAME_KEYS = {"ts", "pt1_bar", "pt2_bar", "dp_bar", "flow_lpm", "flow_base_lpm", "state", "p_leak",
              "methods", "faults", "branch", "loc", "leak_lpm", "lost_l"}


@pytest.mark.parametrize("name", list_scenarios())
def test_simulated_messages_follow_the_contract(name):
    msgs = simulate(build(name, duration_s=60))
    assert msgs
    for m in msgs:
        validate_message(m)
        assert m["values"]["flow_l1_lpm"] == m["values"]["flow_l2_lpm"] == m["values"]["flow_l3_lpm"] == 0


def test_leak_label_only_after_onset():
    msgs = simulate(build("leak_L2"))
    labels = {m["label"] for m in msgs if m["ts_device_ms"] < 80_000}
    assert labels == {"none"}
    assert {m["label"] for m in msgs if m["ts_device_ms"] >= 80_000} == {"leak_L2"}
    assert events_for(build("leak_L2"))[0] == {"t_s": 80.0, "type": "leak_on", "tap": "L2"}


def test_wifi_gap_skips_seq():
    seqs = [m["seq"] for m in simulate(build("wifi_gap"))]
    assert max(b - a for a, b in zip(seqs, seqs[1:])) > 10


def test_frame_has_contract_fields():
    fr = run_messages(simulate(build("baseline", duration_s=70)))
    assert FRAME_KEYS <= set(fr[-1])
    assert set(fr[-1]["loc"]) == {"L1", "L2", "L3"}
    assert set(fr[-1]["methods"]) == {"flow", "m2"}


def test_states_settle_learn_then_healthy():
    fr = run_messages(simulate(build("baseline")))
    order = [f["state"] for i, f in enumerate(fr) if i == 0 or f["state"] != fr[i - 1]["state"]]
    assert order == ["SETTLING", "LEARNING", "HEALTHY"]
    assert fr[-1]["flow_base_lpm"] == pytest.approx(1.5, abs=0.1)


@pytest.mark.parametrize("name", CLEAN_SCENARIOS + FAULT_SCENARIOS)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_false_alarm(name, seed):
    fr = run_messages(simulate(build(name, seed=seed)))
    assert all(f["state"] not in ("WATCH", "LEAK") for f in fr), name


@pytest.mark.parametrize("name,branch", [("leak_L1", "A"), ("leak_L2", "B"), ("leak_L3", "B")])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_medium_leak_detected_with_branch(name, branch, seed):
    fr = run_messages(simulate(build(name, seed=seed)))
    first = next(f for f in fr if f["state"] == "LEAK")
    delay = first["seq"] * 0.5 - 80.0
    assert 0 < delay < 15
    assert first["branch"] == branch
    assert fr[-1]["leak_lpm"] == pytest.approx(0.3, abs=0.1)
    assert fr[-1]["lost_l"] > 0


def test_unplugged_sensor_is_a_fault_not_a_leak():
    fr = run_messages(simulate(build("unplug_PT2")))
    assert "PT2_unplugged" in fr[-1]["faults"]
    assert fr[-1]["methods"]["m2"]["excluded"] is True
    fr = run_messages(simulate(build("unplug_PT1")))
    assert "PT1_unplugged" in fr[-1]["faults"]


def test_pump_restart_relearns():
    fr = run_messages(simulate(build("pump_restart")))
    states = [f["state"] for f in fr]
    assert "PUMP_OFF" in states
    assert states[-1] == "HEALTHY"
    i_off = states.index("PUMP_OFF")
    assert "LEARNING" in states[i_off:]


def test_leak_off_returns_to_healthy():
    fr = run_messages(simulate(build("leak_L1", leak_stop_s=150, duration_s=240)))
    assert any(f["state"] == "LEAK" for f in fr)
    assert fr[-1]["state"] == "HEALTHY"


def test_reset_baseline_and_offline():
    det = BenchDetector()
    msgs = simulate(build("baseline", duration_s=70))
    for m in msgs:
        det.update_message(m)
    det.reset_baseline()
    assert det.update_message(msgs[-1])["state"] in ("SETTLING", "LEARNING")
    last_t = msgs[-1]["ts"]
    assert det.state_at(last_t)["state"] != "OFFLINE"
    from datetime import datetime, timedelta
    later = (datetime.fromisoformat(last_t.replace("Z", "+00:00")) + timedelta(seconds=10)).isoformat()
    assert det.state_at(later)["state"] == "OFFLINE"


def test_detector_ignores_labels():
    msgs = simulate(build("baseline"))
    for m in msgs:
        m["label"] = "leak_L1"
    assert all(f["state"] not in ("WATCH", "LEAK") for f in run_messages(msgs))


def test_config_roundtrip(tmp_path):
    import json
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(BenchConfig(tau2=0.95).to_dict()))
    assert BenchConfig.from_json(p).tau2 == 0.95
