"""Accuracy of the M3 locators vs sensor noise and wave-speed error (simulation).

    python -m m3.sweep   ->  m3/out/sweep.json, report/figures/m3_accuracy.png

The true pipe always has a = 350 m/s. In the wave-speed sweep, the *model* used by the
locators has a wrong a (the field value is only known after measuring it), which is the
main real-world error source (blueprint risk 2: "measure wave speed first").
The CNN will be added to the same comparison.
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
from m3.moc import leak_cda_for_fraction, load_setup  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Inside the covered zone: blind ~4 m at the sensor (a·Tc/2) and ~0.12·L at the reservoir
# end (first-round-trip window with a ±10 % wave-speed margin).
POSITIONS = [30.0, 50.0, 75.0, 100.0, 125.0, 140.0]
METHODS = ("tr", "tr_id", "mfp", "echo") + (("cnn", "cnn_cal") if MODEL_PATH.exists() else ())
_CAL: list = []      # the pipe model fitted on one leak-free valve test (set in main)
U_IDENTIFIED = 0.03   # window margin once the wave speed is identified from the trace
NOISE_M = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2]
A_ERR = [-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10]
SEEDS = 3
SIGMA_FOR_A_SWEEP = 0.02
LEAK_FRACTION = 0.05
FEW_METRES = 5.0


def _bank(a_err: float):
    base = load_setup()
    return a_err, mfp_bank(base.with_(a=base.a * (1 + a_err)))


def _evaluate(model, bank, x_true, sigma, seed):
    true = load_setup()
    true = true.with_(x_leak=x_true, leak_cda=leak_cda_for_fraction(true, LEAK_FRACTION, x_true))
    t, h = measure(true, sigma_m=sigma, rng=np.random.default_rng([seed, int(x_true * 10), int(sigma * 1e4)]))
    a_id = estimate_wave_speed(model, t, h)
    extra = ({"cnn": cnn_locate(model, t, h), "cnn_cal": cnn_locate(model, t, h, calibrated=_CAL[0])}
             if "cnn" in METHODS else {})
    return extra | {
        "x_true": x_true, "sigma_m": sigma, "seed": seed, "a_identified": a_id,
        "tr": time_reversal(model, t, h).x_est,
        "tr_id": time_reversal(model.with_(a=a_id), t, h, a_uncertainty=U_IDENTIFIED).x_est,
        "mfp": matched_field(model, t, h, bank=bank).x_est,
        "echo": echo_locate(model, t, h),
    }


def _summary(rows, key):
    out = {}
    for m in METHODS:
        groups = {}
        for r in rows:
            groups.setdefault(r[key], []).append(abs(r[m] - r["x_true"]))
        out[m] = {str(k): {"mae_m": float(np.mean(v)), "within_5m": float(np.mean(np.array(v) <= FEW_METRES))}
                  for k, v in sorted(groups.items())}
    return out


def main() -> None:
    t0 = time.time()
    base = load_setup()
    with mp.Pool(min(len(A_ERR), max(1, mp.cpu_count() - 1))) as pool:
        banks = dict(pool.map(_bank, A_ERR))
    print(f"replica banks: {time.time() - t0:.0f}s")
    t_c, h_c = measure(base.with_(duration=CAL_WINDOW_S + 0.01), sigma_m=0.05, rng=np.random.default_rng([20261125, 9, 0]))
    cal_model, cal_info = calibrate(base, t_c, h_c)
    _CAL.append(cal_model)
    print(f"calibration: {time.time() - t0:.0f}s", cal_info)

    noise_rows = [_evaluate(base, banks[0.0], x, s, k)
                  for s in NOISE_M for x in POSITIONS for k in range(SEEDS)]
    a_rows = []
    for e in A_ERR:
        model = base.with_(a=base.a * (1 + e))
        for x in POSITIONS:
            for k in range(SEEDS):
                r = _evaluate(model, banks[e], x, SIGMA_FOR_A_SWEEP, k)
                r["a_err"] = e
                a_rows.append(r)

    echo_amp = 0.23  # m, 5 % leak (m3/out/validation.json)
    result = {
        "simulation": True,
        "calibration": cal_info,
        "setup": {"L_m": base.L, "a_true_mps": base.a, "closure_ms": base.Tc * 1000, "fs_hz": 2000,
                  "leak_fraction": LEAK_FRACTION, "positions_m": POSITIONS, "seeds": SEEDS,
                  "echo_amplitude_m": echo_amp, "sigma_for_a_sweep_m": SIGMA_FOR_A_SWEEP},
        "noise": _summary(noise_rows, "sigma_m"),
        "wave_speed": _summary(a_rows, "a_err"),
        "rows": {"noise": noise_rows, "wave_speed": a_rows},
        "runtime_s": round(time.time() - t0, 1),
    }
    out = ROOT / "m3" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sweep.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    a_err_id = [abs(r["a_identified"] / base.a - 1) for r in noise_rows + a_rows]
    result["a_identified_rel_error"] = {"mean": float(np.mean(a_err_id)), "max": float(np.max(a_err_id))}
    (out / "sweep.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    labels = {"tr": "time reversal (assumed a)", "tr_id": "time reversal (a identified from trace)",
              "mfp": "matched-field (assumed a)", "echo": "echo (assumed a)",
              "cnn": "1D CNN, no calibration", "cnn_cal": "1D CNN, calibrated"}
    colors = {"tr": "#2d6fa3", "tr_id": "#1a9850", "mfp": "#e07b00", "echo": "#888", "cnn": "#8e44ad", "cnn_cal": "#c51b7d"}
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    for m in METHODS:
        s = result["noise"][m]
        xs = [float(k) for k in s]
        ax[0].plot(xs, [v["mae_m"] for v in s.values()], "o-", color=colors[m], label=labels[m])
        w = result["wave_speed"][m]
        ax[1].plot([100 * float(k) for k in w], [v["mae_m"] for v in w.values()], "o-", color=colors[m], label=labels[m])
    ax[0].set_xscale("symlog", linthresh=0.01)
    ax[0].set_xlabel("sensor noise σ (m of head)")
    ax[0].set_title(f"Error vs noise (echo ≈ {echo_amp} m, 5 % leak)", fontsize=10)
    ax[1].set_xlabel("wave-speed error in the model (%)")
    ax[1].set_title(f"Error vs wave-speed error (σ = {SIGMA_FOR_A_SWEEP} m)", fontsize=10)
    for a in ax:
        a.set_ylabel("mean |error| (m)")
        a.axhline(FEW_METRES, color="#c0392b", ls=":", lw=1, label="'a few metres' (5 m)")
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.text(0.01, 0.01, f"SIMULATION – 150 m PE pipe, a = 350 m/s, 25 ms closure, 2 kHz, "
             f"{len(POSITIONS)} positions x {SEEDS} noise draws", fontsize=8, color="#a00")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig_path = ROOT / "report" / "figures" / "m3_accuracy.png"
    fig.savefig(fig_path, dpi=150)
    for key in ("noise", "wave_speed"):
        print(key)
        for m in METHODS:
            print("  ", m, {k: round(v["mae_m"], 2) for k, v in result[key][m].items()})
    print(f"done in {result['runtime_s']}s -> m3/out/sweep.json, {fig_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
