"""Synthetic M3 experiments: MOC 'measurement' + high-rate sensor → time-reversal localisation."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import numpy as np

from hydropin_sim.contracts import LeakSpec
from hydropin_sim.methods.m3_timereversal import localise
from hydropin_sim.physics.friction import friction_factor
from hydropin_sim.sensors.model import HighRateSensor
from hydropin_sim.transient.frequency import LineModel
from hydropin_sim.transient.moc import Options, run
from oracles.transient_cases import L_RPV, P, close, rpv_spec, setup

T0 = 0.05
CLOSURE = 0.10
T_CLOSE = 0.01
H_RES = 25.0


@lru_cache(maxsize=64)
def simulate(x_leak: Optional[float], area: float = 3e-6, viscoelastic: bool = False, duration: float = 1.0):
    """MOC 'truth' for a leak at x_leak (None = healthy), unsteady friction on."""
    spec = rpv_spec(h_res=H_RES)
    leaks = [LeakSpec(pipe="P1", position=x_leak / L_RPV, area=area)] if x_leak is not None else []
    m, st = setup(spec, leaks, dt_max=1e-4)
    ev = close(m, t_start=T0, closure=CLOSURE, t_close=T_CLOSE)
    r = run(m, Options(duration=duration, record=["END"], unsteady=True, viscoelastic=viscoelastic), [ev])
    return r, st, m, ev


def effective_noise() -> float:
    """σ_HF / √N_p: one averaged test (math note §5.9)."""
    return P.sensors.SIGMA_HF.v / np.sqrt(P.sensors.N_PULSES.v)


def measure(x_leak: Optional[float], area: float = 3e-6, viscoelastic: bool = False,
            noise_m: Optional[float] = None, seed: int = 0, duration: float = 1.0):
    """High-rate sensor record of the averaged test: returns (t, y, u, steady, model, event)."""
    r, st, m, ev = simulate(x_leak, area, viscoelastic, duration)
    noise_m = effective_noise() if noise_m is None else noise_m
    rng = np.random.default_rng(seed)
    sensor = HighRateSensor.create("HF1", "END", P, rng)
    ser = sensor.read(r.time, r.head[:, 0], P, rng, duration=duration, noise_m=noise_m)
    six = {n: i for i, n in enumerate(st.node_ids)}
    h_v = st.pressure[0, six["END"]]
    u = np.array([(ev.coeff(t) - ev.c0) * np.sqrt(h_v) for t in ser.time])
    return ser.time, ser.value, u, st, m, ev


def line_model(st, ev, viscoelastic: bool = False, a: Optional[float] = None) -> LineModel:
    from hydropin_sim.physics.waves import pipe_wave_speed
    d_out, e = 0.063, 0.063 / 11
    d = d_out - 2 * e
    a_el = pipe_wave_speed(P, "PE100", d, e) if a is None else a
    six = {n: i for i, n in enumerate(st.node_ids)}
    h_v = st.pressure[0, six["END"]]
    q0 = float(st.pump_flow[0]) if st.pump_flow[0] > 0 else float(np.abs(st.flow[0]).max())
    area = np.pi * d ** 2 / 4
    f = float(friction_factor(abs(q0) / area * d / P.nu_w(), P.material("PE100").EPS_R.v, d)[0])
    c_final = ev.coeff(1e9)
    mat = P.material("PE100")
    return LineModel(length=L_RPV, d=d, a=a_el, r_lin=f * abs(q0) / (P.water.G.v * d * area ** 2),
                     y_valve=c_final / (2 * np.sqrt(h_v)), y_up=None, g=P.water.G.v, rho=P.water.RHO_W.v,
                     k_w=P.water.K_W.v, c1_d_over_e=P.pipes.C1.v * d / e,
                     j_k=tuple(mat.J_K.v) if viscoelastic else (), tau_k=tuple(mat.TAU_K.v) if viscoelastic else ())


def experiment(x_leak, area=3e-6, viscoelastic=False, model_viscoelastic=None, noise_m=None, seed=0):
    noise_m = effective_noise() if noise_m is None else noise_m
    t, y, u, st, m, ev = measure(x_leak, area, viscoelastic, noise_m, seed)
    mv = viscoelastic if model_viscoelastic is None else model_viscoelastic
    lm = line_model(st, ev, mv)
    res = localise(t, y, T0, u, lm, noise_sd=max(noise_m, 1e-4), tau_sensor=P.sensors.TAU_SENS.v)
    return res, st, lm, (t, y, u)
