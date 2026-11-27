"""Report figure: the simulated farm (sectors, pipes, candidate sensor sites).

    python -m farm.model.plot_farm   ->  report/figures/farm_layout.png
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from farm.model.build_farm import HERE, load_params, run_steady, build_network  # noqa: E402
from farm.model.export_layout import layout_dict  # noqa: E402

ROOT = HERE.parent.parent


def main() -> None:
    params = load_params()
    lay = layout_dict(params)
    nodes = {n["id"]: n for n in lay["nodes"]}
    wn, _ = build_network(params, open_sectors=params["irrigation"]["open_configs"][0])
    pressure = run_steady(wn)["pressure_m"]

    fig, ax = plt.subplots(figsize=(7, 7.4))
    for s in lay["sectors"]:
        x0, y0, x1, y1 = s["bbox"]
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#e8f3e4",
                               edgecolor="#9bbf8f", lw=1))
        ax.text((x0 + x1) / 2, y1 - 22, f"Sector {s['id']}", ha="center", fontsize=9, color="#4b6b42")
    for p in lay["pipes"]:
        a, b = nodes[p["from"]], nodes[p["to"]]
        if p["kind"] == "pump":
            ax.plot([a["x"], b["x"]], [a["y"], b["y"]], color="#555", lw=1.5, ls=":")
            continue
        ax.plot([a["x"], b["x"]], [a["y"], b["y"]], color="#2d6fa3",
                lw=1 + 18 * p["diameter"], solid_capstyle="round")
    cand = [n for n in lay["nodes"] if n["candidate"]]
    ax.scatter([n["x"] for n in cand], [n["y"] for n in cand], s=46, marker="s",
               color="#e07b00", zorder=5, label=f"candidate sensor site ({len(cand)})")
    r0 = nodes["R0"]
    ax.scatter([r0["x"]], [r0["y"]], s=80, marker="v", color="#555", zorder=5, label="basin + pump")
    xm = params["farm"]["width_m"] / 2
    for n in cand:
        if n["kind"] == "main":
            xy, ha = (5, -12), "left"
        elif n["kind"] == "sector_head":
            xy, ha = ((-6, 5), "right") if n["x"] < xm else ((6, 5), "left")
        else:
            xy, ha = (4, 5), "left"
        ax.annotate(n["id"], (n["x"], n["y"]), xytext=xy, textcoords="offset points",
                    fontsize=7, ha=ha)
    ax.set_aspect("equal")
    ax.set_xlim(-20, params["farm"]["width_m"] + 20)
    ax.set_ylim(-60, params["farm"]["length_m"] + 20)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    p_ps = pressure["PS"] * 0.0980665
    ax.set_title(f"Simulated 50 ha drip farm (WNTR) – 6 sectors, 2 open per shift\n"
                 f"pump outlet {p_ps:.2f} bar at {params['pump']['design_flow_lps']:.0f} L/s design flow",
                 fontsize=10)
    ax.legend(loc="lower right", fontsize=8)
    ax.text(0.01, 0.01, "SIMULATION", transform=ax.transAxes, fontsize=8, color="#a00")
    out = ROOT / "report" / "figures" / "farm_layout.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"figure -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
