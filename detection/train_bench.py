"""Train the bench detector on the campaign's training split -> data/model.json.

    python -m detection.train_bench --db data/hydropin.db [--noise data/noise.json] [--out data/model.json]

1. Split the stopped runs 70 / 30 into train / test, stratified by label, fixed seed. Blind-test
   runs always go to test. The split is saved in the model, so the export scores the headline on
   test runs only and no test run ever shapes the model.
2. Noise floors from role 1's quiet run (data/noise.json from tools/noise.py), if present.
3. Fingerprints: for each tap, the mean direction of the pressure drop [dPT1, dPT2] in the
   training leak runs (from 10 s after "leak on" to "leak off", against the 30 s before).
4. LEAK rule: tau2 and N chosen on training runs only - first no false alarm, then the most leaks
   detected, then the shortest median delay.

The backend (backend/bench_live.py) and the export (tools/export_replays.py) load data/model.json
automatically when it exists.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from detection.bench_detector import TAPS, BenchConfig, run_messages
from detection.campaign import load_runs
from detection.replay import build_replay, score_replay, scoreboard

SEED = 20261126
TEST_SHARE = 0.30
GRID_TAU2 = (0.8, 0.9, 0.95)
GRID_N = (6, 10, 14)


def split_runs(runs: list[dict], test_share: float = TEST_SHARE, seed: int = SEED) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    by_label: dict[str, list[str]] = defaultdict(list)
    test = []
    for r in runs:
        if r["meta"].get("blind"):
            test.append(r["id"])
        else:
            by_label[r["label"]].append(r["id"])
    train = []
    for label in sorted(by_label):
        ids = sorted(by_label[label])
        rng.shuffle(ids)
        k = int(round(len(ids) * test_share)) if len(ids) > 1 else 0
        test += ids[:k]
        train += ids[k:]
    return sorted(train), sorted(test)


def _replay(r: dict, cfg: BenchConfig) -> dict:
    frames = run_messages(r["msgs"], cfg)
    return build_replay(frames, r["events"], run_id=r["id"], label=r["label"], simulation=False,
                        source="bench rev 1", meta=r["meta"])


def fit_fingerprints(train: list[dict], cfg: BenchConfig) -> tuple[dict, dict]:
    dirs: dict[str, list[np.ndarray]] = defaultdict(list)
    for r in train:
        if not r["label"].startswith("leak_"):
            continue
        rep = _replay(r, cfg)
        on = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_on"), None)
        off = next((e["t_s"] for e in rep["events"] if e["type"] == "leak_off"), None)
        if on is None:
            continue
        fr = rep["frames"]
        base = [(f["pt1_bar"], f["pt2_bar"]) for f in fr if on - 30 <= f["t_s"] < on and f["state"] in ("HEALTHY", "WATCH")
                and f["pt2_bar"] is not None]
        leak = [(f["pt1_bar"], f["pt2_bar"]) for f in fr if f["t_s"] >= on + 10 and (off is None or f["t_s"] <= off)
                and f["pt2_bar"] is not None]
        if len(base) < 10 or len(leak) < 10:
            continue
        d = np.mean(leak, axis=0) - np.mean(base, axis=0)
        if np.linalg.norm(d) > 0:
            dirs[r["label"].split("_", 1)[1]].append(d / np.linalg.norm(d))
    fps, counts = dict(cfg.fingerprints), {}
    for t in TAPS:
        if dirs[t]:
            v = np.mean(dirs[t], axis=0)
            fps[t] = [round(float(x), 4) for x in v / np.linalg.norm(v)]
        counts[t] = len(dirs[t])
    return fps, counts


def choose_rule(train: list[dict], cfg: BenchConfig) -> tuple[float, int, list[dict]]:
    grid = []
    for tau2 in GRID_TAU2:
        for n in GRID_N:
            c = BenchConfig(**{**cfg.to_dict(), "tau2": tau2, "n_consecutive": n})
            rows = [score_replay(_replay(r, c), tau2, n) for r in train]
            s = scoreboard(rows, simulation=False)["summary"]
            grid.append({"tau2": tau2, "n": n, "false_alarm_runs": s["false_alarm_runs"],
                         "detected": s["detected"], "median_delay_s": s["median_delay_s"]})
    best = min(grid, key=lambda g: (g["false_alarm_runs"], -g["detected"],
                                    g["median_delay_s"] if g["median_delay_s"] is not None else 1e9))
    return best["tau2"], best["n"], grid


def train(db: Path, noise: Path | None = None) -> dict:
    runs = load_runs(db)
    if not runs:
        raise SystemExit(f"no stopped runs in {db}")
    train_ids, test_ids = split_runs(runs)
    tr = [r for r in runs if r["id"] in set(train_ids)]
    cfg = BenchConfig()
    noise_note = "defaults (no data/noise.json)"
    if noise and noise.exists():
        nz = json.loads(noise.read_text(encoding="utf-8"))["sigma"]
        sp = max([v for v in (nz.get("pt1_bar"), nz.get("pt2_bar")) if v is not None], default=None)
        sf = nz.get("flow_lpm")
        if sp is not None:
            cfg.floor_p_bar = round(max(cfg.floor_p_bar, 2.0 * sp), 4)
        if sf is not None:
            cfg.floor_f_lpm = round(max(cfg.floor_f_lpm, 2.0 * sf), 4)
        noise_note = f"floors = max(default, 2 sigma) from {noise.as_posix()}"
    fps, counts = fit_fingerprints(tr, cfg)
    cfg.fingerprints = fps
    tau2, n, grid = choose_rule(tr, cfg)
    cfg.tau2, cfg.n_consecutive = tau2, n
    model = {**cfg.to_dict(),
             "training": {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "db": db.as_posix(), "seed": SEED, "test_share": TEST_SHARE,
                          "train_runs": train_ids, "test_runs": test_ids,
                          "fingerprint_runs": counts, "noise": noise_note, "rule_grid": grid,
                          "note": "fitted on train runs only; blind runs are test only"}}
    return model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path("data/hydropin.db"))
    ap.add_argument("--noise", type=Path, default=Path("data/noise.json"))
    ap.add_argument("--out", type=Path, default=Path("data/model.json"))
    a = ap.parse_args(argv)
    model = train(a.db, a.noise)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(model, indent=1), encoding="utf-8")
    t = model["training"]
    print(f"{len(t['train_runs'])} train / {len(t['test_runs'])} test runs; tau2={model['tau2']} "
          f"N={model['n_consecutive']}; fingerprints {model['fingerprints']} -> {a.out}")
    print("next: python -m tools.export_replays --db", a.db.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
