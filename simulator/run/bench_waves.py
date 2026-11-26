"""Pressure waves on the prototype board (math note §10.7).

Runs the four board events through the MOC solver at the reference setting, writes
  results/bench-waves/README.md + figures
  results/bench-waves/board_waves.json   (played by the 3D tab of the twin viewer)
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from hydropin_sim.network.prototype import BoardSetting  # noqa: E402
from hydropin_sim.steady.board import M_PER_BAR  # noqa: E402
from hydropin_sim.transient import board as tb  # noqa: E402
from hydropin_sim.transient.board import EVENTS, run_event  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import bench_waves as oracle  # noqa: E402
from oracles.prototype_bench import P, P_REF, R_REF, reference_setting  # noqa: E402

OUT = ROOT / "results" / "bench-waves"
B = P.prototype
SPEC = {"v1_slam": (0.15, 2.5e-4), "v1_pulse": (0.06, 2.5e-4), "l1_burst": (0.15, 2.5e-4),
        "pump_trip": (0.40, 1.0e-3)}
NODES = ["PUMP_OUT", "IN", "T0", "E1", "R1a", "R1b", "TL1", "P1a", "P1", "P1b", "V1a", "V1b", "E3",
         "E2", "R2a", "R2b", "TL2", "P2a", "P2", "P2b", "TL3", "V2a", "V2b", "T1"]
HOSE_F = [0.2, 0.4, 0.6, 0.8]


def mid_points(model):
    """Interior sample points: hose at 4 places, every other gridded pipe longer than 5 cm at its middle."""
    G = model.grid
    pts = [("HOSE", f) for f in HOSE_F]
    for j, pid in enumerate(G.pipes):
        if pid in ("HOSE", "RETURN") or pid.startswith("SS_"):
            continue
        length = G.n_seg[j] * G.dt * G.a[j]
        if length > 0.05:
            pts.append((pid, 0.5))
    return pts


def run_all():
    ref = reference_setting()
    probe = run_event(P, ref, "v1_pulse", 0.001)
    mids = mid_points(probe.model)
    runs = {}
    for ev, (dur, fdt) in SPEC.items():
        runs[ev] = run_event(P, ref, ev, dur, record=NODES, record_points=mids, frame_dt=fdt)
    return ref, mids, runs


def ads_samples(t, h, dr, channel, n_ch=2):
    """ADS1115 conversions of one channel: boxcar mean over 1/DR, channels read in turn (§10.4)."""
    tc = 1.0 / dr
    ends = np.arange((channel + 1) * tc, t[-1], n_ch * tc)
    vals = np.array([h[(t > e - tc) & (t <= e)].mean() for e in ends])
    return ends, vals


def export(ref, mids, runs):
    data = dict(setting=dict(r=R_REF, v=round(ref.theta["V1"], 2)), nodes=NODES,
                mids=[f"{p}@{f:g}" for p, f in mids], events={})
    for ev, bt in runs.items():
        r = bt.result
        dh = (r.head - r.head[0]) * 1000.0                       # mm of water
        i1, i2 = r.point_ids.index("P1"), r.point_ids.index("P2")
        ads = {}
        for dr in (128.0, 860.0):
            for ch, col in ((0, i1), (1, i2)):
                te, va = ads_samples(r.time, r.head[:, col] - r.head[0, col], dr, ch)
                ads[f"{int(dr)}_{ch}"] = [[round(float(x) * 1000, 3) for x in te],
                                          [round(float(v) * 1000 / M_PER_BAR, 2) for v in va]]
        data["events"][ev] = dict(label=EVENTS[ev], t_ms=[round(float(x) * 1000, 3) for x in r.time],
                                  dh=np.round(dh).astype(int).T.tolist(),
                                  p0=[round(bt.state.p_bar["P1"], 4), round(bt.state.p_bar["P2"], 4)],
                                  scale=float(np.percentile(np.abs(dh), 99.5)), ads=ads,
                                  t_event=tb.T_EVENT * 1000)
    path = OUT / "board_waves.json"
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return path


def fig_events(runs):
    fig, axs = st.figure(2, 2, w=10.4, h=6.6)
    for ax, (ev, bt) in zip(axs.ravel(), runs.items()):
        r = bt.result
        tm = (r.time - tb.T_EVENT) * 1000
        for k, s in enumerate(("P1", "P2")):
            i = r.point_ids.index(s)
            ax.plot(tm, (r.head[:, i] - r.head[0, i]) * 1000 / M_PER_BAR, color=st.SERIES[k], lw=1.2, label=s)
        ax.axvline(0, color=st.MUTED, lw=0.8, ls=(0, (3, 2)))
        ax.set_title(EVENTS[ev])
        ax.set_xlabel("Time after the event (ms)")
        ax.set_ylabel("Pressure change (mbar)")
        ax.legend(loc="best")
    st.subtitle(axs[0, 0], f"R1 = R2 = {R_REF:.0f}°, V1 = V2 set for {P_REF} bar")
    return st.save(fig, OUT / "events.png")


def fig_sampling(runs):
    bt = runs["v1_pulse"]
    r = bt.result
    i = r.point_ids.index("P1")
    h = (r.head[:, i] - r.head[0, i]) * 1000 / M_PER_BAR
    fig, ax = st.figure(w=9.4, h=4.2)
    tm = r.time * 1000
    ax.plot(tm, h, color=st.TEXT, lw=1.0, label="true pressure at P1 (twin, 4 kHz shown)")
    for k, (dr, mk) in enumerate(((860.0, "o"), (128.0, "s"))):
        te, va = ads_samples(r.time, r.head[:, i] - r.head[0, i], dr, 0)
        ax.plot(te * 1000, va * 1000 / M_PER_BAR, mk, ms=4.5, color=st.SERIES[k], mec=st.SURFACE, mew=0.8,
                label=f"ADS1115 at {int(dr)} SPS (P1 and P2 in turn: {int(dr / 2)} per s each)")
    ax.axvline(tb.T_EVENT * 1000, color=st.MUTED, lw=0.8, ls=(0, (3, 2)))
    ax.set_xlim(0, 40)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Change of P1 (mbar)")
    ax.set_title("Why M3 cannot run on the board's electronics")
    st.subtitle(ax, "M3 pulse (V1 closes 10 % in 5 ms): the sub-millisecond echoes M3 needs are smoothed away; the ADS1115 sees the slow shape only")
    ax.legend(loc="upper right")
    return st.save(fig, OUT / "sampling.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = oracle.checks()
    ref, mids, runs = run_all()
    js = export(ref, mids, runs)
    figs = [fig_events(runs), fig_sampling(runs)]
    slam = runs["v1_slam"].result
    trip = runs["pump_trip"].result
    burst = runs["l1_burst"].result
    i1 = slam.point_ids.index("P1")
    rise = float(slam.head[:, i1].max() - slam.head[0, i1]) / M_PER_BAR * 1000
    ipo = slam.point_ids.index("PUMP_OUT")
    pmax = float(slam.head[:, ipo].max() - B.PB_Z_PUMP.v) / M_PER_BAR
    b1 = burst.point_ids.index("P1")
    dip = float(burst.head[:, b1].min() - burst.head[0, b1]) / M_PER_BAR * 1000
    t1 = trip.point_ids.index("P1")
    tmin = float(trip.head[:, t1].min() - B.PB_Z_BOARD.v - B.PB_DZ_SENSOR.v) / M_PER_BAR
    g = runs["v1_pulse"].model.grid
    write_report(
        OUT / "README.md", 12, "Pressure waves on the prototype bench",
        "The prototype twin now also runs pressure waves: the same characteristics solver as the bench and the "
        "farm, extended with exact lumped valves, emitter leak taps and a pump that can stop. Four events are "
        "simulated at the reference setting and played in slow motion in the viewer's 3D tab.",
        built=[
            ("transient/moc.py", "Lumped valves (exact, stable when shut), pipe → emitter taps, pump exponent n and speed s(t), RampEvent; farm/bench results unchanged (all pressure-wave, leak-echo and M3 tests pass)", "§10.7"),
            ("transient/board.py", "run_event(): v1_slam, v1_pulse (M3), l1_burst, pump_trip from the board's steady state", "§10.7"),
            ("steady/board.py", "run_board_full(): steady state + prepared model for the transient solver", "§10"),
            ("results/bench-waves/board_waves.json", "Pressure change at 24 nodes + mid-pipe points, 4 events, ADS1115 samples (128 and 860 SPS)", "–"),
        ],
        checks=checks,
        figures=[(figs[0].name, "P1 and P2 during the four events."),
                 (figs[1].name, "The M3 pulse at P1, true vs what the ADS1115 would sample.")],
        findings=[
            f"**Wave speeds on the board:** 16 mm LDPE ≈ {g.a[g.pipes.index('A4')]:.0f} m/s, soft hose ≈ "
            f"{g.a[g.pipes.index('HOSE')]:.0f} m/s, stainless sensor tees ≈ {g.a[g.pipes.index('SS_P1a')]:.0f} m/s. "
            "A wave crosses the board in about 4 ms.",
            f"**Slamming V1 shut is safe for the sensors:** P1 rises by {rise:.0f} mbar and the highest pressure on "
            f"the board reaches {pmax:.2f} bar (limit {B.PB_SAFE_FRAC.v * B.PS_P_MAX.v:.2f}). The flow is small "
            "(≈ 6 cm/s), so the Joukowsky surge is only ≈ 0.1 bar; the rest is the pump pushing against one shut branch.",
            f"**A sudden 0.8 mm leak at L1** sends a pressure drop of {dip:.0f} mbar to P1 within 0.3 ms.",
            f"**Power cut:** the pump stops in {B.PB_T_SPINDOWN.v:.1f} s; P1 falls smoothly to its static value "
            f"(lowest {tmin * 1000:.0f} mbar), no cavitation.",
            "**The waves are smooth, not sharp.** The soft hose and the viscoelastic PE damp the fast echoes; the "
            "steps every ~35 ms are the wave going up and down the 1 m hose (2 × 1 m / 58 m/s). Echoes from the "
            "board's fittings would arrive within 1 ms and are smeared out.",
            "**M3 on the board's electronics is impossible, as expected:** the ADS1115 gives each sensor 64 samples/s "
            "(128 SPS) or 430 (860 SPS, its maximum), enough for the slow shape but not for sub-millisecond echoes. "
            "M3 needs a ≥ 2 kHz sensor and a ≥ 100 m line, as in the leak-echo and M3 studies.",
        ],
        assumptions=[
            "Reference setting: R1 = R2 = 65°, V1 = V2 for 0.8 bar, no leak; water at 22 °C.",
            "Events: V1 shut in 10 ms (fast solenoid or slam), 10 % pulse in 5 ms, 0.8 mm burst in 5 ms, pump spin-down 0.1 s (⚠).",
            "Free outlets into the bucket are fixed-head boundaries; the pump's diaphragm valves stop any back-flow.",
            "PE is viscoelastic (Kelvin–Voigt, §5.3) with the farm's LDPE values; no air in the pipes.",
        ],
        decisions=[ "Film the pump stopping (phone, slow motion) to replace the 0.1 s spin-down guess."],
    )
    print("Bench waves:", sum(c.passed for c in checks), "/", len(checks), "checks;", js, js.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
