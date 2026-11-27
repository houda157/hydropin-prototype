"""Export replays + scoreboard for the static dashboard (GitHub Pages).

Simulated runs (clearly labelled ``simulation: true``) until the bench campaign exists:

    python -m tools.export_replays --sim

Real bench runs from the backend database (each stopped run; detector re-run from the raw readings,
events from the events table; ``simulation: false``):

    python -m tools.export_replays --db data/hydropin.db

Writes ``dashboard/replays/index.json``, ``dashboard/replays/<id>.json`` and ``dashboard/scoreboard.json``
(``scoreboard_sim.json`` for simulated runs, so a real scoreboard never gets overwritten by simulation).
The detector is the same code as live (detection/bench_detector.py) and never sees labels or events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from detection.bench_detector import MODEL_PATHS, load_config, run_messages
from detection.campaign import load_runs
from detection.replay import build_replay, score_replay, scoreboard
from simulator.bench_rev1 import CLEAN_SCENARIOS, FAULT_SCENARIOS, LEAK_SCENARIOS, build, events_for, simulate

OUT = Path("dashboard")


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_round(data), separators=(",", ":")), encoding="utf-8")


def sim_runs(seeds: int) -> tuple[list[dict], list[dict]]:
    """(replays kept for the dashboard, score rows over all seeds)."""
    keep, rows = [], []
    plan = [(n, s) for n in LEAK_SCENARIOS for s in ("small", "medium", "large")]
    plan += [(n, "medium") for n in CLEAN_SCENARIOS + FAULT_SCENARIOS]
    for name, size in plan:
        for seed in range(seeds):
            sc = build(name, leak_size=size, seed=1000 + seed, leak_stop_s=160.0 if name in LEAK_SCENARIOS else None,
                       duration_s=220.0 if name != "pump_restart" else None)
            msgs = simulate(sc)
            frames = run_messages(msgs)
            rid = f"sim_{name}" + (f"_{size}" if name in LEAK_SCENARIOS else "") + f"_s{seed}"
            meta = {"opening": size if sc.tap else None, "notes": sc.notes, "seed": sc.seed,
                    "measured_leak_lpm": None}
            rep = build_replay(frames, events_for(sc), run_id=rid, label=sc.label, simulation=True,
                               source="simulator/bench_rev1.py", meta=meta)
            rows.append(score_replay(rep))
            if seed == 0:
                keep.append(rep)
    return keep, rows


def _split_of(model_path: Path = MODEL_PATHS[0]) -> dict[str, str]:
    """run id -> "train" | "test", from the trained model (empty if there is none yet)."""
    if not model_path.exists():
        return {}
    tr = json.loads(model_path.read_text(encoding="utf-8")).get("training") or {}
    return {**{r: "train" for r in tr.get("train_runs", [])}, **{r: "test" for r in tr.get("test_runs", [])}}


def db_runs(db: Path) -> tuple[list[dict], list[dict]]:
    """Every stopped run, re-detected with the current model (data/model.json if present)."""
    cfg = load_config()
    split = _split_of()
    keep, rows = [], []
    for r in load_runs(db):
        frames = run_messages(r["msgs"], cfg)
        meta = {**r["meta"], "split": split.get(r["id"])}
        simulated = str(meta.get("notes") or "").startswith("SIMULATED")   # tools/sim_campaign.py rehearsal
        rep = build_replay(frames, r["events"], run_id=r["id"], label=r["label"], simulation=simulated,
                           source="simulated campaign (tools/sim_campaign.py)" if simulated else "bench rev 1",
                           meta=meta)
        keep.append(rep)
        rows.append(score_replay(rep, cfg.tau2, cfg.n_consecutive))
    return keep, rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true", help="simulated runs (labelled simulation)")
    g.add_argument("--db", type=Path, help="backend SQLite database with recorded runs")
    ap.add_argument("--seeds", type=int, default=10, help="--sim: seeds per scenario for the scoreboard")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    if a.sim:
        keep, rows = sim_runs(a.seeds)
        board = scoreboard(rows, simulation=True,
                           notes=f"Simulated bench rev 1 (simulator/bench_rev1.py), {a.seeds} seeds per scenario. "
                                 "Not measured: replace with the bench campaign.")
        board_name = "scoreboard_sim.json"
    else:
        keep, rows = db_runs(a.db)
        trained = MODEL_PATHS[0].exists()
        board = scoreboard(rows, simulation=any(r["simulation"] for r in keep),
                           notes=f"Bench rev 1 campaign, {len(rows)} recorded runs. "
                                 + ("Detector trained on the training split (data/model.json); headline on test runs."
                                    if trained else "Detector with default settings (no data/model.json yet)."))
        board_name = "scoreboard.json"

    rdir = a.out / "replays"
    idx_path = rdir / "index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {"version": "1.0", "runs": []}
    kind = "sim" if a.sim else "bench"
    index["runs"] = [r for r in index["runs"] if r.get("kind") != kind]
    for rep in keep:
        _write(rdir / f"{rep['id']}.json", rep)
        s = score_replay(rep)
        index["runs"].append({"id": rep["id"], "kind": kind, "simulation": rep["simulation"], "label": rep["label"],
                              "opening": rep["meta"].get("opening"), "notes": rep["meta"].get("notes"),
                              "duration_s": rep["frames"][-1]["t_s"], "detected": s["detected"],
                              "delay_s": s["delay_s"], "branch": s["branch"], "false_alarm": s["false_alarm"],
                              "split": rep["meta"].get("split"), "blind": bool(rep["meta"].get("blind")),
                              "file": f"{rep['id']}.json"})
    _write(idx_path, index)
    _write(a.out / board_name, board)
    print(f"{len(keep)} replays -> {rdir}; scoreboard ({len(rows)} runs) -> {a.out / board_name}")
    print(json.dumps(board["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
