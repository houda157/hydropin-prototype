"""Scenarios, virtual sensors, dataset, detectability: figures + report.

Also writes the training dataset used by M1 and M2: data/farm_dataset.npz
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from hydropin_sim.contracts import LeakSpec, Scenario  # noqa: E402
from hydropin_sim.physics.leaks import leak_area_for_flow  # noqa: E402
from hydropin_sim.sensors import dataset as dsm  # noqa: E402
from hydropin_sim.sensors import model as sm  # noqa: E402
from hydropin_sim.steady.scenarios import candidate_leaks  # noqa: E402
from hydropin_sim.steady.solver import run_steady  # noqa: E402
from hydropin_sim.viz import style as st  # noqa: E402
from hydropin_sim.viz.report import write_report  # noqa: E402
from oracles import sensors as oracle  # noqa: E402
from oracles.sensors import FARM, FS, P  # noqa: E402

OUT = ROOT / "results" / "sensors"
DATA = ROOT / "data" / "farm_dataset.npz"
SHIFT = ("SECTOR1", "SECTOR3")
LH = 3.6e6
N_DATASET = 4000


def fig_sensor_day():
    rng = np.random.default_rng(2)
    sensor = sm.LowRateSensor.create("P1", "S1", P, rng)
    t = np.arange(0, 86400, 60.0)
    h = 15.0
    y = sensor.read(h, t, P, rng).value
    y0 = y - sensor.bias            # zeroed at installation
    k = 15
    yk = np.nanmean(y0.reshape(-1, k), axis=1)
    tk = t.reshape(-1, k).mean(axis=1)
    dT = sm.box_temperature(t, P.sensors.T_AMP.v)
    comp = y0 - P.sensors.TEMPCO.v * FS * dT * (1 - P.sensors.TEMP_COMP_RESIDUAL.v)
    ck = np.nanmean(comp.reshape(-1, k), axis=1)
    fig, ax = st.figure(w=8.2, h=4.2)
    ax.plot(t / 3600, y0, ".", color="#c9c8c2", markersize=2.2, label="raw readings (1 per minute)")
    ax.plot(tk / 3600, yk, color=st.SERIES[1], label="15-min average, no compensation")
    ax.plot(tk / 3600, ck, color=st.SERIES[0], label="15-min average, temperature-compensated")
    ax.axhline(h, color=st.TEXT, lw=0.9, ls=(0, (3, 3)))
    ax.text(23.8, h + 0.015, "true pressure 15.00 m", ha="right", va="bottom", fontsize=8.2, color=st.TEXT_2)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xlabel("Time of day (h)")
    ax.set_ylabel("Reported pressure head (m)")
    ax.set_title("One day in the life of a virtual pressure sensor")
    st.subtitle(ax, f"0–{P.sensors.FS_BAR.v:.0f} bar, ±{P.sensors.ACC.v * 100:.2f} % FS, box swinging ±{P.sensors.T_AMP.v:.0f} K "
                    "in the sun · constant true pressure")
    ax.legend(loc="lower right", ncol=1)
    return st.save(fig, OUT / "sensor_day.png")


def signatures():
    """Δh at the sensors for a 5 % leak at every location that carries water in SHIFT."""
    base = run_steady(FARM, Scenario(id="h", network="farm_demo", seed=0, open_sectors=list(SHIFT),
                                     duration=1, timestep=1, water_temp=25.0), P)
    ix = {n: i for i, n in enumerate(base.node_ids)}
    q0 = base.pump_flow[0]
    pipes, blocks = candidate_leaks(FARM, SHIFT)
    block_pipe = {p.end: p.id for p in FARM.pipes if p.id.startswith("SUB")}
    locs = [(p, LeakSpec(pipe=p, position=0.5, area=1.0)) for p in pipes if not p.startswith("SUB")] + \
           [(p, LeakSpec(pipe=p, position=0.5, area=1.0)) for p in pipes if p.startswith("SUB")] + \
           [(f"{b} (lateral)", LeakSpec(pipe=block_pipe[b], position=1.0, area=1.0)) for b in blocks]
    names, dh, qleak = [], [], []
    for name, lk in locs:
        h_loc = 14.0
        lk.area = float(leak_area_for_flow(0.05 * q0, h_loc, P.leaks.CD_LEAK.v))
        r = run_steady(FARM, Scenario(id="l", network="farm_demo", seed=0, open_sectors=list(SHIFT),
                                      duration=1, timestep=1, water_temp=25.0, leaks=[lk]), P)
        ixl = {n: i for i, n in enumerate(r.node_ids)}
        dh.append([r.pressure[0, ixl[s]] - base.pressure[0, ix[s]] for s in dsm.FARM_SENSORS])
        names.append(name)
        qleak.append(r.leak_flow[0])
    return names, np.array(dh), np.array(qleak), q0


def fig_signatures(names, dh):
    fig, ax = st.figure(w=8.2, h=5.0)
    mag = np.abs(dh) * 100
    im = ax.imshow(mag, cmap=st.SEQ_CMAP, aspect="auto", vmin=0)
    ax.set_xticks(range(len(dsm.FARM_SENSORS)), dsm.FARM_SENSORS)
    ax.set_yticks(range(len(names)), names)
    ax.grid(False)
    for i in range(mag.shape[0]):
        for j in range(mag.shape[1]):
            v = mag[i, j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7.4,
                    color=st.SURFACE if v > 0.6 * mag.max() else st.TEXT_2)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Pressure drop (cm of water)", color=st.TEXT_2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=st.TEXT_2, labelsize=8)
    ax.set_xlabel("Pressure sensor (node)")
    ax.set_ylabel("Leak location")
    ax.set_title("Leak signatures: pressure drop at each sensor")
    st.subtitle(ax, "Shift sectors 1 + 3 · one leak of 5 % of the pump flow at a time · sensors in closed sectors read ≈ 0")
    return st.save(fig, OUT / "signatures.png")


def fig_detectability(names, dh, qleak, q0, healthy_sd):
    kappa = P.decision.KAPPA.v
    sens = np.max(np.abs(dh), axis=1) / qleak        # m per (m3/s), linearised
    s_comp, s_raw = sm.sigma_total(P, True), sm.sigma_total(P, False)
    q_comp = kappa * s_comp / sens * LH
    q_raw = kappa * s_raw / sens * LH
    q_flow_noise = kappa * P.sensors.SIGMA_Q.v * q0 / np.sqrt(P.decision.N_AVG.v) * LH
    q_flow_model = kappa * healthy_sd * q0 * LH
    order = np.argsort(q_comp)
    fig, ax = st.figure(w=8.2, h=5.0)
    y = np.arange(len(names))
    for k, i in enumerate(order):
        ax.plot([q_comp[i], q_raw[i]], [k, k], color=st.GRID, lw=2.2, zorder=1)
    ax.scatter(q_comp[order], y, color=st.SERIES[0], s=46, zorder=3, edgecolors=st.SURFACE, linewidths=1.5,
               label="pressure, temperature-compensated")
    ax.scatter(q_raw[order], y, color=st.SERIES[1], s=46, zorder=3, edgecolors=st.SURFACE, linewidths=1.5,
               label="pressure, no compensation")
    ax.axvline(q_flow_noise, color=st.SERIES[2], lw=1.5)
    ax.axvline(q_flow_model, color=st.SERIES[2], lw=1.5, ls=(0, (4, 3)))
    ax.text(q_flow_noise * 1.06, len(names) - 0.6, "flow meter,\nnoise only", fontsize=7.8, color=st.TEXT_2, va="top")
    ax.text(q_flow_model * 1.06, len(names) - 0.6, "flow balance,\nwith model\nuncertainty", fontsize=7.8,
            color=st.TEXT_2, va="top")
    ax.set_xscale("log")
    ax.set_yticks(y, [names[i] for i in order])
    ax.set_xlabel("Smallest detectable leak (L/h, log scale)")
    ax.set_title("Detectability map: the smallest leak each sensor set can see")
    st.subtitle(ax, f"κ = {kappa:.0f}, {int(P.decision.N_AVG.v)}-min windows · shift sectors 1 + 3 "
                    f"(pump {q0 * 1000:.1f} L/s = {q0 * LH:,.0f} L/h)")
    ax.legend(loc="lower right")
    ax.set_xlim(min(q_comp.min(), q_flow_noise) / 1.6, max(q_raw.max(), q_flow_model) * 3)
    return st.save(fig, OUT / "detectability.png"), q_comp, q_raw, q_flow_noise, q_flow_model


def fig_water_balance(ds, nominal_q):
    q_meas = np.nanmean(ds["Q"], axis=1)
    q_nom = nominal_q[ds["SHIFT"]]
    excess = (q_meas / q_nom - 1) * 100
    frac = ds["LEAK_FLOW"] / q_nom * 100
    kind = ds["LEAK_KIND"]
    healthy = kind == 0
    sd = excess[healthy].std()
    fig, ax = st.figure(w=8.2, h=4.4)
    rng = np.random.default_rng(0)
    ax.scatter(rng.uniform(0.35, 0.65, healthy.sum()), excess[healthy], s=6, color="#c9c8c2",
               label="healthy (jittered)", zorder=2)
    ax.scatter(frac[kind == 1], excess[kind == 1], s=7, color=st.SERIES[0], alpha=0.7, label="leak on a pipe", zorder=3)
    ax.scatter(frac[kind == 2], excess[kind == 2], s=7, color=st.SERIES[1], alpha=0.7, label="leak in a lateral", zorder=3)
    thr = P.decision.KAPPA.v * sd + excess[healthy].mean()
    ax.axhline(thr, color=st.TEXT_2, lw=0.9, ls=(0, (3, 3)))
    ax.text(0.95, thr + 0.5, f"alarm threshold (healthy mean + κσ) = {thr:.1f} %", ha="left", fontsize=8.2,
            color=st.TEXT_2)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(0.3, 28)
    ax.set_xticks([0.5, 1, 2, 5, 10, 20], ["healthy", "1", "2", "5", "10", "20"])
    ax.set_xlabel("True leak flow (% of the shift's nominal flow)")
    ax.set_ylabel("Measured pump flow vs nominal (%)")
    ax.set_title("Water balance at the pump: what the flow meter alone can see")
    st.subtitle(ax, f"{len(kind):,} Monte Carlo samples (clogging, roughness, survey error, water temperature, sensor noise)")
    ax.legend(loc="upper left", markerscale=2.2)
    return st.save(fig, OUT / "water_balance.png"), sd / 100


def main():
    checks = oracle.checks()
    f1 = fig_sensor_day()
    names, dh, qleak, q0 = signatures()
    f2 = fig_signatures(names, dh)
    print("generating dataset ...")
    ds = dsm.generate(FARM, P, N_DATASET, seed=3, verbose=True)
    dsm.save(ds, DATA)
    shifts = [tuple(s.split("+")) for s in ds["shifts"]]
    nominal = dsm.nominal_shift_info(FARM, P, shifts)
    nominal_q = np.array([nominal[s][0].q_nominal for s in shifts])
    f4, healthy_sd = fig_water_balance(ds, nominal_q)
    f3, q_comp, q_raw, q_fn, q_fm = fig_detectability(names, dh, qleak, q0, healthy_sd)
    n_leak = int((ds["LEAK_KIND"] > 0).sum())
    write_report(
        OUT / "README.md", 3, "Virtual sensors, scenarios and training dataset",
        "The twin now produces what the field will produce: noisy, drifting, quantised sensor readings with lost "
        "packets, for thousands of randomly perturbed irrigation shifts with and without leaks. It also says "
        "which leaks are detectable before any method is trained.",
        built=[
            ("sensors/model.py", "Low-rate sensor (gain, bias, temperature and ageing drift, noise, ADC, packet loss), high-rate M3 sensor (lag, sampling, GPS offset), flow meter, σ_tot, detectability", "§3, §2.7"),
            ("steady/scenarios.py", "Monte Carlo sampler: shift, clogging, roughness, survey error, water temperature, one leak on a pipe or inside a lateral, only where water flows", "§2.9"),
            ("sensors/dataset.py", f"Scenario → twin → sensors pipeline; `data/farm_dataset.npz` with {N_DATASET:,} samples", "§2.9, §3"),
            ("sensors/stream.py", "Readings → MQTT messages in the exact ESP32 format (topic hydropin/<farm>/<node>)", "contracts"),
            ("params.yaml + math note", "New: `N_AVG`, `TEMP_COMP_RESIDUAL`, `SIGMA_Q` (§0.6, §2.7, §3.3 updated)", "§0.6"),
        ],
        checks=checks,
        figures=[
            (f1.name, "One sensor, one day, constant true pressure: noise, lost packets, and the daily drift caused by the sun on the box."),
            (f2.name, "Leak signatures: which sensor sees which leak, and how strongly."),
            (f3.name, "Detectability map: smallest detectable leak per location, for the pressure sensors (with/without temperature compensation) and for the flow meter."),
            (f4.name, "Water balance over the whole dataset: pump flow vs the twin's nominal flow."),
        ],
        findings=[
            f"Temperature compensation is the single most important sensor-side feature: it brings σ_tot from **{sm.sigma_total(P, False) * 100:.1f} cm** to **{sm.sigma_total(P, True) * 100:.1f} cm**. Measuring the box temperature in every node is a cheap must-have for the hardware team.",
            f"With compensation, the smallest detectable leak by pressure is **{q_comp.min():.0f}–{q_comp.max():.0f} L/h** depending on location. Without it, **{q_raw.min():.0f}–{q_raw.max():.0f} L/h**. For comparison, one 80 m lateral carries ≈ 400 L/h, so a split lateral is clearly detectable.",
            f"The flow meter is precise (noise-only limit ≈ {q_fn:.0f} L/h), but comparing the pump flow with the twin is limited by **model uncertainty** (clogging, roughness, water temperature): healthy samples scatter by ±{healthy_sd * 100:.1f} %, so the water balance alone only flags leaks above ≈ **{q_fm:.0f} L/h**. Pressure patterns (M1/M2) are needed below that, and calibration on the real farm will tighten this band.",
            f"Every leak drops **all** open-sector sensors by {np.abs(dh[np.abs(dh) > 0.01]).min() * 100:.0f}–{np.abs(dh).max() * 100:.0f} cm: most of that is the pump sliding down its curve (common to all sensors). The part that differs between sensors, which localises the leak, is at most ≈ {np.max(np.ptp(np.where(np.abs(dh) > 0.01, dh, np.nan)[:, ~np.all(np.abs(dh) < 0.01, axis=0)], axis=1)) * 100:.0f} cm. So detection is easy and localisation is the hard part. M2 must work on the *pattern* (removing the common part), and M3 is needed for the last metres.",
            "Sensors in closed sectors read ≈ 0 and see nothing. Detection is **per shift**, and a leak in a sector is only visible while that sector irrigates.",
            f"Dataset for M1 and M2: **{N_DATASET:,} samples**, {n_leak:,} with a leak (half on pipes, half inside laterals), 6 shifts, 9 pressure sensors + 1 flow meter, 60 one-minute readings each.",
        ],
        assumptions=[
            "Sensor parameters (`ACC`, `TEMPCO`, `T_AMP`, `DRIFT_YR`, `SIGMA_N`, `LOSS_RATE`, `TEMP_COMP_RESIDUAL`, `SIGMA_Q`) are placeholders (`verify`); replace them with the chosen sensor's datasheet and the bench measurements.",
            "Bias and gain are removed by zeroing at installation; a leak is judged as a change (math note §3.3).",
            "Monte Carlo ranges: clogging 0–30 % (mostly clean), roughness ×0.8–3, survey error σ = 5 cm, water 15–35 °C, leak 1–20 % of the shift flow (log-uniform).",
            "Default sensor set (9 pressure sensors: pump outlet, every sector head, every sector's last block) until sensor placement optimises it.",
            "Each sample is entirely healthy or entirely leaky (no leak starting mid-window yet).",
        ],
        decisions=[
            "Hardware team: add a temperature sensor in every node box (needed for compensation).",
            "Confirm the Monte Carlo ranges with the agricultural engineer (typical clogging, water temperature in pipes).",
        ],
    )
    print(f"Sensors: {sum(c.passed for c in checks)}/{len(checks)} checks pass")


if __name__ == "__main__":
    main()
