"""Export M3 showcase cases for the dashboard's M3 tab (simulation).

    python -m m3.export_dashboard   ->  dashboard/m3/index.json + dashboard/m3/<case>.json   (~2 min)

Format: dashboard/m3/FORMAT.md. Every number is simulated (label it "Simulation" on screen).
Each case: one 150 m PE pipe, a 5 % leak, a 25 ms valve closure, 2 kHz sensor at the valve.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from m3.calibrate import CAL_WINDOW_S, calibrate, creep_scale, with_creep
from m3.cnn import MODEL_PATH, cnn_locate
from m3.locate import (FS, echo_locate, estimate_wave_speed, matched_field, measure, mfp_bank,
                       time_reversal)
from m3.moc import joukowsky_head, leak_cda_for_fraction, load_setup, simulate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "m3"
FORMAT_VERSION = "1.1"
LEAK_FRACTION = 0.05
SIGMA_M = 0.02            # sensor noise (m of head), a quiet 24-bit acquisition
FRAME_DT = 0.005          # s between animation frames
ANIM_S = 1.0              # animation length: closure + first round trip + reservoir return
N_X_ANIM = 121            # points along the pipe in the animation (every 1.25 m)
TRACE_S = 1.3             # sensor trace length shown

CASES = [
    {"id": "m3_case_01", "x": 35.0, "pipe": "elastic",
     "title": "Leak 115 m from the sensor", "story": "A far leak: its echo returns after 0.66 s."},
    {"id": "m3_case_02", "x": 90.0, "pipe": "elastic",
     "title": "Leak 60 m from the sensor", "story": "Mid-pipe leak: echo after 0.34 s, time reversal focuses on it."},
    {"id": "m3_case_03", "x": 135.0, "pipe": "elastic",
     "title": "Leak 15 m from the sensor", "story": "A near leak: the echo returns only 86 ms after the valve closes."},
    {"id": "m3_case_04", "x": 90.0, "pipe": "creep",
     "title": "PE pipe with creep, calibrated model",
     "story": "The plastic wall absorbs the wave; after one leak-free calibration test the leak is found again."},
]


def r(a, nd):
    return np.round(np.asarray(a, dtype=float), nd).tolist()


def export_case(case: dict, model_elastic, bank_elastic, cal_cache: dict) -> dict:
    elastic = load_setup(viscoelastic=False)
    true_pipe = with_creep(elastic, 1.0) if case["pipe"] == "creep" else elastic
    x = case["x"]
    true = true_pipe.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true_pipe, LEAK_FRACTION, x))
    seed = int(x * 10) + (7 if case["pipe"] == "creep" else 0)

    # 1. what the sensor records (noisy, 2 kHz)
    t, h = measure(true, sigma_m=SIGMA_M, rng=np.random.default_rng(seed))

    # 2. the model the locators use: elastic, or calibrated on a leak-free test of this pipe
    if case["pipe"] == "creep":
        if "creep" not in cal_cache:
            tc, hc = measure(true_pipe.with_(duration=CAL_WINDOW_S + 0.01), sigma_m=0.05, rng=np.random.default_rng(99))
            m, info = calibrate(elastic, tc, hc)
            cal_cache["creep"] = (m, info, mfp_bank(m))
        model, cal_info, bank = cal_cache["creep"]
        a_u = 0.03
    else:
        model, cal_info, bank, a_u = model_elastic, None, bank_elastic, 0.12

    # 3. the four locators
    tr = time_reversal(model, t, h, a_uncertainty=a_u)
    mf = matched_field(model, t, h, bank=bank, a_uncertainty=a_u)
    est = {"tr": tr.x_est, "mfp": mf.x_est, "echo": echo_locate(model, t, h, a_uncertainty=a_u)}
    if MODEL_PATH.exists():
        est["cnn"] = cnn_locate(elastic, t, h, calibrated=model if case["pipe"] == "creep" else None)
    a_id = estimate_wave_speed(elastic, t, h)
    x_actual = round(x / true.dx) * true.dx

    # 4. animation: pressure along the pipe over time (true pipe, no noise)
    sim = simulate(true.with_(duration=ANIM_S), frame_every_s=FRAME_DT)
    ix = np.round(np.linspace(0, true.N, N_X_ANIM)).astype(int)
    frames = sim.frames[:, ix]
    h_model = simulate(model.with_(x_leak=None, leak_cda=0.0, duration=TRACE_S + 0.01)).sampled(FS)[1]
    n_tr = int(TRACE_S * FS)
    step = 6                                                    # time-reversal curve every 1 m
    d_sensor = true.L - x_actual
    return {
        "version": FORMAT_VERSION, "simulation": True, "id": case["id"],
        "title": case["title"], "story": case["story"],
        "pipe": {"kind": case["pipe"], "length_m": true.L, "diameter_m": true.D, "wave_speed_mps": true.a,
                 "reservoir_head_m": true.H_res, "sensor_x_m": true.L, "valve_x_m": true.L,
                 "creep_scale": creep_scale(true_pipe), "note": "reservoir at x = 0, valve and sensor at x = L"},
        "leak": {"x_true_m": x_actual, "distance_from_sensor_m": d_sensor, "fraction_of_flow": LEAK_FRACTION,
                 "flow_lps": round(float(sim.q_leak[0]) * 1000, 4)},
        "valve": {"closure_start_s": true.t_close, "closure_time_s": true.Tc,
                  "joukowsky_m": round(joukowsky_head(true), 3)},
        "timing": {"echo_expected_s": round(true.t_close + 2 * d_sensor / true.a, 4),
                   "reservoir_return_s": round(true.t_close + 2 * true.L / true.a, 4)},
        "sensor": {"fs_hz": FS, "noise_sigma_m": SIGMA_M, "t0_s": 0.0, "dt_s": 1 / FS,
                   "H_m": r(h[:n_tr], 3), "model_H_m": r(h_model[:n_tr], 3)},
        "frames": {"dt_s": FRAME_DT, "t_s": r(sim.frame_t, 4), "x_m": r(sim.x[ix], 2), "H_m": r(frames, 2)},
        "tr": {"x_m": r(tr.x[::step], 2), "energy": r(tr.score[::step], 4), "x_est_m": round(tr.x_est, 2)},
        "mfp": {"x_m": r(mf.x, 1), "match": r(mf.score, 4), "x_est_m": round(mf.x_est, 2)},
        "estimates_m": {k: round(float(v), 2) for k, v in est.items()},
        "error_m": {k: round(abs(float(v) - x_actual), 2) for k, v in est.items()},
        "model": {"kind": "calibrated" if cal_info else "elastic, nominal", "wave_speed_mps": round(model.a, 2),
                  "darcy_f": round(model.f, 5), "creep_scale": round(creep_scale(model), 4),
                  "calibration": ({k: (round(v, 4) if isinstance(v, float) else v) for k, v in cal_info.items()}
                                  if cal_info else None)},
        "wave_speed_identified_mps": round(a_id, 2),
    }


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    elastic = load_setup(viscoelastic=False)
    bank_elastic = mfp_bank(elastic)
    cal_cache: dict = {}
    index = []
    for case in CASES:
        data = export_case(case, elastic, bank_elastic, cal_cache)
        path = OUT / f"{case['id']}.json"
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        index.append({"id": case["id"], "file": path.name, "title": case["title"], "story": case["story"],
                      "pipe": case["pipe"], "x_true_m": data["leak"]["x_true_m"],
                      "error_m": data["error_m"], "size_kb": round(path.stat().st_size / 1024)})
        print(f"{case['id']}: x={data['leak']['x_true_m']:.1f} m  errors {data['error_m']}  ({index[-1]['size_kb']} KB)")
    (OUT / "index.json").write_text(json.dumps({
        "version": FORMAT_VERSION, "simulation": True,
        "label": "Simulation: M3 pressure-wave method on a 150 m PE pipe (not measured on the bench)",
        "methods": {"tr": "time reversal", "mfp": "matched-field", "echo": "echo timing", "cnn": "1D CNN"},
        "cases": index}, indent=1), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
