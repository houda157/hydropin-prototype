"""Leak echoes, unsteady friction and pipe creep, cavitation: figures + report."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from hydropin_sim.contracts import LeakSpec  # noqa: E402
from hydropin_sim.physics.waves import cavitation_head  # noqa: E402
from hydropin_sim.transient.moc import Options, run  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import leak_echoes as oracle  # noqa: E402
from oracles.leak_echoes import T0, X_LEAK  # noqa: E402
from oracles.transient_cases import L_RPV, P, close, rpv_spec, setup  # noqa: E402

OUT = ROOT / "results" / "leak-echoes"
G = 9.81


def echo_run(x_leak, closure=0.10, area=3e-6):
    spec = rpv_spec(h_res=25.0)
    leaks = [LeakSpec(pipe="P1", position=x_leak / L_RPV, area=area)]
    m, s = setup(spec, leaks, dt_max=2.5e-4)
    r = run(m, Options(duration=1.0, record=["END"]), [close(m, t_start=T0, closure=closure)])
    return m, s, r


def fig_echo():
    ml, sl, rl = oracle.partial_closure(True)
    mh, sh, rh = oracle.partial_closure(False)
    a = ml.grid.a[0]
    t = rl.time
    hh = np.interp(t, rh.time, rh.head[:, 0])
    fig, (a1, a2) = st.figure(2, 1, w=8.4, h=5.6, sharex=True)
    a1.plot(t, hh, color=st.SERIES[0], label="no leak")
    a1.plot(t, rl.head[:, 0], color=st.SERIES[1], label=f"leak at {X_LEAK:.0f} m ({sl.leak_flow[0] * 3.6e6:.0f} L/h)")
    a1.set_ylabel("Head at the valve (m)")
    a1.set_title("A leak sends back an echo")
    st.subtitle(a1, "Excitation valve closes by 10 % in one step at 0.05 s (small, safe pulse) · 150 m HDPE Ø63")
    a1.legend(loc="center right", bbox_to_anchor=(0.97, 0.45))
    d = (rl.head[:, 0] - hh) * 100
    t_arr = T0 + 2 * (L_RPV - X_LEAK) / a
    a2.axvline(t_arr, color=st.MUTED, lw=0.9, ls=(0, (3, 3)))
    a2.text(t_arr + 0.008, d[(t > T0 + 0.01) & (t < t_arr)].mean() - 0.5, f"predicted echo\nt₀ + 2(L − x_L)/a = {t_arr:.3f} s", fontsize=8,
            color=st.TEXT_2, va="bottom")
    a2.plot(t, d, color=st.SERIES[1])
    a2.set_ylabel("Leaky − healthy (cm)")
    a2.set_xlabel("Time (s)")
    a2.set_xlim(0, 0.95)
    win = (t > T0 + 0.01) & (t < T0 + 2 * L_RPV / a - 0.01)
    lo, hi = d[win].min(), d[win].max()
    a2.set_ylim(lo - 0.8, hi + 0.8)
    return st.save(fig, OUT / "echo.png")


def fig_positions():
    fig, ax = st.figure(w=8.4, h=4.2)
    for i, x in enumerate((30.0, 60.0, 90.0, 120.0)):
        m, s, r = echo_run(x)
        mh, sh, rh = echo_run(x, area=1e-14)
        a = m.grid.a[0]
        d = (r.head[:, 0] - rh.head[:, 0]) * 100
        d = d - d[np.argmin(np.abs(r.time - T0)) + 4]
        ax.plot(r.time, d, color=st.SERIES[i], label=f"leak at {x:.0f} m")
        t_arr = T0 + 2 * (L_RPV - x) / a
        ax.axvline(t_arr, color=st.SERIES[i], lw=0.8, ls=(0, (2, 3)), alpha=0.8)
    ax.set_xlim(0.06, 0.9)
    ax.set_ylim(-2.4, 0.6)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Echo at the valve (cm)")
    ax.set_title("The echo's arrival time says where the leak is")
    st.subtitle(ax, "Same leak size at four positions · dashed: predicted arrival 2(L − x_L)/a · basis of M3")
    ax.legend(loc="lower left", ncol=2)
    return st.save(fig, OUT / "positions.png")


def fig_damping():
    me, re_ = oracle.full_closure("qs")
    mu, ru = oracle.full_closure("uf")
    mv, rv = oracle.full_closure("ve")
    fig, ax = st.figure(w=8.4, h=4.2)
    for i, (r, name) in enumerate(((re_, "elastic pipe, quasi-steady friction"),
                                   (ru, "+ unsteady friction"),
                                   (rv, "+ PE creep (viscoelastic, placeholder J_k)"))):
        ax.plot(r.time, r.head[:, 0], color=st.SERIES[i], label=name, lw=1.3)
    ax.set_xlim(0, 9)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Head at the valve (m)")
    ax.set_title("Why plastic pipes swallow the wave")
    st.subtitle(ax, "Full closure in 10 ms · creep of the PE wall dissipates far more energy than friction")
    ax.legend(loc="upper right")
    return st.save(fig, OUT / "damping.png")


def fig_cavitation():
    closures = np.array([0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0])
    margins = []
    hv = cavitation_head(P.p_vap(20.0), P.water.P_ATM.v, P.water.RHO_W.v, G)
    for cfrac in closures:
        m, s = setup(rpv_spec(h_res=25.0), dt_max=5e-4)
        r = run(m, Options(duration=2.0, record=["END"]), [close(m, t_start=T0, closure=float(cfrac), t_close=0.01)],
                p_vap_head=hv)
        margins.append(r.meta["cavitation_margin"])
    margins = np.array(margins)
    fig, ax = st.figure(w=7.4, h=4.0)
    ax.axhspan(-12, 0, color="#f7e3e3", lw=0)
    ax.text(5, -1.2, "column separation (cavitation): unsafe for the pipe", fontsize=8.2, color=st.TEXT_2, va="top")
    ax.plot(closures * 100, margins, "o-", color=st.SERIES[0], markeredgecolor=st.SURFACE, markeredgewidth=1.5)
    ok = closures[margins > 0]
    ax.set_xlabel("Excitation: valve closure (% of its opening, in 10 ms)")
    ax.set_ylabel("Lowest head above vapour pressure (m)")
    ax.set_title("How big can the M3 pulse be?")
    st.subtitle(ax, f"Line at 2.5 bar · safe up to ≈ {ok.max() * 100:.0f} % closure with these placeholders")
    ax.set_ylim(min(margins.min() - 1, -3), margins.max() + 2)
    return st.save(fig, OUT / "cavitation.png"), closures, margins


def main():
    checks = oracle.checks()
    f1 = fig_echo()
    f2 = fig_positions()
    f3 = fig_damping()
    f4, closures, margins = fig_cavitation()
    me, re_ = oracle.full_closure("qs")
    mv, rv = oracle.full_closure("ve")
    write_report(
        OUT / "README.md", 5, "Leak echoes, unsteady friction and pipe creep",
        "The transient solver now contains the three effects that matter on a farm: the leak itself (an echo), "
        "the extra damping of unsteady friction, and the creep of plastic pipe walls. Each one is checked against "
        "theory, and the solver says how large the M3 pulse may safely be.",
        built=[
            ("transient/moc.py · leak nodes", "A leak is an emitter node inside the pipe (same as the steady twin)", "§5.6"),
            ("transient/moc.py · unsteady=True", "Brunone–Vardy unsteady friction, k₃ from the initial Reynolds number", "§5.4"),
            ("transient/moc.py · viscoelastic=True", "Generalised Kelvin–Voigt creep, exact exponential update, implicit in H_P", "§5.3"),
            ("transient/moc.py · p_vap_head", "Cavitation monitor: lowest head above vapour pressure over the whole run", "§5.6"),
        ],
        checks=checks,
        figures=[
            (f1.name, "The echo of a 3 mm² leak at 80 m after a small valve pulse, and its predicted arrival time."),
            (f2.name, "Echo arrival time for four leak positions."),
            (f3.name, "Damping: elastic pipe vs unsteady friction vs PE creep."),
            (f4.name, "Safe excitation size: cavitation margin vs valve closure."),
        ],
        findings=[
            "A leak of only **≈ 2 % of the flow** sends back a clear **≈ 1.6 cm** echo at exactly the predicted time **t₀ + 2(L − x_L)/a**. The amplitude matches small-signal theory within 7 %. The physical basis of M3 is confirmed in our own solver.",
            "**PE creep dominates damping.** With the placeholder creep values, the 4th oscillation keeps only 11 % of its amplitude (70 % for an elastic pipe). For M3 this means: use the **first echo**, measure close to the excitation, and **calibrate J_k, τ_k on the bench** (a leak-free test is enough).",
            "Unsteady friction adds a little damping (70 % → 67 %). Small but real; kept on for M3.",
            f"A full fast closure on a 2.5 bar line sends the down-surge **below vapour pressure** (cavitation risk). The pulse is safe up to ≈ **{closures[margins > 0].max() * 100:.0f} % closure** in 10 ms. M3 should use small partial closures (5–10 %), which still give clean echoes (figure 1).",
            "First run of oracle 5.4 failed: unsteady friction made damping *weaker*. Cause: the code used sgn(Q·∂Q/∂x) instead of the math note's sgn(Q)·|∂Q/∂x|. Fixed by following the note.",
        ],
        assumptions=[
            "PE100 creep parameters J_k, τ_k are order-of-magnitude placeholders (`verify`): the damping figure is qualitative until bench calibration.",
            "k₃ of unsteady friction from Vardy's C* at the initial Reynolds number (constant during the run).",
            "Leak = orifice (exponent 0.5) linearised by the solver at each step; no leak-area change with pressure (FAVAD m = 0).",
            "Cavitation is flagged, not simulated; a run with a flag is not used for M3 training.",
        ],
        decisions=[
            "Hardware team: plan a **partial** (5–10 %) fast closure for the M3 valve, not a full one.",
            "Bench protocol: one leak-free transient test first, to calibrate wave speed and PE creep.",
        ],
    )
    print(f"Leak echoes: {sum(c.passed for c in checks)}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
