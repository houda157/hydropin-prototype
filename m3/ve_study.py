"""What PE pipe-wall creep (viscoelasticity) does to M3 leak location, and how field
calibration fixes it (simulation).

    python -m m3.ve_study        ->  m3/out/ve_study.json, report/figures/m3_viscoelastic.png
    python -m m3.ve_study plot   ->  redraw the figure from the JSON

Three "real" pipes:
  elastic      – no creep
  creep        – typical PE creep (params.yaml 'viscoelastic', illustrative values)
  creep_other  – creep of another shape (retardation times 0.1 / 1 / 3 s): the model family
                 cannot reproduce it exactly (model-form error, like a real pipe)
Three ways to model the pipe:
  no calibration – elastic model (tr, tr_id, mfp, echo) / CNN uncalibrated route (cnn)
  lab creep      – the typical creep, known from lab tests (tr_ve, mfp_ve)
  calibrated     – wave speed, friction and creep fitted on ONE leak-free valve test of that
                   pipe (calibrate.py; σ = 0.05 m) (tr_cal, mfp_cal, cnn_cal)
Same leak positions, leak size and noise draws as m3.sweep.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from m3.calibrate import CAL_WINDOW_S, calibrate  # noqa: E402
from m3.cnn import MODEL_PATH, cnn_locate  # noqa: E402
from m3.locate import (echo_locate, estimate_wave_speed, matched_field, measure,  # noqa: E402
                       mfp_bank, time_reversal)
from m3.moc import leak_cda_for_fraction, load_setup, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POSITIONS = [30.0, 50.0, 75.0, 100.0, 125.0, 140.0]
NOISE_M = [0.02, 0.05, 0.1]
SEEDS = 3
LEAK_FRACTION = 0.05
U_IDENTIFIED = 0.03
CAL_SIGMA = 0.05
HAS_CNN = MODEL_PATH.exists()
SENS_SCALES = [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5]   # creep model / real creep
SENS_SIGMA = 0.05

TRUTHS = ["elastic", "creep", "creep_other"]
TRUTH_LABELS = {"elastic": "real pipe: elastic", "creep": "real pipe: typical PE creep",
                "creep_other": "real pipe: creep of another shape"}
LABELS = {
    "tr": "time reversal, elastic model",
    "tr_id": "time reversal, elastic model, a identified",
    "mfp": "matched-field, elastic model",
    "echo": "echo, elastic model",
    "cnn": "CNN, no calibration",
    "tr_ve": "time reversal, lab creep",
    "mfp_ve": "matched-field, lab creep",
    "tr_cal": "time reversal, calibrated",
    "mfp_cal": "matched-field, calibrated",
    "cnn_cal": "CNN, calibrated",
}


def truth_pipe(name: str):
    elastic = load_setup(viscoelastic=False)
    if name == "elastic":
        return elastic
    creep = load_setup(viscoelastic=True)
    if name == "creep":
        return creep
    return elastic.with_(ve_J=creep.ve_J, ve_tau=(0.1, 1.0, 3.0))


def _calibrate_truth(i_name):
    i, name = i_name
    base = load_setup(viscoelastic=False)
    t, h = measure(truth_pipe(name).with_(duration=CAL_WINDOW_S + 0.01), sigma_m=CAL_SIGMA,
                   rng=np.random.default_rng([20261125, 9, i]))
    m, info = calibrate(base, t, h)
    return name, m, info


def _bank(key_model):
    key, model = key_model
    return key, mfp_bank(model)


_G: dict = {}


def _init(models, banks):
    import torch
    torch.set_num_threads(1)
    _G["models"], _G["banks"] = models, banks


def _evaluate(args):
    truth, x, sigma, seed = args
    models, banks = _G["models"], _G["banks"]
    elastic, lab, cal = models["elastic"], models["lab"], models[f"cal_{truth}"]
    true = truth_pipe(truth)
    true = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, LEAK_FRACTION, x))
    t, h = measure(true, sigma_m=sigma, rng=np.random.default_rng([seed, int(x * 10), int(sigma * 1e4)]))
    a_id = estimate_wave_speed(elastic, t, h)
    row = {
        "truth": truth, "x_true": x, "sigma_m": sigma, "seed": seed, "a_identified": a_id,
        "tr": time_reversal(elastic, t, h).x_est,
        "tr_id": time_reversal(elastic.with_(a=a_id), t, h, a_uncertainty=U_IDENTIFIED).x_est,
        "mfp": matched_field(elastic, t, h, bank=banks["elastic"]).x_est,
        "echo": echo_locate(elastic, t, h),
        "tr_ve": time_reversal(lab, t, h).x_est,
        "mfp_ve": matched_field(lab, t, h, bank=banks["lab"]).x_est,
        "tr_cal": time_reversal(cal, t, h, a_uncertainty=U_IDENTIFIED).x_est,
        "mfp_cal": matched_field(cal, t, h, bank=banks[f"cal_{truth}"], a_uncertainty=U_IDENTIFIED).x_est,
    }
    if HAS_CNN:
        row["cnn"] = cnn_locate(elastic, t, h)
        row["cnn_cal"] = cnn_locate(elastic, t, h, calibrated=cal)
    return row


def _sens(args):
    scale, x = args
    creep_p = load_setup(viscoelastic=True)
    model = creep_p.with_(ve_J=tuple(j * scale for j in creep_p.ve_J))
    tru = creep_p.with_(x_leak=x, leak_cda=leak_cda_for_fraction(creep_p, LEAK_FRACTION, x))
    t, h = measure(tru, sigma_m=SENS_SIGMA, rng=np.random.default_rng([0, int(x * 10), int(SENS_SIGMA * 1e4)]))
    return scale, abs(time_reversal(model, t, h).x_est - x)


def main() -> None:
    t0 = time.time()
    workers = min(6, max(1, mp.cpu_count() - 1))   # each worker holds 5 replica banks + torch: RAM-bound
    with mp.Pool(len(TRUTHS)) as pool:
        cal = pool.map(_calibrate_truth, list(enumerate(TRUTHS)))
    models = {"elastic": load_setup(viscoelastic=False), "lab": load_setup(viscoelastic=True)}
    calib_info = {}
    for name, m, info in cal:
        models[f"cal_{name}"] = m
        calib_info[name] = info
    print(f"calibration: {time.time() - t0:.0f}s", {k: (round(v['a_mps'], 1), round(v['f'], 4),
                                                         round(v['creep_scale'], 3), round(v['rms_m'], 3))
                                                     for k, v in calib_info.items()})
    with mp.Pool(min(workers, len(models))) as pool:
        banks = dict(pool.map(_bank, list(models.items())))
    print(f"replica banks: {time.time() - t0:.0f}s")

    jobs = [(tv, x, s, k) for tv in TRUTHS for s in NOISE_M for x in POSITIONS for k in range(SEEDS)]
    with mp.Pool(workers, initializer=_init, initargs=(models, banks)) as pool:
        rows = pool.map(_evaluate, jobs, chunksize=2)
        sens_rows = pool.map(_sens, [(sc, x) for sc in SENS_SCALES for x in POSITIONS])
    methods = [m for m in LABELS if m in rows[0]]

    summary = {}
    for truth in TRUTHS:
        summary[truth] = {}
        for m in methods:
            summary[truth][m] = {}
            for s in NOISE_M:
                err = [abs(r[m] - r["x_true"]) for r in rows if r["truth"] == truth and r["sigma_m"] == s]
                summary[truth][m][str(s)] = {"mae_m": float(np.mean(err)),
                                             "within_5m": float(np.mean(np.array(err) <= 5))}
    sens = {}
    for sc in SENS_SCALES:
        errs = [e for s2, e in sens_rows if s2 == sc]
        sens[str(sc)] = {"mae_m": float(np.mean(errs)), "max_m": float(np.max(errs)),
                         "errors_m": [round(e, 2) for e in errs]}

    # how creep changes the signal itself (noise-free, leak at 90 m)
    sig = {}
    for name in TRUTHS:
        base = truth_pipe(name)
        ref = simulate(base.with_(duration=6.0))
        leak = simulate(base.with_(x_leak=90.0, leak_cda=leak_cda_for_fraction(base, 0.05, 90.0)))
        lr = simulate(base)
        first = (ref.t > 0.1) & (ref.t < 1.0)
        late = ref.t > 5.0
        win = (leak.t > base.t_close + 0.3) & (leak.t < base.t_close + 0.4)
        sig[name] = {
            "surge_m": float(ref.H_valve[(ref.t > 0.15) & (ref.t < 0.3)].mean() - ref.H0),
            "swing_first_s_m": float(np.ptp(ref.H_valve[first])),
            "swing_after_5s_m": float(np.ptp(ref.H_valve[late])),
            "echo_step_90m_m": float(abs((leak.H_valve - lr.H_valve)[win].mean()
                                         - (leak.H_valve - lr.H_valve)[leak.t < base.t_close].mean())),
            "trace": {"t_s": ref.t[::40].round(4).tolist(), "H_m": ref.H_valve[::40].round(3).tolist()},
        }
    creep_p = load_setup(viscoelastic=True)
    result = {
        "simulation": True,
        "creep_model": {"J_per_Pa": list(creep_p.ve_J), "tau_s": list(creep_p.ve_tau),
                        "wall_m": creep_p.wall, "alpha": creep_p.ve_alpha,
                        "other_shape_tau_s": [0.1, 1.0, 3.0],
                        "note": "illustrative assumption (params.yaml), to confirm with the mentor"},
        "setup": {"positions_m": POSITIONS, "noise_m": NOISE_M, "seeds": SEEDS,
                  "leak_fraction": LEAK_FRACTION, "calibration_sigma_m": CAL_SIGMA, "truths": TRUTHS},
        "calibration": calib_info,
        "signal": {k: {kk: vv for kk, vv in v.items() if kk != "trace"} for k, v in sig.items()},
        "traces": {k: v["trace"] for k, v in sig.items()},
        "summary": summary, "labels": {m: LABELS[m] for m in methods},
        "creep_model_sensitivity": {"sigma_m": SENS_SIGMA, "method": "tr, lab creep model with J scaled, real pipe = creep",
                                    "by_scale": sens},
        "rows": rows,
        "runtime_s": round(time.time() - t0, 1),
    }
    out = ROOT / "m3" / "out"
    (out / "ve_study.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    fig_path = plot(result)

    for truth in TRUTHS:
        print(truth)
        for m in methods:
            print(f"   {m:8s}", {k: round(v['mae_m'], 2) for k, v in summary[truth][m].items()})
    print("creep model sensitivity (scale: mean / max m):",
          {k: (round(v["mae_m"], 2), round(v["max_m"], 2)) for k, v in sens.items()})
    print(f"done in {result['runtime_s']}s -> m3/out/ve_study.json, {fig_path.relative_to(ROOT)}")


def plot(result: dict) -> Path:
    """Draw report/figures/m3_viscoelastic.png from a ve_study.json result."""
    summary = result["summary"]
    truths = [t for t in TRUTHS if t in summary]
    labels = {m: LABELS.get(m, v) for m, v in result["labels"].items()}
    methods = list(labels)
    sens = result["creep_model_sensitivity"]["by_scale"]
    sens_sigma = result["creep_model_sensitivity"]["sigma_m"]
    colors = {"elastic": "#bbb", "creep": "#2d6fa3", "creep_other": "#e07b00"}

    fig, ax = plt.subplots(1, 3, figsize=(17, 6.2), gridspec_kw={"width_ratios": [1, 1.5, 1.0]})
    for name in truths:
        tr = result["traces"][name]
        ax[0].plot(tr["t_s"], tr["H_m"], color="#888" if name == "elastic" else colors[name], lw=1.1,
                   label=TRUTH_LABELS[name].replace("real pipe: ", ""))
    ax[0].set_xlabel("time (s)")
    ax[0].set_ylabel("head at the valve (m)")
    ax[0].set_title("1. Creep damps and smooths the wave (no leak)", fontsize=10)
    ax[0].legend(fontsize=8, loc="lower right")
    ax[0].grid(alpha=0.3)

    s_show = "0.05"
    ys = np.arange(len(methods))[::-1] * 1.25
    w = 0.34
    offs = {t: (1 - i) * w for i, t in enumerate(truths)}
    vmax = 0.0
    for t in truths:
        vals = [summary[t][m][s_show]["mae_m"] for m in methods]
        vmax = max(vmax, max(vals))
        ax[1].barh(ys + offs[t], vals, w, color=colors[t], label=TRUTH_LABELS[t])
        for y, v in zip(ys, vals):
            ax[1].text(v + 0.6, y + offs[t], f"{v:.1f}", va="center", fontsize=6.5,
                       color="#555" if t == "elastic" else colors[t])
    ax[1].set_yticks(ys)
    ax[1].set_yticklabels([labels[m] for m in methods], fontsize=8)
    ax[1].axvline(5, color="#c0392b", ls=":", lw=1, label="'a few metres' (5 m)")
    ax[1].set_xlabel("mean |error| (m)")
    ax[1].set_xlim(0, vmax * 1.18)
    ax[1].set_title(f"2. Leak location error by method (σ = {s_show} m, 5 % leak)", fontsize=10)
    ax[1].legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, frameon=False)
    ax[1].grid(alpha=0.3, axis="x")

    scales = [float(k) for k in sens]
    xpct = [100 * (s - 1) for s in scales]
    ax[2].plot(xpct, [v["mae_m"] for v in sens.values()], "o-", color="#2d6fa3", label="mean error")
    ax[2].plot(xpct, [v["max_m"] for v in sens.values()], "s--", color="#999", ms=4,
               label="worst of 6 leak positions")
    ax[2].axhline(5, color="#c0392b", ls=":", lw=1, label="5 m")
    ax[2].set_yscale("log")
    ax[2].set_ylim(0.1, 300)
    ax[2].set_xlabel("creep error in the model (%)")
    ax[2].set_ylabel("|error| (m)")
    ax[2].set_title("3. No calibration: how exactly\n"
                    f"must creep be known? (TR, σ = {sens_sigma} m)", fontsize=10)
    ax[2].legend(fontsize=7.5, loc="lower left", framealpha=0.95)
    ax[2].grid(alpha=0.3)
    fig.text(0.01, 0.01, "SIMULATION – creep parameters are illustrative (3 Kelvin-Voigt elements, "
             "τ = 0.05 / 0.5 / 1.5 s, total 3e-10 1/Pa; 'another shape': τ = 0.1 / 1 / 3 s); confirm with "
             "the mentor. 'Calibrated' = fitted on one leak-free valve test (σ = 0.05 m).",
             fontsize=8, color="#a00")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig_path = ROOT / "report" / "figures" / "m3_viscoelastic.png"
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)
    return fig_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "plot":       # redraw from the saved JSON only
        print(plot(json.loads((ROOT / "m3" / "out" / "ve_study.json").read_text(encoding="utf-8"))))
    else:
        main()
