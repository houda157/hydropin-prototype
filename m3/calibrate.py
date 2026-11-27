"""Pipe calibration from one leak-free valve test (M3 field procedure, simulation).

At installation, close the valve once while the pipe is known to be leak-free and record
the sensor. Fit the model's unknowns so its intact trace matches that recording:
  - wave speed `a` (elastic, instantaneous)
  - Darcy friction `f`
  - creep scale `s`: the creep compliances are s × the typical PE values in params.yaml
    (the retardation times stay fixed; s = 0 means an elastic wall)
The calibrated model is then used by every locator (time reversal, matched-field, CNN).

    python -m m3.calibrate   ->  m3/out/calibration.json  (accuracy over many simulated pipes)
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from m3.locate import FS, estimate_wave_speed, measure
from m3.moc import PipeSetup, load_setup, simulate

ROOT = Path(__file__).resolve().parent.parent
CAL_WINDOW_S = 1.3           # closure + first round trip + reservoir return + margin
TYPICAL = load_setup(viscoelastic=True)   # typical PE creep (params.yaml)


def with_creep(model: PipeSetup, s: float) -> PipeSetup:
    """model with creep = s × typical PE creep (s = 0: elastic)."""
    s = max(float(s), 0.0)
    if s == 0.0:
        return model.with_(ve_J=(), ve_tau=())
    return model.with_(ve_J=tuple(j * s for j in TYPICAL.ve_J), ve_tau=TYPICAL.ve_tau)


def creep_scale(model: PipeSetup) -> float:
    return float(sum(model.ve_J) / sum(TYPICAL.ve_J)) if model.viscoelastic else 0.0


def intact_trace(model: PipeSetup, n: int) -> np.ndarray:
    _, h = simulate(model.with_(x_leak=None, leak_cda=0.0, duration=CAL_WINDOW_S + 0.01)).sampled(FS)
    return h[:n]


def calibrate(base: PipeSetup, t: np.ndarray, h: np.ndarray) -> tuple[PipeSetup, dict]:
    """Fit (a, f, s) so the intact model reproduces a leak-free recording (t, h at 2 kHz).

    base gives the known geometry and operating point (L, D, H_res, V0, closure).
    Nelder-Mead on (a / a0, f / f0, s), starting from the wave speed read off the trace,
    nominal friction and typical creep.
    """
    n = min(len(h), int(CAL_WINDOW_S * FS))
    hh = np.asarray(h[:n], dtype=float)
    a0 = estimate_wave_speed(base.with_(ve_J=(), ve_tau=()), t, h)
    f0 = 0.02

    def model_of(p):
        a, f, s = a0 * p[0], f0 * abs(p[1]), abs(p[2])
        return with_creep(base.with_(a=a, f=max(f, 1e-4)), s)

    def cost(p):
        return float(np.mean((intact_trace(model_of(p), n) - hh) ** 2))

    starts = [np.array([1.0, 1.0, 1.0]), np.array([1.0, 1.0, 0.0])]
    best = None
    for x0 in starts:
        r = minimize(cost, x0, method="Nelder-Mead",
                     options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 400,
                              "initial_simplex": [x0, x0 + [0.03, 0, 0], x0 + [0, 0.3, 0], x0 + [0, 0, 0.3]]})
        if best is None or r.fun < best.fun:
            best = r
    m = model_of(best.x)
    info = {"a_mps": m.a, "f": m.f, "creep_scale": creep_scale(m),
            "rms_m": float(np.sqrt(best.fun)), "n_eval": int(best.nfev), "a_start_mps": a0}
    return m, info


# ----------------------------------------------------------------------------- accuracy study
N_PIPES = 48
SIGMA_M = 0.05


def _one(k):
    rng = np.random.default_rng([20261125, k])
    base = load_setup(viscoelastic=False)
    a = base.a * rng.uniform(0.9, 1.1)
    f = rng.uniform(0.015, 0.030)
    s = 0.0 if k % 4 == 0 else rng.uniform(0.0, 1.5)
    true = with_creep(base.with_(a=a, f=f), s)
    t, h = measure(true.with_(duration=CAL_WINDOW_S + 0.01), sigma_m=SIGMA_M,
                   rng=np.random.default_rng([20261125, 1, k]))
    m, info = calibrate(base, t, h)
    return {"k": k, "a_true": a, "f_true": f, "s_true": s, **info}


def main() -> None:
    t0 = time.time()
    with mp.Pool(max(1, mp.cpu_count() - 1)) as pool:
        rows = pool.map(_one, range(N_PIPES))
    a_err = np.array([r["a_mps"] / r["a_true"] - 1 for r in rows])
    f_err = np.array([r["f"] / r["f_true"] - 1 for r in rows])
    s_err = np.array([r["creep_scale"] - r["s_true"] for r in rows])
    res = {
        "simulation": True,
        "setup": {"n_pipes": N_PIPES, "sigma_m": SIGMA_M, "a_range": "350 x U(0.9, 1.1)",
                  "f_range": "U(0.015, 0.030)", "creep_scale_range": "0 (1 in 4 pipes) or U(0, 1.5)",
                  "window_s": CAL_WINDOW_S, "method": "Nelder-Mead on (a, f, creep scale), 2 starts"},
        "errors": {
            "a_rel": {"mean": float(a_err.mean()), "std": float(a_err.std()), "max_abs": float(np.abs(a_err).max())},
            "f_rel": {"mean": float(f_err.mean()), "std": float(f_err.std()), "max_abs": float(np.abs(f_err).max())},
            "creep_scale_abs": {"mean": float(s_err.mean()), "std": float(s_err.std()),
                                "max_abs": float(np.abs(s_err).max())},
        },
        "fit_rms_m": {"mean": float(np.mean([r["rms_m"] for r in rows])), "max": float(max(r["rms_m"] for r in rows))},
        "rows": rows, "runtime_s": round(time.time() - t0, 1),
    }
    out = ROOT / "m3" / "out" / "calibration.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("errors", "fit_rms_m", "runtime_s")}, indent=1))


FORM_CASES = [  # real creep with a different SHAPE than the model family (model-form error)
    ("other retardation times", (1e-10, 1e-10, 1e-10), (0.1, 1.0, 3.0)),
    ("two elements", (1.5e-10, 1.5e-10), (0.2, 2.0)),
]


def _form_case(case):
    from m3.locate import time_reversal
    from m3.moc import leak_cda_for_fraction
    name, J, tau = case
    base = load_setup(viscoelastic=False)
    true = base.with_(ve_J=J, ve_tau=tau)
    t, h = measure(true.with_(duration=CAL_WINDOW_S + 0.01), sigma_m=SIGMA_M, rng=np.random.default_rng(3))
    m, info = calibrate(base, t, h)
    errs = {}
    for x in (30.0, 50.0, 75.0, 100.0, 125.0, 140.0):
        tr = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, 0.05, x))
        tt, hh = measure(tr, sigma_m=SIGMA_M, rng=np.random.default_rng(int(x)))
        errs[str(x)] = round(abs(time_reversal(m, tt, hh).x_est - x), 3)
    return {"case": name, "true_J_per_Pa": list(J), "true_tau_s": list(tau), "calibrated": info,
            "tr_error_m_by_position": errs, "tr_mae_m": float(np.mean(list(errs.values())))}


def form_test() -> None:
    """Calibrate on pipes whose creep the model family cannot reproduce exactly, then locate."""
    with mp.Pool(len(FORM_CASES)) as pool:
        res = pool.map(_form_case, FORM_CASES)
    out = ROOT / "m3" / "out" / "calibration.json"
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    data["model_form_test"] = {"sigma_m": SIGMA_M, "leak_fraction": 0.05, "cases": res}
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    for r in res:
        print(r["case"], "fit rms %.3f m, creep scale %.2f, TR mean error %.2f m"
              % (r["calibrated"]["rms_m"], r["calibrated"]["creep_scale"], r["tr_mae_m"]), r["tr_error_m_by_position"])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "formtest":
        form_test()
    else:
        main()
