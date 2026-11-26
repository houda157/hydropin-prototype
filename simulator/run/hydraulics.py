"""Reference networks and steady-state twin: figures + validation report."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from hydropin_sim.contracts import LeakSpec, Scenario  # noqa: E402
from hydropin_sim.network.builder import FIT_RANGE, build_wntr, write_inp  # noqa: E402
from hydropin_sim.network.generators import save_spec  # noqa: E402
from hydropin_sim.physics import emitters as em  # noqa: E402
from hydropin_sim.physics.leaks import leak_area_for_flow  # noqa: E402
from hydropin_sim.steady.solver import run_steady  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import hydraulics as oracle  # noqa: E402
from oracles.hydraulics import BENCH, FARM, P, scenario  # noqa: E402

OUT = ROOT / "results" / "hydraulics"
NET = ROOT / "config" / "networks"
BAR = 1 / 10.197
LATERAL_INK = "#dcdad3"


def _geometry(spec):
    xy = {n.id: (n.x, n.y) for n in spec.nodes}
    return xy


def _draw_laterals(ax, spec, color=LATERAL_INK, sectors_color=None):
    xy = _geometry(spec)
    sector_of = {b: s.id for s in spec.sectors for b in s.lateral_blocks}
    for lb in spec.lateral_blocks:
        x0, y0 = xy[lb.node]
        col = color if sectors_color is None else sectors_color.get(sector_of[lb.node], color)
        for k in range(lb.n_laterals):
            y = y0 + (k - (lb.n_laterals - 1) / 2) * 1.0
            ax.plot([x0 + 1.0, x0 + lb.lateral_length], [y, y], color=col, lw=0.5, zorder=1,
                    solid_capstyle="butt")


def fig_farm_map():
    fig, ax = st.figure(w=9.4, h=4.2)
    xy = _geometry(FARM)
    _draw_laterals(ax, FARM)
    mat_col = {"PVC": st.SERIES[0], "PE100": st.SERIES[1]}
    valve_pipes = {v.pipe for v in FARM.valves}
    for p in FARM.pipes:
        (x1, y1), (x2, y2) = xy[p.start], xy[p.end]
        ax.plot([x1, x2], [y1, y2], color=mat_col[p.material], lw=2.6 if p.material == "PVC" else 2.0,
                zorder=3, solid_capstyle="round")
        if p.id in valve_pipes:
            ax.plot([(x1 + x2) / 2], [(y1 + y2) / 2], marker="D", color=st.TEXT, markersize=5.5,
                    markeredgecolor=st.SURFACE, markeredgewidth=1.2, zorder=6)
    for pu in FARM.pumps:
        (x1, y1), (x2, y2) = xy[pu.start], xy[pu.end]
        ax.plot([x1, x2], [y1, y2], color=st.TEXT_2, lw=1.2, ls=(0, (2, 2)), zorder=2)
        st.dot(ax, x1, y1, st.TEXT, size=8)
        ax.annotate("basin + pump", (x1, y1), xytext=(0, -14), textcoords="offset points",
                    fontsize=8.2, color=st.TEXT_2, ha="center")
    for lb in FARM.lateral_blocks:
        st.dot(ax, *xy[lb.node], st.SERIES[2], size=7)
    for s in FARM.sectors:
        x0, y0 = xy[s.lateral_blocks[-1]]
        ax.text(x0 + 40, y0 + 8, s.id.title().replace("Sector", "Sector "), ha="center", fontsize=8.8,
                color=st.TEXT_2)
    handles = [Line2D([], [], color=st.SERIES[0], lw=2.6, label="Main · PVC Ø90 PN10"),
               Line2D([], [], color=st.SERIES[1], lw=2.0, label="Sub-mains · PE100 Ø75 SDR11"),
               Line2D([], [], color=LATERAL_INK, lw=1.2, label="Laterals · Ø16, 80 m (drawn, not modelled)"),
               Line2D([], [], marker="o", color=st.SERIES[2], lw=0, markersize=7, label="Lateral block (1 node = 10 laterals)"),
               Line2D([], [], marker="D", color=st.TEXT, lw=0, markersize=5.5, label="Sector valve")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    ax.set_aspect("equal")
    ax.set_xlim(-18, 385)
    ax.set_ylim(-12, 48)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title("Demo drip farm (placeholder until the pilot farm survey)")
    st.subtitle(ax, FARM.description)
    return st.save(fig, OUT / "farm_map.png")


def fig_pressure_map(res):
    fig, ax = st.figure(w=9.4, h=3.3)
    xy = _geometry(FARM)
    ix = {n: i for i, n in enumerate(res.node_ids)}
    opens = {"SECTOR1", "SECTOR3"}
    _draw_laterals(ax, FARM, sectors_color={s.id: ("#c9dcf3" if s.id in opens else "#ecebe7")
                                            for s in FARM.sectors})
    for p in FARM.pipes:
        (x1, y1), (x2, y2) = xy[p.start], xy[p.end]
        ax.plot([x1, x2], [y1, y2], color="#b9b8b2", lw=1.6, zorder=2)
    open_nodes = [n for n in FARM.nodes if n.kind.value != "source"]
    pb = np.array([res.pressure[0, ix[n.id]] * BAR for n in open_nodes])
    vmin, vmax = 1.2, 1.6
    closed = {b for s in FARM.sectors if s.id not in opens for b in [*s.lateral_blocks, f"S{s.id[-1]}"]}
    pts_open = [(n, v) for n, v in zip(open_nodes, pb) if n.id not in closed]
    pts_closed = [n for n in open_nodes if n.id in closed]
    sc = ax.scatter([xy[n.id][0] for n, _ in pts_open], [xy[n.id][1] for n, _ in pts_open],
                    c=[v for _, v in pts_open], cmap=st.SEQ_CMAP, vmin=vmin, vmax=vmax, s=70, zorder=5,
                    edgecolors=st.SURFACE, linewidths=1.5)
    ax.scatter([xy[n.id][0] for n in pts_closed], [xy[n.id][1] for n in pts_closed], color="#d6d5cf",
               s=55, zorder=5, edgecolors=st.SURFACE, linewidths=1.5)
    for s in FARM.sectors:
        x0, y0 = xy[s.lateral_blocks[-1]]
        txt = "open" if s.id in opens else "closed"
        ax.text(x0 + 40, y0 + 8, f"{s.id.title().replace('Sector', 'Sector ')} · {txt}", ha="center",
                fontsize=8.8, color=st.TEXT_2 if txt == "open" else st.MUTED)
    cb = fig.colorbar(sc, cax=ax.inset_axes([1.01, 0.05, 0.015, 0.9]))
    cb.set_label("Pressure (bar)", color=st.TEXT_2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=st.TEXT_2, labelsize=8)
    ax.set_aspect("equal")
    ax.set_xlim(-18, 385)
    ax.set_ylim(-12, 48)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    q = res.pump_flow[0] * 1000
    ax.set_title("Steady state, irrigation shift with sectors 1 and 3 open")
    st.subtitle(ax, f"Pump {q:.2f} L/s · block pressures {min(v for _, v in pts_open if True):.2f}–"
                    f"{max(v for _, v in pts_open):.2f} bar · closed sectors drain to ≈ 0")
    return st.save(fig, OUT / "pressure_map.png")


def fig_bench():
    healthy = run_steady(BENCH, Scenario(id="h", network="bench", seed=0, open_sectors=[], duration=1,
                                         timestep=1), P)
    ixh = {n: i for i, n in enumerate(healthy.node_ids)}
    q0 = healthy.pump_flow[0]
    area = leak_area_for_flow(0.05 * q0, healthy.pressure[0, ixh["B80"]], P.leaks.CD_LEAK.v)
    leaky = run_steady(BENCH, Scenario(id="l", network="bench", seed=0, open_sectors=[], duration=1, timestep=1,
                                       leaks=[LeakSpec(pipe="L2", position=1.0, area=float(area))]), P)
    ixl = {n: i for i, n in enumerate(leaky.node_ids)}
    order = ["B0", "B40", "B80", "B120", "END"]
    x = np.array([0, 40, 80, 120, 150])
    ph = np.array([healthy.pressure[0, ixh[n]] for n in order])
    pl = np.array([leaky.pressure[0, ixl[n]] for n in order])
    fig, (a1, a2) = st.figure(1, 2, w=9.4, h=3.9)
    a1.plot(x, ph * BAR, color=st.SERIES[0], marker="o", markeredgecolor=st.SURFACE, markeredgewidth=1.5,
            label="no leak")
    a1.plot(x, pl * BAR, color=st.SERIES[1], marker="o", markeredgecolor=st.SURFACE, markeredgewidth=1.5,
            label="leak = 5 % of flow at 80 m")
    a1.axvline(80, color=st.MUTED, lw=0.8, ls=(0, (3, 3)))
    a1.set_xlabel("Position along the bench (m)")
    a1.set_ylabel("Pressure (bar)")
    a1.set_title("Bench pressure profile")
    st.subtitle(a1, f"150 m HDPE Ø63 · pump {q0 * 1000:.2f} L/s → {leaky.pump_flow[0] * 1000:.2f} L/s with the leak")
    a1.legend(loc="lower left")
    diff = (pl - ph) * 100   # cm of water
    a2.axhline(0, color=st.GRID, lw=0.8)
    a2.plot(x, diff, color=st.SERIES[1], marker="o", markeredgecolor=st.SURFACE, markeredgewidth=1.5)
    for xi, di in zip(x, diff):
        a2.annotate(f"{di:.0f} cm", (xi, di), xytext=(0, -13), textcoords="offset points", ha="center",
                    fontsize=8, color=st.TEXT_2)
    a2.axvline(80, color=st.MUTED, lw=0.8, ls=(0, (3, 3)))
    a2.text(82, diff.max() * 0.15, "leak", fontsize=8.2, color=st.TEXT_2)
    a2.set_xlabel("Position along the bench (m)")
    a2.set_ylabel("Pressure change (cm of water)")
    a2.set_ylim(diff.min() * 1.35, max(diff.max(), 0) + 10)
    a2.set_title("Leak signature")
    st.subtitle(a2, "Change caused by the leak (leaky − healthy)")
    return st.save(fig, OUT / "bench.png"), q0, leaky.pump_flow[0], diff


def fig_aggregation():
    fig, ax = st.figure(w=7.4, h=4.1)
    h = np.linspace(*FIT_RANGE, 60)
    eps, nu = P.material("LDPE").EPS_R.v, P.nu_w()
    q_eq = np.array([em.lateral_equivalent_flow(hi, 200, 0.4, 0.0136, eps, nu, oracle.dripper, slope=-0.003)
                     for hi in h])
    wn, info = build_wntr(FARM, P)
    fit = next(iter(info.block_fits.values()))
    lh = 3.6e6
    ax.plot(h * BAR, q_eq * lh, color=st.SERIES[0], label="Equivalent lateral (math note §2.4)")
    ax.plot(h * BAR, fit.c_lateral * np.sqrt(h) * lh, color=st.SERIES[1], ls=(0, (4, 3)),
            label=f"Emitter used in EPANET: C√h (max error {fit.max_rel_error * 100:.1f} %)")
    hs = np.array([6, 10, 15, 20, 25.0])
    q_ep = np.array([oracle.explicit_lateral_wntr(float(hi), -0.003) for hi in hs])
    for hi, qi in zip(hs, q_ep):
        st.dot(ax, hi * BAR, qi * lh, st.SERIES[2], size=7.5)
    ax.plot([], [], "o", color=st.SERIES[2], label="200 drippers solved one by one by EPANET")
    ax.set_xlabel("Pressure at the lateral inlet (bar)")
    ax.set_ylabel("Lateral inflow (L/h)")
    ax.set_title("One node per lateral block: is the reduction faithful?")
    st.subtitle(ax, "80 m Ø16 lateral, 200 drippers of 2 L/h, 0.3 % uphill")
    ax.legend(loc="upper left")
    return st.save(fig, OUT / "aggregation.png"), fit


def fig_pump():
    fig, ax = st.figure(w=7.4, h=4.1)
    pu = FARM.pumps[0]
    q = np.linspace(0, (pu.h0 / pu.r) ** 0.5, 200)
    ax.plot(q * 1000, (pu.h0 - pu.r * q ** 2) * BAR, color=st.SERIES[0], label="Pump curve")
    shifts = [("1 sector", ["SECTOR1"]), ("2 sectors", ["SECTOR1", "SECTOR3"]),
              ("3 sectors", ["SECTOR1", "SECTOR2", "SECTOR3"]), ("4 sectors", [f"SECTOR{k}" for k in range(1, 5)])]
    pts = []
    for name, opens in shifts:
        r = run_steady(FARM, scenario(opens, sid=name), P)
        ix = {n: i for i, n in enumerate(r.node_ids)}
        blocks = [b for s in FARM.sectors if s.id in opens for b in s.lateral_blocks]
        pb = np.mean([r.pressure[0, ix[b]] for b in blocks]) * BAR
        qq = r.pump_flow[0]
        hh = pu.h0 - pu.r * qq ** 2
        st.dot(ax, qq * 1000, hh * BAR, st.SERIES[1], size=8)
        off, ha = ((-10, -24), "right") if name == "4 sectors" else ((8, 4), "left")
        ax.annotate(f"{name}\nblocks at {pb:.2f} bar", (qq * 1000, hh * BAR), xytext=off,
                    textcoords="offset points", fontsize=8, color=st.TEXT_2, ha=ha)
        pts.append((name, qq, pb))
    ax.set_xlim(0, q[-1] * 1000 * 1.05)
    ax.set_ylim(0, pu.h0 * BAR * 1.1)
    ax.set_xlabel("Pump flow (L/s)")
    ax.set_ylabel("Pump head (bar)")
    ax.set_title("Where the pump works for each irrigation shift")
    st.subtitle(ax, "Opening more sectors moves the pump down its curve and lowers every pressure")
    return st.save(fig, OUT / "pump.png"), pts


def main():
    save_spec(BENCH, NET / "bench.yaml")
    save_spec(FARM, NET / "farm_demo.yaml")
    write_inp(build_wntr(BENCH, P)[0], NET / "bench.inp")
    write_inp(build_wntr(FARM, P)[0], NET / "farm_demo.inp")
    checks = oracle.checks()
    res = run_steady(FARM, scenario(), P)
    f1 = fig_farm_map()
    f2 = fig_pressure_map(res)
    f3, q0, q1, diff = fig_bench()
    f4, fit = fig_aggregation()
    f5, pts = fig_pump()
    ix = {n: i for i, n in enumerate(res.node_ids)}
    write_report(
        OUT / "README.md", 2, "Networks and steady-state twin",
        "The test bench and a demo drip farm are described as validated network files, turned into EPANET "
        "models (Darcy–Weisbach, one node per lateral block) and solved. Results are checked against our "
        "own physics, an independent dripper-by-dripper model and conservation laws.",
        built=[
            ("network/generators.py", "Bench placeholder (150 m HDPE Ø63) and parametric demo farm; YAML save/load", "§1"),
            ("network/builder.py", "NetworkSpec → EPANET model: D-W, viscosity from temperature, lateral-block emitter fit, pump curve, .inp export", "§2.1–2.6"),
            ("steady/solver.py", "Runs a Scenario: open/closed sectors, leaks (pipe split + orifice), clogging, roughness/elevation draws → SteadyResult", "§2, §2.9"),
            ("config/networks/", "bench.yaml, farm_demo.yaml and their EPANET .inp files (open them in EPANET to inspect)", "–"),
            ("contracts.py", "Added optional `Node.outlet_coeff` (fixed outlet, e.g. bench flush valve), allowed by the contract rule", "–"),
        ],
        checks=checks,
        figures=[
            (f1.name, "The demo farm: PVC main, one PE sub-main per sector behind a valve, three lateral blocks per sector."),
            (f2.name, "Pressures computed by the twin for a shift with sectors 1 and 3 open."),
            (f3.name, "Bench: a leak of 5 % of the flow at 80 m, seen by pressure sensors at the junctions."),
            (f4.name, "Check of decision D2: the one-node lateral block against 200 drippers solved individually."),
            (f5.name, "Pump operating points for shifts of 1 to 4 sectors."),
        ],
        findings=[
            "EPANET and our own Darcy–Weisbach agree within **0.05 %** on a single pipe and within **0.06 %** on every turbulent pipe of the farm. The two code paths can be trusted to describe the same physics.",
            f"The one-node lateral block stays within **{fit.max_rel_error * 100:.1f} %** of the equivalent-lateral law over 0.6–2.5 bar, and within **0.2 %** of 200 drippers solved one by one.",
            f"On the bench, a leak of 5 % of the flow at 80 m raises the pump flow from {q0 * 1000:.2f} to {q1 * 1000:.2f} L/s and lowers every pressure by **{abs(diff).min():.0f}–{abs(diff).max():.0f} cm of water**: easy to detect (≈ 3× the ±25 cm sensor accuracy). But most of that drop is the pump sliding down its curve and is the same everywhere. The part that points to the leak, the difference between sensors, is only **≈ {abs(diff).max() - abs(diff).min():.0f} cm**, below sensor accuracy. Steady-state pressure **detects** well but **localises** poorly on a single line, which is exactly why M3 exists.",
            f"With this placeholder pump, block pressures range from ≈ {min(p[2] for p in pts):.1f} to ≈ {max(p[2] for p in pts):.1f} bar depending on how many sectors are open. The **irrigation shift is a major state of the network**, which confirms that M2 needs one 'normal' per shift (math note §4.1).",
            "Closed sectors drain through their drippers, so their sensors read ≈ 0. A sensor reading near zero in a closed sector is normal, not a leak.",
        ],
        assumptions=[
            "Bench and farm geometry, pump curves and terrain slopes are placeholders (Architecture D3).",
            "Laterals: 80 m Ø16 with 2 L/h non-compensating drippers every 0.4 m. PC drippers are not a power law and are not supported by the EPANET twin yet.",
            f"Lateral-block emitter fitted over {FIT_RANGE[0]:.0f}–{FIT_RANGE[1]:.0f} m. Outside that range the fit error grows; checked automatically.",
            "Leaks are orifices (N₁ = 0.5): EPANET has one global emitter exponent (math note §2.4 warning).",
            "Sector valves are ideal on/off links with K = 2 minor loss when open.",
        ],
        decisions=[
            "Hardware team: send the real bench layout (lengths, tees, leak-valve and sensor positions, pump or tank).",
            "Pilot farm: survey of the main, sub-mains, sectors and typical shifts as soon as possible, to replace the demo farm.",
        ],
    )
    n_ok = sum(c.passed for c in checks)
    print(f"Hydraulics: {n_ok}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
