"""Export the farm for other roles: layout.json (dashboard map), farm.inp and perturbed models.

    python -m farm.model.export_layout

Writes
  farm/model/layout.json        (and a copy in dashboard/farm/layout.json)
  farm/model/farm.inp           nominal model, all sectors open
  farm/model/perturbed/farm_pXX.inp  perturbed models for role 2's robustness check
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import wntr

from farm.model.build_farm import HERE, build_network, load_params, sector_flow_m3s

ROOT = HERE.parent.parent
LAYOUT_VERSION = "1.0"


def layout_dict(params: dict) -> dict:
    wn, meta = build_network(params)
    nodes = []
    for name, d in meta.nodes.items():
        n = wn.get_node(name)
        elev = n.base_head if d["kind"] == "reservoir" else n.elevation
        nodes.append({
            "id": name, "x": d["x"], "y": d["y"], "elev": round(float(elev), 3),
            "kind": d["kind"], "sector": d["sector"], "branch": d["branch"],
            "candidate": d["candidate"],
        })
    pipes = []
    for name, d in meta.pipes.items():
        link = wn.get_link(name)
        row = {"id": name, "from": link.start_node_name, "to": link.end_node_name,
               "kind": d["kind"], "sector": d["sector"], "branch": d["branch"],
               "leak_candidate": d["leak_candidate"]}
        if d["kind"] != "pump":
            row.update(length=round(link.length, 2), diameter=link.diameter)
        pipes.append(row)
    sectors = [{"id": s, "name": f"Sector {s}", "row": v["row"], "side": v["side"],
                "nodes": v["nodes"], "bbox": v["bbox"],
                "design_flow_lps": round(sector_flow_m3s(params) * 1000, 2)}
               for s, v in meta.sectors.items()]
    f = params["farm"]
    return {
        "version": LAYOUT_VERSION,
        "simulation": True,
        "label": "Simulated farm (WNTR) – not a real network",
        "units": {"xy": "m", "elev": "m", "length": "m", "diameter": "m", "flow": "L/s"},
        "farm": {"area_ha": f["area_ha"], "width_m": f["width_m"], "length_m": f["length_m"],
                 "pump_node": "PS", "source_node": "R0",
                 "irrigation_shifts": params["irrigation"]["open_configs"]},
        "nodes": nodes,
        "pipes": pipes,
        "sectors": sectors,
    }


def main() -> None:
    params = load_params()
    lay = layout_dict(params)
    out = HERE / "layout.json"
    out.write_text(json.dumps(lay, indent=1), encoding="utf-8")
    dash = ROOT / "dashboard" / "farm" / "layout.json"
    dash.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, dash)

    wn, _ = build_network(params)
    wntr.network.write_inpfile(wn, str(HERE / "farm.inp"))

    pdir = HERE / "perturbed"
    pdir.mkdir(exist_ok=True)
    base = params["leaks"]["base_seed"] + 100000  # disjoint from leak-dataset seeds
    for k in range(params["perturb"]["n_perturbed_models"]):
        wn_p, _ = build_network(params, seed=base + k)
        wntr.network.write_inpfile(wn_p, str(pdir / f"farm_p{k:02d}.inp"))
    print(f"layout: {len(lay['nodes'])} nodes, {len(lay['pipes'])} links, "
          f"{len(lay['sectors'])} sectors -> {out.relative_to(ROOT)}, {dash.relative_to(ROOT)}")
    print(f"models: farm.inp + {params['perturb']['n_perturbed_models']} perturbed in {pdir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
