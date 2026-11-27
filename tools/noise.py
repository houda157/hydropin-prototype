"""Sensor noise sigma from a quiet run (role 1's 5-minute no-leak run) -> data/noise.json.

    python -m tools.noise --db data/hydropin.db --run 3
    python -m tools.noise --db data/hydropin.db          # the longest stopped run labelled "none"
    python -m tools.noise --csv quiet.csv                # columns pressure_bar, pressure_b_bar, flow_main_lpm

sigma is the short-term noise: std of successive differences / sqrt(2), which slow drift does
not inflate. The plain standard deviation is reported next to it. Only samples with the pump
running are used. The output feeds detection/train_bench.py (noise floors), the farm leak data
(`python -m farm.leaks.generate --sigma-bar ...`) and the placement tool.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path

import numpy as np

PUMP_ON_LPM = 0.3
COLS = {"pt1_bar": "pressure_bar", "pt2_bar": "pressure_b_bar", "flow_lpm": "flow_main_lpm"}


def sigmas(rows: list[dict]) -> dict:
    on = [r for r in rows if (r.get("flow_main_lpm") or 0) > PUMP_ON_LPM]
    out = {"n": len(on), "sigma": {}, "std": {}}
    for key, col in COLS.items():
        x = np.array([r[col] for r in on if r.get(col) is not None], dtype=float)
        if len(x) < 10:
            out["sigma"][key] = out["std"][key] = None
            continue
        out["sigma"][key] = round(float(np.std(np.diff(x)) / math.sqrt(2)), 5)
        out["std"][key] = round(float(np.std(x)), 5)
    return out


def from_db(db: Path, run: int | None) -> tuple[list[dict], str]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        if run is None:
            row = conn.execute("SELECT * FROM runs WHERE label='none' AND stopped_ts IS NOT NULL "
                               "ORDER BY julianday(stopped_ts) - julianday(started_ts) DESC, id DESC "
                               "LIMIT 1").fetchone()
        else:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
        if row is None:
            raise SystemExit("no matching run (start and stop a run labelled 'none' first)")
        rd = conn.execute("SELECT * FROM readings WHERE ts >= ? AND ts <= ? ORDER BY ts",
                          (row["started_ts"], row["stopped_ts"] or "9999")).fetchall()
        return [dict(r) for r in rd], f"run {row['id']} ({row['label']})"
    finally:
        conn.close()


def from_csv(path: Path) -> tuple[list[dict], str]:
    import csv
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [{k: (float(v) if v not in ("", None) else None) for k, v in r.items() if k in COLS.values()}
                for r in csv.DictReader(fh)]
    return rows, path.name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--db", type=Path, default=Path("data/hydropin.db"))
    g.add_argument("--csv", type=Path)
    ap.add_argument("--run", type=int)
    ap.add_argument("--out", type=Path, default=Path("data/noise.json"))
    a = ap.parse_args(argv)
    rows, src = from_csv(a.csv) if a.csv else from_db(a.db, a.run)
    res = sigmas(rows)
    if res["n"] < 60:
        print(f"warning: only {res['n']} samples with the pump on; a 5-minute run gives ~600 at 2 Hz")
    res["source"] = src
    res["measured"] = True
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    s = res["sigma"]
    print(f"{src}: {res['n']} samples; sigma PT1 {s['pt1_bar']} bar, PT2 {s['pt2_bar']} bar, flow {s['flow_lpm']} L/min"
          f" -> {a.out}")
    p = [v for v in (s["pt1_bar"], s["pt2_bar"]) if v]
    if p:
        sig = round(max(p), 4)
        print("next:")
        print(f"  python -m farm.leaks.generate --sigma-bar {sig}")
        print(f"  python -m farm.placement.optimise --sigma-bar {sig}")
        print("  python -m farm.methods.results; python -m farm.drone.dispatch; python -m farm.explorer.build_data")
        print("  python -m detection.train_bench --db data/hydropin.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
