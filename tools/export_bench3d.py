"""Export the 3D bench for the dashboard: dashboard/bench3d/board.json + hp3d.bundle.js.

The dashboard's Bench panel draws Houda's 3D bench (simulator/run/viewer3d) but feeds it the
backend's own frames. From the twin it only needs the geometry and the twin states for the default
valve setting (the live bench does not report valve angles). Both are read from the twin viewer,
where run/demo.py inlines them as `const BD={...}`, so the dashboard and the viewer cannot drift.

The scene itself is Houda's bundle (simulator/run/viewer3d/hp3d.bundle.js, built from scene3d.js; see
the README there), copied next to the data because GitHub Pages publishes dashboard/ only.

    python -m tools.export_bench3d
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "simulator" / "demo" / "hydropin_viewer.html"
BUNDLE = ROOT / "simulator" / "run" / "viewer3d" / "hp3d.bundle.js"
OUT = ROOT / "dashboard" / "bench3d" / "board.json"
DEFAULT_R, DEFAULT_V = 65, 78.0        # board_tab.board_spec default: R1 = R2 = 65°, V1 = V2 = 78°
KEEP = ("link_ids", "nodes", "pos", "links", "xy", "cmap", "thr", "D")


def extract_bd(html: str) -> dict:
    i = html.index("const BD=") + len("const BD=")
    bd, _ = json.JSONDecoder().raw_decode(html, i)
    return bd


def slim(bd: dict) -> dict:
    prefix = f"{DEFAULT_R}|{DEFAULT_V:.1f}|"
    states = {k[len(prefix):]: v for k, v in bd["states"].items() if k.startswith(prefix)}
    if not states:
        raise SystemExit(f"no twin state for the default setting {prefix!r}")
    out = {k: bd[k] for k in KEEP if k in bd}
    out.update(setting={"r": DEFAULT_R, "v": DEFAULT_V}, states=states)   # keys: "<leak>|<d mm>"
    return out


def main() -> None:
    out = slim(extract_bd(VIEWER.read_text(encoding="utf-8")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(out['states'])} twin states, {OUT.stat().st_size / 1024:.0f} KB")
    shutil.copyfile(BUNDLE, OUT.parent / BUNDLE.name)
    print(f"{(OUT.parent / BUNDLE.name).relative_to(ROOT)}: copied from {BUNDLE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
