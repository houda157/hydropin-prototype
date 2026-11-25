"""What PE pipe-wall creep (viscoelasticity) does to M3 leak location (simulation).

    python -m m3.ve_study   ->  m3/out/ve_study.json, report/figures/m3_viscoelastic.png

The real pipe either is elastic or creeps (params.yaml 'viscoelastic', illustrative values).
Each method runs with an **elastic model** (unaware of creep, the realistic first attempt)
and, for time reversal and matched-field, also with a **creep-aware model** (same creep
parameters as the real pipe: the best case, if creep was measured in the lab).
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
HAS_CNN = MODEL_PATH.exists()
SENS_SCALES = [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5]   # creep model / real creep
SENS_SIGMA = 0.05

LABELS = {
    "tr": "time reversal, elastic model",
    "tr_id": "time reversal, elastic model, a identified",
    "tr_ve": "time reversal, creep-aware model",
    "mfp": "matched-field, elastic model",
    "mfp_ve": "matched-field, creep-aware model",
    "echo": "echo, elastic model",
    "cnn": "CNN (elastic training), a identified",
}


def _bank(viscoelastic: bool):
    return viscoelastic, mfp_bank(load_setup(viscoelastic=viscoelastic))


def _evaluate(truth_ve: bool, banks, x, sigma, seed):
    elastic = load_setup(viscoelastic=False)
    creep = load_setup(viscoelastic=True)
    true = creep if truth_ve else elastic
    true = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, LEAK_FRACTION, x))
    t, h = measure(true, sigma_m=sigma, rng=np.random.default_rng([seed, int(x * 10), int(sigma * 1e4)]))
    a_id = estimate_wave_speed(elastic, t, h)
    row = {
        "truth": "creep" if truth_ve else "elastic", "x_true": x, "sigma_m": sigma, "seed": seed,
        "a_identified": a_id,
        "tr": time_reversal(elastic, t, h).x_est,
        "tr_id": time_reversal(elastic.with_(a=a_id), t, h, a_uncertainty=U_IDENTIFIED).x_est,
        "tr_ve": time_reversal(creep, t, h).x_est,
        "mfp": matched_field(elastic, t, h, bank=banks[False]).x_est,
        "mfp_ve": matched_field(creep, t, h, bank=banks[True]).x_est,
        "echo": echo_locate(elastic, t, h),
    }
    if HAS_CNN:
        row["cnn"] = cnn_locate(elastic, t, h)
    return row


def main() -> None:
    t0 = time.time()
    with mp.Pool(2) as pool:
        banks = dict(pool.map(_bank, [False, True]))
    print(f"replica banks: {time.time() - t0:.0f}s")
    rows = [_evaluate(tv, banks, x, s, k)
            for tv in (False, True) for s in NOISE_M for x in POSITIONS for k in range(SEEDS)]
    methods = [m for m in LABELS if m in rows[0]]

    summary = {}
    for truth in ("elastic", "creep"):
        summary[truth] = {}
        for m in methods:
            summary[truth][m] = {}
            for s in NOISE_M:
                err = [abs(r[m] - r["x_true"]) for r in rows if r["truth"] == truth and r["sigma_m"] == s]
                summary[truth][m][str(s)] = {"mae_m": float(np.mean(err)),
                                             "within_5m": float(np.mean(np.array(err) <= 5))}

    # how creep changes the signal itself (noise-free, leak at 90 m)
    sig = {}
    for name, ve in (("elastic", False), ("creep", True)):
        base = load_setup(viscoelastic=ve)
        ref = simulate(base.with_(duration=6.0))
        leak = simulate(base.with_(x_leak=90.0, leak_cda=leak_cda_for_fraction(base, 0.05, 90.0)))
        first = (ref.t > 0.1) & (ref.t < 1.0)
        late = ref.t > 5.0
        win = (leak.t > base.t_close + 0.3) & (leak.t < base.t_close + 0.4)
        lr = simulate(base)
        sig[name] = {
            "surge_m": float(ref.H_valve[(ref.t > 0.15) & (ref.t < 0.3)].mean() - ref.H0),
            "swing_first_s_m": float(np.ptp(ref.H_valve[first])),
            "swing_after_5s_m": float(np.ptp(ref.H_valve[late])),
            "echo_step_90m_m": float(abs((leak.H_valve - lr.H_valve)[win].mean()
                                         - (leak.H_valve - lr.H_valve)[leak.t < base.t_close].mean())),
            "trace_t_s": ref.t[::40].round(4).tolist(), "trace_H_m": ref.H_valve[::40].round(3).tolist(),
        }
    # how accurate must the creep model be? TR with creep compliances scaled by s
    creep_p = load_setup(viscoelastic=True)
    sens = {}
    for scale in SENS_SCALES:
        model = creep_p.with_(ve_J=tuple(j * scale for j in creep_p.ve_J))
        errs = []
        for x in POSITIONS:
            tru = creep_p.with_(x_leak=x, leak_cda=leak_cda_for_fraction(creep_p, LEAK_FRACTION, x))
            t, h = measure(tru, sigma_m=SENS_SIGMA, rng=np.random.default_rng([0, int(x * 10), int(SENS_SIGMA * 1e4)]))
            errs.append(abs(time_reversal(model, t, h).x_est - x))
        sens[str(scale)] = {"mae_m": float(np.mean(errs)), "max_m": float(np.max(errs)),
                            "errors_m": [round(e, 2) for e in errs]}
    result = {
        "simulation": True,
        "creep_model": {"J_per_Pa": list(creep_p.ve_J), "tau_s": list(creep_p.ve_tau),
                        "wall_m": creep_p.wall, "alpha": creep_p.ve_alpha,
                        "note": "illustrative assumption (params.yaml), to confirm with the mentor"},
        "setup": {"positions_m": POSITIONS, "noise_m": NOISE_M, "seeds": SEEDS, "leak_fraction": LEAK_FRACTION},
        "signal": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("trace")} for k, v in sig.items()},
        "traces": {k: {"t_s": v["trace_t_s"], "H_m": v["trace_H_m"]} for k, v in sig.items()},
        "summary": summary, "labels": {m: LABELS[m] for m in methods},
        "creep_model_sensitivity": {"sigma_m": SENS_SIGMA, "method": "tr, creep-aware model with J scaled",
                                    "by_scale": sens},
        "rows": rows,
        "runtime_s": round(time.time() - t0, 1),
    }
    out = ROOT / "m3" / "out"
    (out / "ve_study.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    fig_path = plot(result)

    print(json.dumps(result["signal"], indent=1))
    for truth in ("elastic", "creep"):
        print(truth)
        for m in methods:
            print(f"   {m:7s}", {k: round(v['mae_m'], 2) for k, v in summary[truth][m].items()})
    print("creep model sensitivity (scale: mean / max m):",
          {k: (round(v["mae_m"], 2), round(v["max_m"], 2)) for k, v in sens.items()})
    print(f"done in {result['runtime_s']}s -> m3/out/ve_study.json, {fig_path.relative_to(ROOT)}")


def plot(result: dict) -> Path:
    """Draw report/figures/m3_viscoelastic.png from a ve_study.json result."""
    summary = result["summary"]
    labels = {m: LABELS.get(m, v) for m, v in result["labels"].items()}
    methods = list(labels)
    sens = result["creep_model_sensitivity"]["by_scale"]
    sens_sigma = result["creep_model_sensitivity"]["sigma_m"]

    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8), gridspec_kw={"width_ratios": [1, 1.35, 1.0]})
    for name, color in (("elastic", "#888"), ("creep", "#2d6fa3")):
        tr = result["traces"][name]
        ax[0].plot(tr["t_s"], tr["H_m"], color=color, lw=1.1,
                   label="elastic pipe" if name == "elastic" else "PE pipe with creep")
    ax[0].set_xlabel("time (s)")
    ax[0].set_ylabel("head at the valve (m)")
    ax[0].set_title("1. Creep damps and smooths the wave (no leak)", fontsize=10)
    ax[0].legend(fontsize=8, loc="lower right")
    ax[0].grid(alpha=0.3)

    s_show = "0.05"
    ys = np.arange(len(methods))[::-1]
    w = 0.38
    e_vals = [summary["elastic"][m][s_show]["mae_m"] for m in methods]
    c_vals = [summary["creep"][m][s_show]["mae_m"] for m in methods]
    ax[1].barh(ys + w / 2, e_vals, w, color="#bbb", label="real pipe: elastic")
    ax[1].barh(ys - w / 2, c_vals, w, color="#2d6fa3", label="real pipe: PE with creep")
    for y, ev, cv in zip(ys, e_vals, c_vals):
        ax[1].text(ev + 0.8, y + w / 2, f"{ev:.1f} m", va="center", fontsize=7, color="#555")
        ax[1].text(cv + 0.8, y - w / 2, f"{cv:.1f} m", va="center", fontsize=7, color="#2d6fa3")
    ax[1].set_yticks(ys)
    ax[1].set_yticklabels([labels[m] for m in methods], fontsize=7.5)
    ax[1].axvline(5, color="#c0392b", ls=":", lw=1, label="'a few metres' (5 m)")
    ax[1].set_xlabel("mean |error| (m)")
    ax[1].set_xlim(0, max(max(e_vals), max(c_vals)) * 1.25)
    ax[1].set_title(f"2. The model must match the pipe wall (σ = {s_show} m)", fontsize=10)
    ax[1].legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, frameon=False)
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
    ax[2].set_title("3. How well must creep be known?\n"
                    f"(time reversal, σ = {sens_sigma} m)", fontsize=10)
    ax[2].legend(fontsize=7.5, loc="lower left", framealpha=0.95)
    ax[2].grid(alpha=0.3)
    fig.text(0.01, 0.01, "SIMULATION – creep parameters are illustrative (3 Kelvin-Voigt elements, "
             "τ = 0.05 / 0.5 / 1.5 s, total 3e-10 1/Pa); confirm with the mentor. 5 % leak.",
             fontsize=8, color="#a00")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig_path = ROOT / "report" / "figures" / "m3_viscoelastic.png"
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)
    return fig_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "plot":       # redraw from the saved JSON only
        print(plot(json.loads((ROOT / "m3" / "out" / "ve_study.json").read_text(encoding="utf-8"))))
    else:
        main()
