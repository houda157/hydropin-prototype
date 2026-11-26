import json

from simulator.bench_rev1 import build, simulate
from tools.serial_bridge import bridge_lines


def test_bridge_forwards_frames_and_skips_logs():
    msgs = simulate(build("baseline", duration_s=3))
    lines = ["[wifi] connecting...", ""] + [json.dumps(m) for m in msgs] + ['{"broken": ', b"[mqtt] ok\n"]
    sent = []
    n = bridge_lines(lines, sent.append, log=lambda *_: None)
    assert n["sent"] == len(msgs) == len(sent)
    assert n["invalid"] == 1 and n["skipped"] == 3
    assert sent[0]["seq"] == msgs[0]["seq"]


def test_bridge_survives_send_failures():
    msgs = simulate(build("baseline", duration_s=1))

    def boom(_):
        raise ConnectionError("broker down")
    n = bridge_lines([json.dumps(m) for m in msgs], boom, log=lambda *_: None)
    assert n["send_failed"] == len(msgs) and n["sent"] == 0
