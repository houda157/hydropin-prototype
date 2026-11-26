"""Bench-day tools on a simulated campaign: noise -> train (split) -> export -> scoreboard v1.1."""
import json
import os
from pathlib import Path

import pytest

from detection.replay import score_replay, scoreboard
from detection.train_bench import split_runs, train
from detection.campaign import load_runs
from tools import noise, sim_campaign


@pytest.fixture(scope="module")
def camp(tmp_path_factory):
    d = tmp_path_factory.mktemp("camp")
    db = d / "camp.db"
    sim_campaign.make(db, repeats=1)
    return d, db


def test_sim_campaign_refuses_real_db():
    with pytest.raises(SystemExit):
        sim_campaign.make(Path("data/hydropin.db"))


def test_noise_from_longest_quiet_run(camp):
    d, db = camp
    out = d / "noise.json"
    assert noise.main(["--db", str(db), "--out", str(out)]) == 0
    nz = json.loads(out.read_text())
    assert nz["n"] >= 500                          # the 5-minute quiet run, not a short fault run
    assert 0.003 < nz["sigma"]["pt1_bar"] < 0.012  # simulator noise is 0.006 bar


def test_split_is_stratified_and_blind_is_test(camp):
    _, db = camp
    runs = load_runs(db)
    tr, te = split_runs(runs)
    assert not set(tr) & set(te) and len(tr) + len(te) == len(runs)
    blind = {r["id"] for r in runs if r["meta"].get("blind")}
    assert blind and blind <= set(te)
    assert split_runs(runs) == (tr, te)            # fixed seed


def test_train_fits_fingerprints_on_train_only(camp):
    d, db = camp
    m = train(db, d / "noise.json")
    t = m["training"]
    assert set(t["train_runs"]).isdisjoint(t["test_runs"])
    l1, l2 = m["fingerprints"]["L1"], m["fingerprints"]["L2"]
    assert abs(l1[0]) > abs(l1[1])                 # L1 drops PT1 more
    assert abs(l2[1]) > abs(l2[0])                 # L2 drops PT2 more
    assert m["tau2"] in (0.8, 0.9, 0.95) and m["n_consecutive"] in (6, 10, 14)


def test_export_uses_model_split_and_marks_simulation(camp, monkeypatch):
    d, db = camp
    (d / "data").mkdir(exist_ok=True)
    (d / "data" / "model.json").write_text(json.dumps(train(db, d / "noise.json")))
    monkeypatch.chdir(d)
    from tools import export_replays
    assert export_replays.main(["--db", str(db), "--out", str(d / "dash")]) == 0
    board = json.loads((d / "dash" / "scoreboard.json").read_text())
    assert board["simulation"] is True             # SIMULATED notes are never shown as measured
    assert board["headline"].startswith("test split")
    assert set(board["per_method"]) == {"fused", "flow", "m2"}
    assert board["blind"]["runs"] == 6
    assert board["summary"]["false_alarm_runs"] == 0
    cm = board["confusion"]["taps"]
    assert sum(sum(v.values()) for v in cm.values()) == board["summary"]["leak_runs"]


def test_scoreboard_without_split_uses_all_runs():
    rows = [{"id": "a", "label": "none", "detected": None, "false_alarm": False, "healthy_s": 3600.0,
             "false_episodes": {"fused": 1, "flow": 2, "m2": 0}, "split": None, "blind": False}]
    b = scoreboard(rows, simulation=True)
    assert b["headline"] == "all runs" and b["summary"]["false_alarms_per_hour"] == 1.0
    assert b["per_method"]["flow"]["false_alarms_per_hour"] == 2.0
