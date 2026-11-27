"""Report figures for the platform and farm sections (needs matplotlib: run in .venv-sim).

    python -m tools.report_figures

Writes report/figures/software_chain.png, farm_placement.png, farm_drone_route.png.
The farm figures read dashboard/farm/{placement,drone}.json and farm/model/layout.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "report" / "figures"
ACCENT, BLUE, GREY, INK = "#e4472a", "#1f6feb", "#9b9b95", "#151515"


def software_chain(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 3.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 40)
    ax.axis("off")

    def box(x, y, w, h, title, lines, color=INK, dashed=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    fc="white", ec=color, lw=1.4, ls="--" if dashed else "-"))
        ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=9, weight="bold", color=color)
        ax.text(x + w / 2, y + h - 6.2, "\n".join(lines), ha="center", va="top", fontsize=7, color=INK, linespacing=1.35)

    def arrow(x1, y1, x2, y2, label="", dy=1.4):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=10, lw=1.1, color=INK))
        if label:
            ax.text((x1 + x2) / 2, (y1 + y2) / 2 + dy, label, ha="center", fontsize=6.5, color="#444")

    box(1, 20, 17, 17, "ESP32 bench node", ["ADS1115: PT1, PT2", "Hall flow meter F0", "2 Hz, raw counts + values", "WiFi"])
    box(23, 20, 12, 17, "MQTT broker", ["amqtt / Mosquitto", "hydropin/bench", "status: LWT", "(laptop, LAN)"])
    box(40, 14, 25, 23, "Python backend (laptop)", ["FastAPI + paho-mqtt + SQLite", "validate -> store -> detect",
                                                     "quality gate, pump states,", "flow + M2 -> fusion -> state,",
                                                     "branch, tap, L/min, litres lost", "REST: runs, events, baseline,",
                                                     "CSV export, replay", "Telegram on LEAK / fault / resolved"], color=ACCENT)
    box(71, 22, 27, 15, "Dashboard: live mode", ["served by the laptop, /ws stream", "Bench, Scoreboard, Farm, M3,", "What's real tabs; run controls"])
    box(71, 2, 27, 15, "Dashboard: replay (GitHub Pages)", ["static HTML/JS, no build step", "recorded runs + scoreboard", "farm, placement, drone, M3 (sim)"], color=BLUE)
    box(40, 2, 25, 9, "Exports (same detector code)", ["replays/*.json, scoreboard.json"], dashed=True)
    box(1, 2, 34, 13, "Simulation side (marked 'simulation')", ["bench simulator (contract frames)", "WNTR virtual farm -> placement, M2/M1, drone",
                                                                     "M3 pressure-wave solver, TR / MFP / CNN"], color=GREY, dashed=True)
    arrow(18.5, 28.5, 22.6, 28.5, "MQTT")
    arrow(35.4, 28.5, 39.6, 28.5)
    arrow(65.4, 30, 70.6, 30)
    ax.text(68, 31.6, "/ws", ha="center", fontsize=6.5, color="#444")
    arrow(52.5, 13.6, 52.5, 11.4)
    arrow(65.4, 6.5, 70.6, 8)
    ax.text(68, 3.2, "Pages", ha="center", fontsize=6.5, color="#444")
    arrow(35.4, 8, 39.6, 7)
    ax.text(50, 39.5, "HydroPin software chain (bench rev 1)", ha="center", fontsize=10, weight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def placement(path: Path) -> None:
    d = json.loads((ROOT / "dashboard" / "farm" / "placement.json").read_text(encoding="utf-8"))
    s = d["sets"]
    n = [x["n"] for x in s]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.plot(n, [x["by_size"]["3"]["detected_pct"] for x in s], "-o", color=BLUE, ms=3, label="3 % leaks detected")
    ax.plot(n, [x["by_size"]["3"]["isolated_pct"] for x in s], "-o", color=ACCENT, ms=3, label="3 % leaks: right branch")
    ax.plot(n, [x["robust"]["by_size"]["3"]["isolated_pct"] for x in s], "--", color=ACCENT, lw=1,
            label="same, on 10 perturbed farms (overlaps)")
    ax.plot(n, [x["by_size"]["1"]["detected_pct"] for x in s], "-o", color=GREY, ms=3, label="1 % leaks detected")
    ax.set_xlabel("sensor nodes")
    ax.set_ylabel("% of simulated leaks")
    ax.set_ylim(0, 105)
    ax.set_xticks(n)
    ax.grid(alpha=0.3)
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(n, [f"{x['cost_dt'] / 1000:.1f}k" for x in s], fontsize=7)
    ax2.set_xlabel(f"kit cost, DT ({d['cost_per_node_dt']} DT per node, assumption)", fontsize=8)
    ax.axvline(d["recommended_n"], color=INK, lw=0.8, ls=":")
    ax.legend(fontsize=7, loc="center right")
    ax.set_title(f"Sensor placement, virtual 50 ha farm, k*sigma = {d['k']:g} x {d['sigma_bar'] * 1000:g} mbar - SIMULATION",
                 fontsize=8, pad=26)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def drone(path: Path) -> None:
    lay = json.loads((ROOT / "farm" / "model" / "layout.json").read_text(encoding="utf-8"))
    dr = json.loads((ROOT / "dashboard" / "farm" / "drone.json").read_text(encoding="utf-8"))
    nodes = {x["id"]: (x["x"], x["y"]) for x in lay["nodes"]}
    route = next(r for r in dr["routes"] if r["sensors_n"] == 6 and r["true_pipe_in_route"] and len(r["pipes"]) <= 4)
    fig, ax = plt.subplots(figsize=(5.2, 5.0))
    for sct in lay["sectors"]:
        x0, y0, x1, y1 = sct["bbox"]
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fc="#f1f1ee", ec="#d3d3ce", lw=0.8))
        ax.text((x0 + x1) / 2, y1 - 12, f"sector {sct['id']}", ha="center", fontsize=7, color=GREY)
    for p in lay["pipes"]:
        if p["kind"] == "pump":
            continue
        (xa, ya), (xb, yb) = nodes[p["from"]], nodes[p["to"]]
        lw = 2.4 if p["kind"] == "main" else 1.3
        ax.plot([xa, xb], [ya, yb], color="#2d2d2b", lw=lw, zorder=2)
    for pid in route["true_pipes"]:
        p = next(q for q in lay["pipes"] if q["id"] == pid)
        (xa, ya), (xb, yb) = nodes[p["from"]], nodes[p["to"]]
        ax.plot([xa, xb], [ya, yb], color=ACCENT, lw=4, alpha=0.5, zorder=3, label="true leak pipe")
    wx, wy = zip(*route["waypoints"])
    ax.plot(wx, wy, "-", color=BLUE, lw=1, zorder=4)
    ax.plot(wx, wy, ".", color=BLUE, ms=3, zorder=4, label="waypoints (10 m, 30 m altitude)")
    b = dr["base"]
    ax.plot([b["x"]], [b["y"]], "s", color=INK, ms=7, zorder=5, label="base (pump station)")
    ax.set_aspect("equal")
    ax.set_xlabel("m")
    ax.set_ylabel("m")
    ax.legend(fontsize=6.5, loc="lower right")
    ax.set_title(f"Drone route: {route['title']}\n{route['length_m']:.0f} m, {route['flight_s'] / 60:.1f} min, "
                 f"take-off {route['takeoff'].split(' ')[1]} - SIMULATION", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    software_chain(FIG / "software_chain.png")
    placement(FIG / "farm_placement.png")
    drone(FIG / "farm_drone_route.png")
    print("report/figures: software_chain.png, farm_placement.png, farm_drone_route.png")


if __name__ == "__main__":
    main()
