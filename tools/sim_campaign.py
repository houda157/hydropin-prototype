"""Fill a backend database with a *simulated* campaign, to rehearse the bench-day pipeline.

    python -m tools.sim_campaign --db scratch/sim_campaign.db [--repeats 6]

Same shape as role 1's protocol: L1/L2/L3 x small/large x repeats staged leak runs (60 s healthy,
leak, then off), one 5-minute quiet run, fault runs (unplug, pump restart) and blind runs (marked
blind). Every run is labelled "SIMULATED" in its notes. Never point this at data/hydropin.db.

Then:  python -m tools.noise --db <db>; python -m detection.train_bench --db <db> --out <model>;
       python -m tools.export_replays --db <db>  (with the model at data/model.json)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import storage
from simulator.bench_rev1 import build, events_for, simulate


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_SEQ = [0]


def add_run(conn, sc, start: datetime, *, opening=None, blind=False) -> datetime:
    msgs = simulate(sc, start=start)
    for m in msgs:                        # one ESP32 that keeps counting: (device, seq) is unique
        m["seq"] += _SEQ[0]
        storage.insert_reading(conn, m)
    _SEQ[0] = msgs[-1]["seq"] + 1
    rid = storage.create_run(conn, sc.label, notes=f"SIMULATED {sc.name}: {sc.notes}", opening=opening, blind=blind)
    conn.execute("UPDATE runs SET started_ts = ?, stopped_ts = ? WHERE id = ?", (msgs[0]["ts"], msgs[-1]["ts"], rid))
    for e in events_for(sc):
        storage.insert_event(conn, e["type"], ts=_iso(start + timedelta(seconds=e["t_s"])), tap=e.get("tap"), run_id=rid)
    return start + timedelta(seconds=sc.duration_s + 30)


def make(db: Path, repeats: int = 6) -> int:
    if db.resolve() == Path("data/hydropin.db").resolve():
        raise SystemExit("refusing to write a simulated campaign into the real database")
    storage.init_db(db)
    t = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
    n = 0
    with storage.db_session(db) as conn:
        for tap in ("L1", "L2", "L3"):
            for size, opening in (("small", "small"), ("large", "large")):
                for k in range(repeats):
                    sc = build(f"leak_{tap}", leak_size=size, seed=5000 + 100 * n, leak_start_s=60.0,
                               leak_stop_s=120.0, duration_s=150.0)
                    t = add_run(conn, sc, t, opening=opening)
                    n += 1
        t = add_run(conn, build("baseline", duration_s=300.0, seed=4242), t)
        n += 1
        for name in ("unplug_PT1", "unplug_PT2", "pump_restart", "ripple", "wifi_gap"):
            t = add_run(conn, build(name, seed=4300 + n), t)
            n += 1
        for k, tap in enumerate(("L2", "L1", "L3", "L1", "L2", "L3")):
            sc = build(f"leak_{tap}", leak_size=("medium", "large")[k % 2], seed=6000 + k,
                       leak_start_s=70.0, leak_stop_s=130.0, duration_s=160.0)
            t = add_run(conn, sc, t, opening=("medium", "large")[k % 2], blind=True)
            n += 1
        conn.commit()
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--repeats", type=int, default=6)
    a = ap.parse_args(argv)
    n = make(a.db, a.repeats)
    print(f"{n} simulated runs -> {a.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
