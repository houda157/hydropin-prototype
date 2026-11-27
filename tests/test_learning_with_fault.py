"""A pressure sensor that is faulted before or during LEARNING must not block detection.

Spec 5.5.1: detection continues on flow plus the remaining sensor. Before this fix the
detector learned only from frames with no pressure fault, so it stayed in LEARNING forever.
"""
from detection.bench_detector import run_messages
from simulator.bench_rev1 import build, simulate


def test_pt2_unplugged_from_the_start_still_detects_a_leak_on_flow():
    frames = run_messages(simulate(build("leak_L1", unplug=("PT2", 0.0), duration_s=160)))
    states = [f["state"] for f in frames]
    assert "HEALTHY" in states                       # learning finished
    assert states[-1] == "LEAK"                      # flow alone carries the alarm
    last = frames[-1]
    assert "PT2_unplugged" in last["faults"]
    assert last["methods"]["m2"]["excluded"] is True
    assert last["branch"] is None                    # no honest branch with one pressure


def test_no_false_alarm_with_pt2_unplugged_and_no_leak():
    frames = run_messages(simulate(build("baseline", unplug=("PT2", 0.0), duration_s=160)))
    assert "HEALTHY" in [f["state"] for f in frames]
    assert not any(f["state"] in ("WATCH", "LEAK") for f in frames)


def test_healthy_sensors_still_give_the_branch():
    frames = run_messages(simulate(build("leak_L2", duration_s=160)))
    assert frames[-1]["state"] == "LEAK" and frames[-1]["branch"] == "B"
