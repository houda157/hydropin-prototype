"""Twin of the 3rd-phase prototype board and its real measurement chain.

Figures + report in results/prototype-bench/. Math note §10.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402

from hydropin_sim.network import prototype as pb  # noqa: E402
from hydropin_sim.network.prototype import BoardSetting, board_spec  # noqa: E402
from hydropin_sim.sensors import board as sb  # noqa: E402
from hydropin_sim.steady.board import LPM, M_PER_BAR, end_valve_angle_for, run_board  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import prototype_bench as oracle  # noqa: E402
from oracles.prototype_bench import P, P_REF, R_REF, reference_setting  # noqa: E402

OUT = ROOT / "results" / "prototype-bench"
B = P.prototype
KAPPA = P.decision.KAPPA.v
TAP_COL = {"L1": st.SERIES[0], "L2": st.SERIES[1], "L3": st.SERIES[2]}


def with_leak(base, **leak_d):
    return BoardSetting(theta=dict(base.theta), leak_d=leak_d)


# ════════════════════════════════════════════════════════════════════════════
# Recording simulator (what the ESP32 would publish)
# ════════════════════════════════════════════════════════════════════════════

def quiet_params(**off):
    """Copy of the parameters with some disturbances switched off (for the noise budget)."""
    Q = P.model_copy(deep=True)
    for name in off:
        getattr(Q.prototype, name).value = 0.0
    return Q


def record(Pr, schedule, duration, seed, wander_moves_pressure=True):
    """wander_moves_pressure=False keeps the supply wander only in the pump speed seen by
    the ripple phase (used to isolate the ripple in the noise budget)."""
    rng = np.random.default_rng(seed)
    segs = sb.timeline(Pr, schedule)
    if not wander_moves_pressure:
        for sg in segs:
            sg.sens = {k: 0.0 for k in sg.sens}
    tf = np.arange(0, duration + 1, 0.05)
    if Pr.prototype.PB_SIGMA_V.v > 0:
        sdev = sb.ou_process(tf, Pr.prototype.PB_SIGMA_V.v, Pr.prototype.PB_TAU_V.v, rng)
    else:
        sdev = np.zeros_like(tf)

    def s_fun(t):
        return np.interp(t, tf, sdev)

    pub = {}
    for ch, s in enumerate(("P1", "P2")):
        chain = sb.PressureChain.create(s, Pr, rng, channel=ch)
        te = sb.conversion_times(duration, Pr, ch)
        raw = chain.read(segs, te, s_fun(te), Pr, rng, with_ripple=Pr.prototype.PB_RIPPLE_M.v > 0)
        pub[s] = sb.firmware_average(raw, Pr)
        pub[s + "_raw"] = raw
    fm = sb.HallFlowMeter.create(Pr, np.random.default_rng(seed + 100))
    pub["F0_fw"] = fm.read(segs, duration, s_fun, Pr, np.random.default_rng(seed + 1))
    pub["F0_cal"] = fm.read(segs, duration, s_fun, Pr, np.random.default_rng(seed + 1),
                            k_fw=fm.k_dev, f0_fw=fm.f_off)
    pub["segs"] = segs
    return pub


def change_sigma(x, n):
    """σ of the change between two consecutive windows of n published values."""
    m = len(x) // n
    blocks = np.asarray(x[: m * n]).reshape(m, n).mean(axis=1)
    return float(np.std(np.diff(blocks)))


# ════════════════════════════════════════════════════════════════════════════
# Figures
# ════════════════════════════════════════════════════════════════════════════

def fig_board(ref):
    stt = run_board(P, with_leak(ref, L1=0.5e-3))
    spec, _ = board_spec(P, with_leak(ref, L1=0.5e-3))
    nodes = {n.id: n for n in spec.nodes}
    fig, ax = st.figure(w=9.2, h=5.6)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).FancyBboxPatch(
        (0, 0), 60, 40, boxstyle="round,pad=0,rounding_size=1.2", fc="#f3ece0", ec="#e2d6c1", lw=1.0, zorder=0))
    norm = Normalize(0.0, 1.0)
    segs, cols = [], []
    for p in spec.pipes:
        a, b = nodes[p.start], nodes[p.end]
        if not (0 <= a.x <= 0.6 and 0 <= b.x <= 0.6 and -0.01 <= a.y and -0.01 <= b.y) or p.id == "HOSE":
            continue
        pa = stt.pressure.get(p.start, 0.0) / M_PER_BAR
        pe = stt.pressure.get(p.end, 0.0) / M_PER_BAR
        if p.id.startswith("TAP") or p.id == "RETURN":
            xb, yb = a.x, a.y - (0.06 if p.id.startswith("TAP") else 0.07)
            segs.append([(a.x * 100, a.y * 100), (xb * 100, yb * 100)])
        else:
            segs.append([(a.x * 100, a.y * 100), (b.x * 100, b.y * 100)])
        cols.append(0.5 * (pa + pe))
    lc = LineCollection(segs, cmap=st.SEQ_CMAP, norm=norm, linewidths=7, capstyle="round", zorder=2)
    lc.set_array(np.array(cols))
    ax.add_collection(lc)
    cb = fig.colorbar(lc, ax=ax, shrink=0.75, pad=0.02)
    cb.set_label("Pressure in the pipe (bar)", color=st.TEXT_2)
    cb.outline.set_visible(False)

    def lab(nid, text, dx=0, dy=3.2, ha="center", color=st.TEXT_2, weight="normal"):
        x, y = pb.XY[nid]
        ax.text(x * 100 + dx, y * 100 + dy, text, ha=ha, va="center", fontsize=8.3, color=color,
                fontweight=weight, zorder=6)

    for v in pb.VALVES:
        x, y = pb.XY[v]
        ax.plot([x * 100], [y * 100], marker="D", ms=8, color=st.TEXT_2, mec=st.SURFACE, mew=1.5, zorder=5)
        lab(v, f"{v} {ref.theta[v]:.0f}°", dy=-3.4)
    for s in ("P1", "P2"):
        x, y = pb.XY[s]
        ax.plot([x * 100, x * 100], [y * 100, y * 100 + 7], color="#b9c3cc", lw=5, zorder=3, solid_capstyle="round")
        ax.plot([x * 100], [y * 100 + 7], "s", ms=10, color=st.TEXT, zorder=5)
        ax.text(x * 100 + 1.8, y * 100 + 7, f"{s}  {stt.p_bar[s]:.3f} bar", fontsize=8.6, color=st.TEXT,
                fontweight="bold", va="center", zorder=6)
    for t in pb.TAPS:
        x, y = pb.XY["T" + t]
        on = stt.q_out[t] > 0
        st.dot(ax, x * 100, y * 100 - 6, st.CRITICAL if on else st.MUTED, size=7)
        txt = f"{t}  leak {stt.q_out[t] * LPM:.2f} L/min" if on else f"{t} shut"
        ax.text(x * 100 + 1.4, y * 100 - 6 - (0 if t == "L1" else 1.6), txt, fontsize=8,
                va="center" if t == "L1" else "top", ha="left", color=st.CRITICAL if on else st.MUTED, zorder=6)
    xi, yi = pb.XY["IN"]
    ax.plot([xi * 100 + 2, 20], [yi * 100, yi * 100], color="#c99a2e", lw=11, solid_capstyle="butt", zorder=4)
    ax.text(16.5, yi * 100 + 3.3, f"F0  {stt.q_f0 * LPM:.2f} L/min", ha="center", fontsize=8.6, color=st.TEXT,
            fontweight="bold")
    ax.annotate("", xy=(xi * 100, yi * 100), xytext=(-9, yi * 100), arrowprops=dict(arrowstyle="-|>", color=st.TEXT_2, lw=1.4))
    ax.text(-9.5, yi * 100, f"R365 pump\n{B.PB_V_SUPPLY.v:.0f} V, 1 m hose", ha="right", va="center", fontsize=8, color=st.TEXT_2)
    x1, y1 = pb.XY["T1"]
    ax.text(x1 * 100 + 1.5, 2.0, f"return\n{stt.q_out['RET'] * LPM:.2f} L/min", fontsize=8, color=st.TEXT_2, va="bottom")
    ax.set_xlim(-24, 66)
    ax.set_ylim(-4, 44)
    ax.set_xticks([0, 10, 20, 30, 40, 50, 60])
    ax.set_yticks([0, 10, 20, 30, 40])
    ax.set_xlabel("Board x (cm)")
    ax.set_ylabel("Board y (cm)")
    ax.set_title("The prototype board as the twin sees it (L1 open with a 0.5 mm orifice)")
    st.subtitle(ax, f"60 × 40 cm board lying on the table, R1 = R2 = {R_REF:.0f}°, V1 = V2 set for {P_REF} bar; "
                    "every tee, elbow, valve and sensor tee is a modelled loss")
    return st.save(fig, OUT / "board.png")


def fig_operating(ref):
    angles = np.linspace(0, B.THETA_CLOSED.v - 0.3, 46)
    fig, axs = st.figure(1, 2, w=10.0, h=4.2)
    for i, r in enumerate((45.0, R_REF)):
        p, q = [], []
        for a in angles:
            s = run_board(P, BoardSetting(theta={"R1": r, "R2": r, "V1": a, "V2": a}))
            p.append(np.mean(list(s.p_bar.values())))
            q.append(s.q_f0 * LPM)
        axs[0].plot(angles, p, color=st.SERIES[i], label=f"R1 = R2 = {r:.0f}°")
        axs[1].plot(angles, q, color=st.SERIES[i], label=f"R1 = R2 = {r:.0f}°")
        st.end_label(axs[0], angles[-1], p[-1], f"R {r:.0f}°", dy=6 if i == 0 else -6)
    lim = B.PB_SAFE_FRAC.v * B.PS_P_MAX.v
    axs[0].axhline(lim, color=st.CRITICAL, lw=1.0, ls=(0, (4, 3)))
    axs[0].text(2, lim + 0.03, f"safe limit {lim:.2f} bar (90 % of the sensors' 1.6 bar)", fontsize=8, color=st.TEXT_2)
    a_ref = ref.theta["V1"]
    s_ref = run_board(P, ref)
    st.dot(axs[0], a_ref, np.mean(list(s_ref.p_bar.values())), st.TEXT)
    axs[0].annotate(f"working point\nV = {a_ref:.1f}°", (a_ref, np.mean(list(s_ref.p_bar.values()))),
                    xytext=(-62, 18), textcoords="offset points", fontsize=8, color=st.TEXT_2,
                    arrowprops=dict(arrowstyle="-", color=st.MUTED, lw=0.8))
    axs[1].axhline(1.0, color=st.MUTED, lw=1.0, ls=(0, (2, 2)))
    axs[1].text(2, 1.03, "flow sensor's rated minimum (1 L/min)", fontsize=8, color=st.TEXT_2)
    axs[0].set_ylim(-0.1, 1.6)
    axs[0].set_xlabel("End valves V1 and V2, closing angle (°)")
    axs[1].set_xlabel("End valves V1 and V2, closing angle (°)")
    axs[0].set_ylabel("Mean of P1 and P2 (bar)")
    axs[1].set_ylabel("Flow through F0 (L/min)")
    axs[0].set_title("Pressure only builds up in the last 15° before shut-off")
    st.subtitle(axs[0], "R365 at 12 V, taps shut")
    axs[1].set_title("Flow at the sensors")
    st.subtitle(axs[1], "the board runs near the bottom of the Hall sensor's range")
    axs[1].legend(loc="center left")
    return st.save(fig, OUT / "operating.png")


def leak_sweep(ref, diam):
    s0 = run_board(P, ref)
    out = {}
    for t in pb.TAPS:
        rows = []
        for d in diam:
            s = run_board(P, with_leak(ref, **{t: d}))
            rows.append((s.q_leak / s0.q_f0 * 100, (s.p_bar["P1"] - s0.p_bar["P1"]) * 1e3,
                         (s.p_bar["P2"] - s0.p_bar["P2"]) * 1e3, (s.q_f0 - s0.q_f0) * LPM, s.q_leak * LPM))
        out[t] = np.array(rows)
    return s0, out


def fig_signatures(sweep, sig):
    _, out = sweep
    fig, axs = st.figure(1, 2, w=10.0, h=4.5)
    ax = axs[0]
    for t in pb.TAPS:
        r = out[t]
        ls = (0, (4, 3)) if t == "L3" else "-"
        ax.plot(r[:, 1], r[:, 2], color=TAP_COL[t], ls=ls, label=t, marker="o", ms=4,
                mec=st.SURFACE, mew=1.0)
    lim = min(out["L1"][:, 1].min(), out["L2"][:, 2].min()) * 1.05
    ax.plot([0, lim], [0, lim], color=st.MUTED, lw=0.8, ls=(0, (2, 2)))
    ax.text(lim * 0.55, lim * 0.62, "equal drop", rotation=45, fontsize=8, color=st.MUTED)
    th = np.linspace(0, 2 * np.pi, 100)
    rad = KAPPA * sig["P_1s"] * 1e3
    ax.fill(rad * np.cos(th), rad * np.sin(th), color=st.BAND, zorder=0)
    ax.annotate(f"3σ of a 1-s reading = {rad:.1f} mbar", (0, 0), xytext=(-150, -12), textcoords="offset points",
                fontsize=7.8, color=st.TEXT_2, arrowprops=dict(arrowstyle="-", color=st.MUTED, lw=0.8))
    ax.set_xlabel("Change of P1 (mbar)")
    ax.set_ylabel("Change of P2 (mbar)")
    ax.set_title("Which tap? L2 and L3 look the same")
    st.subtitle(ax, "orifice 0.01 → 1.2 mm at the end of each tap tube")
    ax.legend(loc="lower right")
    ax = axs[1]
    for t in pb.TAPS:
        r = out[t]
        ax.plot(r[:, 0], r[:, 3], color=TAP_COL[t], ls=(0, (4, 3)) if t == "L3" else "-", label=t)
    ax.plot(out["L1"][:, 0], out["L1"][:, 0] / 100 * sweep[0].q_f0 * LPM, color=st.MUTED, lw=1.0,
            ls=(0, (2, 2)))
    ax.text(out["L1"][-1, 0] * 0.45, out["L1"][-1, 0] * 0.45 / 100 * sweep[0].q_f0 * LPM + 0.045,
            "leak flow itself", fontsize=8, color=st.MUTED)
    ax.axhline(KAPPA * sig["F_cal_10s"] * LPM, color=st.TEXT_2, lw=0.9, ls=(0, (4, 3)))
    ax.text(1, KAPPA * sig["F_cal_10s"] * LPM + 0.008, "3σ of F0 (calibrated, 10 s mean)", fontsize=8,
            color=st.TEXT_2)
    ax.set_xlabel("Leak flow (% of the healthy flow)")
    ax.set_ylabel("Increase of F0 (L/min)")
    ax.set_title("F0 sees only part of the leak")
    st.subtitle(ax, "the pump slides down its curve: less head, so less return flow")
    return st.save(fig, OUT / "signatures.png")


def fig_recording(rec, t_leak):
    fig, axs = st.figure(2, 1, w=9.4, h=6.4, sharex=True)
    ax = axs[0]
    segs = rec["segs"]
    for i, s in enumerate(("P1", "P2")):
        pub = rec[s]
        ax.plot(pub.time, pub.value / M_PER_BAR, color=st.SERIES[i], lw=1.0, label=f"{s} as published (1 s mean)")
        tt = np.array([0, t_leak, t_leak, pub.time[-1]])
        tv = [segs[0].state.p_bar[s], segs[0].state.p_bar[s], segs[1].state.p_bar[s], segs[1].state.p_bar[s]]
        ax.plot(tt, tv, color=st.TEXT, lw=0.9, ls=(0, (3, 2)))
        st.end_label(ax, pub.time[-1], pub.value[-30:].mean() / M_PER_BAR, s)
    ax.axvline(t_leak, color=st.CRITICAL, lw=0.9)
    ax.text(t_leak + 3, 0.80, "L1 opened (0.5 mm orifice)", color=st.CRITICAL, fontsize=8.2, va="bottom")
    ax.set_ylabel("Pressure (bar)")
    ax.set_title("Five minutes of what the ESP32 would publish")
    st.subtitle(ax, "dashed: true pressure; offsets = sensor accuracy (±13 mbar, removed by zeroing); common wobble = 12 V adapter")
    ax.legend(loc="lower left", ncol=2)
    ax = axs[1]
    fw, cal = rec["F0_fw"], rec["F0_cal"]
    ax.step(fw.time, fw.q_hat * LPM, where="post", color=st.SERIES[3], lw=1.0, label="firmware as written (K = 7.5)")
    ax.step(cal.time, cal.q_hat * LPM, where="post", color=st.SERIES[2], lw=1.0, label="after bucket calibration")
    ax.plot(cal.time, cal.q_true * LPM, color=st.TEXT, lw=0.9, ls=(0, (3, 2)), label="true flow")
    ax.axvline(t_leak, color=st.CRITICAL, lw=0.9)
    ax.set_ylabel("F0 (L/min)")
    ax.set_xlabel("Time (s)")
    ax.set_title("F0: 1-second pulse counts")
    st.subtitle(ax, "about 6 pulses per second, so each 1-s reading jumps by one pulse = 0.12 L/min")
    ax.set_ylim(0.52, 1.3)
    ax.legend(loc="lower right", ncol=3)
    return st.save(fig, OUT / "recording.png")


def noise_budget(ref, duration=900):
    sched = [(0.0, ref)]
    comps = {
        "ADC (noise + 1-code steps)": dict(PS_SIGMA_N=0, PB_RIPPLE_M=0, PB_SIGMA_V=0, PB_T_AMP_LAB=0),
        "Sensor output noise": dict(PB_RIPPLE_M=0, PB_SIGMA_V=0, PB_T_AMP_LAB=0, ADS_NOISE=0),
        "Pump ripple (aliased)": dict(PS_SIGMA_N=0, PB_T_AMP_LAB=0, ADS_NOISE=0),
        "12 V adapter wander": dict(PS_SIGMA_N=0, PB_RIPPLE_M=0, PB_T_AMP_LAB=0, ADS_NOISE=0),
        "Everything together": {},
    }
    res = {}
    for name, off in comps.items():
        Pr = quiet_params(**off)
        rec = record(Pr, sched, duration, seed=7, wander_moves_pressure=not name.startswith("Pump"))
        p1, p2 = rec["P1"].value, rec["P2"].value
        n = min(len(p1), len(p2))
        res[name] = (change_sigma(p1, 1) / np.sqrt(2) * 1e3 / M_PER_BAR,
                     change_sigma(p1[:n] - p2[:n], 1) / np.sqrt(2) * 1e3 / M_PER_BAR)
    return res


def fig_noise(res):
    fig, ax = st.figure(w=8.6, h=3.9)
    names = list(res)
    y = np.arange(len(names))
    h = 0.36
    a = [res[n][0] for n in names]
    b = [res[n][1] for n in names]
    ax.barh(y - h / 2 - 0.02, a, height=h, color=st.SERIES[0], label="P1 alone")
    ax.barh(y + h / 2 + 0.02, b, height=h, color=st.SERIES[2], label="P1 − P2")
    for yi, (va, vb) in enumerate(zip(a, b)):
        ax.text(va, yi - h / 2 - 0.02, f" {va:.2f}", va="center", fontsize=8, color=st.TEXT_2)
        ax.text(vb, yi + h / 2 + 0.02, f" {vb:.2f}", va="center", fontsize=8, color=st.TEXT_2)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlabel("Noise of one published 1-s reading (mbar, 1σ)")
    ax.set_title("Where the noise comes from")
    st.subtitle(ax, "each bar: only that disturbance switched on; the difference P1 − P2 cancels the pump")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    return st.save(fig, OUT / "noise.png")


def detectability(ref, sweep, quiet):
    _, out = sweep
    windows = [1, 5, 10, 30, 60]
    res = {k: [] for k in ("P1 alone", "P1 − P2", "F0 calibrated", "F0 as written")}
    p1, p2 = quiet["P1"].value, quiet["P2"].value
    n = min(len(p1), len(p2))
    fcal, ffw = quiet["F0_cal"].q_hat, quiet["F0_fw"].q_hat
    r = out["L1"]
    pct = r[:, 0]
    fine = np.linspace(pct.min(), pct.max(), 2000)
    sig1 = np.interp(fine, pct, np.abs(r[:, 1]))
    sigd = np.interp(fine, pct, np.abs(r[:, 1] - r[:, 2]))
    sigf = np.interp(fine, pct, np.abs(r[:, 3]))
    k_ratio = B.FM_K.v / B.FM_K_FW.v          # uncalibrated firmware scales changes by K_F/K_fw

    def first(sig, thr):
        ok = sig > thr
        return float(fine[np.argmax(ok)]) if ok.any() else np.nan

    for w in windows:
        res["P1 alone"].append(first(sig1, KAPPA * change_sigma(p1, w) / M_PER_BAR * 1e3))
        res["P1 − P2"].append(first(sigd, KAPPA * change_sigma(p1[:n] - p2[:n], w) / M_PER_BAR * 1e3))
        res["F0 calibrated"].append(first(sigf, KAPPA * change_sigma(fcal, w) * LPM))
        res["F0 as written"].append(first(sigf * k_ratio, KAPPA * change_sigma(ffw, w) * LPM))
    return windows, res


def fig_detect(windows, res):
    fig, ax = st.figure(w=8.2, h=4.3)
    for i, (k, v) in enumerate(res.items()):
        ax.plot(windows, v, color=st.SERIES[i], marker="o", ms=5, mec=st.SURFACE, mew=1.2, label=k)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(windows, [str(w) for w in windows])
    ax.set_xlim(0.8, 75)
    ax.set_xlabel("Averaging window before and after (s)")
    ax.set_ylabel("Smallest leak at L1 seen at 3σ (% of flow)")
    ax.set_title("Pressure sees leaks of 0.05–0.8 % of the flow; F0 needs 1–7 %")
    st.subtitle(ax, "change between two consecutive windows, with every simulated disturbance on")
    ax.legend(loc="upper right")
    return st.save(fig, OUT / "detect.png")


# ════════════════════════════════════════════════════════════════════════════

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = oracle.checks()
    ref = reference_setting()
    diam = np.array([0.01, 0.015, 0.02, 0.03, 0.04, 0.06, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2]) * 1e-3
    sweep = leak_sweep(ref, diam)
    quiet = record(P, [(0.0, ref)], 2400, seed=3)
    sig = {"P_1s": change_sigma(quiet["P1"].value, 1) / np.sqrt(2) / M_PER_BAR,
           "F_cal_10s": change_sigma(quiet["F0_cal"].q_hat, 10)}
    t_leak = 150.0
    rec = record(P, [(0.0, ref), (t_leak, with_leak(ref, L1=0.5e-3))], 300, seed=5)
    budget = noise_budget(ref)
    windows, det = detectability(ref, sweep, quiet)
    figs = [fig_board(ref), fig_operating(ref), fig_signatures(sweep, sig), fig_recording(rec, t_leak),
            fig_noise(budget), fig_detect(windows, det)]

    s0, out = sweep
    l2, l3 = out["L2"], out["L3"]
    cos23 = float(np.min([np.dot(a[1:3], b[1:3]) / np.linalg.norm(a[1:3]) / np.linalg.norm(b[1:3])
                          for a, b in zip(l2, l3)]))
    i05 = list(diam).index(0.5e-3)
    sens = sb.speed_sensitivity(P, ref)
    lsb_bar = B.FW_DIV_FACTOR.v * 2 * B.ADS_FSR.v / 2 ** 16 / B.PS_V_MAX.v * (B.PS_P_MAX.v - B.PS_P_MIN.v)
    fw_bias = (rec["F0_fw"].q_hat[: int(t_leak) - 5].mean() / rec["F0_fw"].q_true[: int(t_leak) - 5].mean() - 1) * 100
    i30 = windows.index(30)
    # hand-opened tap: leak share at a few angles; slope of pressure vs end-valve angle; R = 45° contrast
    tap_pct = {}
    for a in (60.0, 75.0, 80.0, 81.5):
        s = run_board(P, BoardSetting(theta={**ref.theta, "L1": a}))
        tap_pct[a] = s.q_leak / s0.q_f0 * 100
    hi_ = run_board(P, BoardSetting(theta={**ref.theta, "V1": ref.theta["V1"] + 0.5, "V2": ref.theta["V2"] + 0.5}))
    lo_ = run_board(P, BoardSetting(theta={**ref.theta, "V1": ref.theta["V1"] - 0.5, "V2": ref.theta["V2"] - 0.5}))
    slope = np.mean(list(hi_.p_bar.values())) - np.mean(list(lo_.p_bar.values()))
    a45 = end_valve_angle_for(P, P_REF, BoardSetting(theta={"R1": 45.0, "R2": 45.0}))
    ref45 = BoardSetting(theta={"R1": 45.0, "R2": 45.0, "V1": a45, "V2": a45})
    b45 = run_board(P, ref45)
    l45 = run_board(P, with_leak(ref45, L1=0.5e-3))
    ratio45 = (l45.p_bar["P1"] - b45.p_bar["P1"]) / (l45.p_bar["P2"] - b45.p_bar["P2"])
    drop45 = b45.pressure["R1a"] - b45.pressure["R1b"]
    write_report(
        OUT / "README.md", 12, "Prototype bench twin",
        "Twin of the 3rd-phase board, built from the hardware list and sketch of 18 Nov 2026: every pipe, "
        "fitting, valve, tap, the R365 pump, both Swagelok sensors with their divider, the ADS1115, the "
        "ESP32 firmware formulas and the Hall flow sensor's pulse counter. It predicts what P1, P2 and F0 "
        "will publish for any valve setting and any leak, before the board is built.",
        built=[
            ("physics/fittings.py", "Bore restriction, Weisbach plug-valve law K(θ), DC diaphragm pump curve vs voltage, ripple", "§10.2–10.3"),
            ("network/prototype.py", "Board geometry from the sketch, BoardSetting (valve angles, calibrated leak orifices), board_spec", "§10.1–10.2"),
            ("steady/board.py", "run_board (EPANET, check valves on outlets, shut valves removed), safety check, end-valve angle for a target pressure", "§10.3"),
            ("sensors/board.py", "PressureChain (Swagelok → divider/shunt → ADS1115 → firmware), HallFlowMeter (pulse counter), supply wander, timelines", "§10.3–10.5"),
            ("config/params.yaml › prototype", "63 new parameters with source, range and ⚠ flag; 2 new materials (soft PVC hose, 316 steel)", "§0.7"),
        ],
        checks=checks,
        figures=[
            (figs[0].name, "The board as modelled, coloured by pressure, with L1 leaking through a 0.5 mm orifice."),
            (figs[1].name, "Operating map: pressure and flow vs the end-valve angle, for two settings of R1/R2."),
            (figs[2].name, "Leak signatures of the three taps for orifices of 0.01–1.2 mm."),
            (figs[3].name, "Five simulated minutes of published data; L1 opens at 150 s."),
            (figs[4].name, "Noise budget of one published 1-s reading."),
            (figs[5].name, "Smallest detectable leak vs averaging window."),
        ],
        findings=[
            f"**Working point.** The pressure only builds up when V1/V2 are within ~15° of shut-off; {P_REF} bar needs "
            f"V ≈ {ref.theta['V1']:.1f}° with R1 = R2 = {R_REF:.0f}° (shut at {B.THETA_CLOSED.v:.0f}°). Around there, 1° moves "
            f"the pressure by {slope:.2f} bar: set it slowly while watching P1/P2 on the laptop. The valve law beyond 65° is an "
            "extrapolation, so the real angle will differ; the healthy calibration fixes that.",
            f"**R1/R2 must really restrict.** At 45° they drop only {drop45 * 100:.0f} cm of water, so a leak on either branch moves P1 and P2 almost equally "
            f"(ΔP1/ΔP2 = {ratio45:.2f} for a 0.5 mm leak at L1). At {R_REF:.0f}° the branch contrast is clear: a 0.5 mm leak at L1 gives ΔP1 = {out['L1'][i05, 1]:.0f} mbar vs "
            f"ΔP2 = {out['L1'][i05, 2]:.0f} mbar.",
            f"**L2 and L3 cannot be told apart** with P1, P2 and F0 (cosine of their signatures ≥ {cos23:.4f}): both are on branch B, "
            "and both leaks draw their water through R2 only. A restriction between L2 and P2 separates them (L3's water must "
            "cross it, L2's does not): with a third mini valve at ~65–70° there (K ≈ 8 000) the two signatures are 16° apart "
            "in the P1–P2 plane. A third pressure sensor would also do it.",
            f"**Leak taps opened by hand are far too big.** The ½\" tap leaks {tap_pct[60.0]:.0f} % of the flow at 60°, {tap_pct[75.0]:.0f} % at 75°, "
            f"{tap_pct[80.0]:.0f} % at 80° and still {tap_pct[81.5]:.0f} % at 81.5° (shut at {B.THETA_CLOSED.v:.0f}°). For reproducible small leaks, put a calibrated "
            f"orifice at the end of each tap tube (a drilled cap or a dripper): 0.5 mm ≈ {out['L1'][i05, 0]:.0f} % of the flow, "
            f"0.2 mm ≈ {out['L1'][list(diam).index(0.2e-3), 0]:.1f} %.",
            f"**Pressure resolution is not the limit.** One ADS1115 code is {lsb_bar * 1e3:.2f} mbar. The largest noise is the 12 V adapter "
            f"wandering ({budget['12 V adapter wander'][0]:.1f} mbar on P1 alone, sensitivity {sens['P1'] / M_PER_BAR:.2f} bar per 100 % "
            f"voltage), and it nearly cancels in P1 − P2 ({budget['12 V adapter wander'][1]:.2f} mbar). Use the difference, or a regulated supply.",
            f"**F0 needs calibration and long windows.** At ~{s0.q_f0 * LPM:.1f} L/min the sensor gives ~6 pulses/s; with the firmware's "
            f"K = 7.5 and no offset it reads {fw_bias:+.0f} % off. A 1-s reading steps by 0.12 L/min. After the bucket calibration, "
            f"with 30-s windows, F0 detects leaks ≥ {det['F0 calibrated'][i30]:.1f} % of the flow; pressure detects ≥ "
            f"{det['P1 − P2'][i30]:.2f} %.",
            "**Never close all valves** (oracle 12.15): the R365 shut-off head (~1.8 bar) exceeds the sensors' 1.6 bar. The twin "
            "flags any setting whose highest pressure passes 90 % of 1.6 bar.",
            "**M3 is not tested on the board** (team decision, and the board is too short and has no fast valve). It remains fully in the "
            "simulation on the bench line and the demo farm (the pressure-wave studies (solver, leak echoes, M3)), with its parameters still marked ⚠.",
        ],
        assumptions=[
            "Layout read off the 18 Nov sketch; lengths, bores and heights are estimates (all ⚠ in params.yaml §0.7).",
            "Board flat on the table (team decision, 22 Nov), 0.5 m above the bucket water (bucket on the floor, assumed); outlet tubes drain freely (no siphon).",
            "Pump R365: straight-line curve through 2.5 L/min free flow and 1.8 bar shut-off at 12 V; listings disagree (1–2.5 bar).",
            "Fitting losses: Crane-type K values plus the bore restriction; valves follow the Weisbach plug-cock table. Laminar flow "
            "on the board (Re ≈ 800–1 700) makes real minor losses somewhat larger than these turbulent values: calibrated later.",
            "Pump ripple 0.1 m at 150 Hz and adapter wander 0.3 % are guesses until the 5-minute quiet recording.",
            "Flow sensor taken as a brass G1/2 type with f = 8.1 Q − 3 (Adafruit datasheet); the firmware constant 7.5 is the common example value.",
            "EPANET uses g = 9.80665 m/s²; the hand oracle 9.81 m/s² (0.03 % difference, inside the 0.1 % tolerance of 12.7).",
        ],
        decisions=[
            "Confirm which list is current: the cost sheet (16 Nov: 3 sensors 0–10 bar, YF-S201, 370 W pump, 3 branches) or the PDF + sketch (18 Nov). The twin follows the 18 Nov version.",
            f"Set R1/R2 near {R_REF:.0f}° (not 45°) so the two branches respond differently.",
            "Replace the hand-cracked leak taps by calibrated orifices (drilled end caps 0.2 / 0.5 / 1 mm, or drippers).",
            "Decide how to separate L2 from L3: a third mini valve between L2 and P2 (~65–70°), a third sensor, or accept 'branch B' as the answer.",
            "Keep the R365 out of the water: it is a self-priming diaphragm pump, not a submersible one (the 18 Nov diagram shows it inside the bucket).",
            "Once assembled, measure the ⚠ values and record the healthy settings, the leak flows and a 5-minute quiet run; the twin will be calibrated on them.",
        ],
    )
    print("Prototype bench report written:", OUT / "README.md")
    for k, v in det.items():
        print(k, [round(x, 3) for x in v])
    print(budget)


if __name__ == "__main__":
    main()
