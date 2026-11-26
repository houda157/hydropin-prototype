"""Oracles – scenarios, virtual sensors, dataset, MQTT (math note §2.7, §2.9, §3)."""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache

import numpy as np

from hydropin_sim.config import load_params
from hydropin_sim.contracts import Scenario, SensorMessage, SensorSeries
from hydropin_sim.network.generators import demo_farm_spec
from hydropin_sim.sensors import model as sm
from hydropin_sim.sensors.dataset import generate, nominal_shift_info
from hydropin_sim.sensors.stream import to_messages, to_mqtt
from hydropin_sim.steady.scenarios import (CLOG_BETA, ROUGHNESS_SCALE, TEMP_RANGE, ScenarioSampler,
                                       default_shifts)
from hydropin_sim.steady.solver import run_steady
from oracles.base import Check

P = load_params()
FARM = demo_farm_spec()
FS = sm.full_scale_m(P)


@lru_cache(maxsize=1)
def small_dataset():
    return generate(FARM, P, 120, seed=11)


def checks() -> list[Check]:
    c: list[Check] = []
    s = P.sensors
    rng = np.random.default_rng(0)
    sensor = sm.LowRateSensor("T", "J", gain=0.0, bias=0.0, drift_sign=1.0)
    n = 200_000
    t = np.arange(n, dtype=float)
    y = sensor.read(15.0, t, P, rng, temp_offset=np.zeros(n)).value
    ok = ~np.isnan(y)
    age = t / sm.SECONDS_PER_YEAR * s.DRIFT_YR.v * FS
    noise = y[ok] - 15.0 - age[ok]
    c.append(Check("3.1", "Sensor noise std = SIGMA_N × full scale", s.SIGMA_N.v * FS,
                   float(noise.std()), 0.02, "rel", "§3.1", "m"))
    loss = 1 - ok.mean()
    c.append(Check("3.2", "Packet-loss rate = LOSS_RATE (± 3σ binomial)", s.LOSS_RATE.v, float(loss),
                   3 * np.sqrt(s.LOSS_RATE.v * (1 - s.LOSS_RATE.v) / n), "abs", "§3.1"))
    dq = FS / 2 ** int(s.ADC_BITS.v)
    c.append(Check("3.3", "Every reading is a whole number of ADC steps", True,
                   bool(np.allclose(y[ok] / dq, np.round(y[ok] / dq), atol=1e-6)), kind="bool", ref="§3.1"))
    biases = np.array([sm.LowRateSensor.create("x", "J", P, rng).bias for _ in range(20000)])
    c.append(Check("3.4", "Bias spread across devices = ACC × F_S / 2", s.ACC.v * FS / 2,
                   float(biases.std()), 0.03, "rel", "§3.1", "m"))
    td = np.arange(0, 86400, 10.0)
    dT = sm.box_temperature(td, s.T_AMP.v)
    yt = sensor.read(15.0, td, P, rng, temp_offset=dT).value
    m = ~np.isnan(yt)
    basis = np.sin(2 * np.pi * (td[m] / 86400 - 0.25))
    amp = float(np.linalg.lstsq(np.c_[basis, np.ones(m.sum()), td[m]], yt[m], rcond=None)[0][0])
    c.append(Check("3.5", "Daily temperature drift amplitude = TEMPCO × F_S × T_AMP",
                   s.TEMPCO.v * FS * s.T_AMP.v, amp, 0.02, "rel", "§3.1", "m"))
    k = int(P.decision.N_AVG.v)
    yy = noise[: (len(noise) // k) * k].reshape(-1, k).mean(axis=1)
    c.append(Check("3.6", f"Averaging {k} readings divides the noise by √{k}", s.SIGMA_N.v * FS / np.sqrt(k),
                   float(yy.std()), 0.05, "rel", "§3.3", "m"))
    hand = np.sqrt((s.SIGMA_N.v * FS) ** 2 / k
                   + (s.TEMP_COMP_RESIDUAL.v * s.TEMPCO.v * FS * s.T_AMP.v / np.sqrt(2)) ** 2)
    c.append(Check("3.7", "σ_tot (compensated) = hand calculation of math note §3.3", float(hand),
                   sm.sigma_total(P), 1e-12, "rel", "§3.3", "m"))

    shifts = default_shifts(FARM)
    nominal = nominal_shift_info(FARM, P, shifts)
    info = {sh: v[0] for sh, v in nominal.items()}
    a = [ScenarioSampler(FARM, P, info, seed=5).sample(i).model_dump() for i in range(20)]
    b = [ScenarioSampler(FARM, P, info, seed=5).sample(i).model_dump() for i in range(20)]
    c.append(Check("3.8", "Same seed → identical scenarios (reproducibility)", True, a == b, kind="bool", ref="§2.9"))
    sampler = ScenarioSampler(FARM, P, info, seed=6)
    scs = [sampler.sample(i) for i in range(300)]
    cmax = P.emitters.C_CLOG.range[1]
    in_range = all(0 <= v <= cmax for sc in scs for v in sc.clogging.values()) and \
        all(ROUGHNESS_SCALE[0] <= v <= ROUGHNESS_SCALE[1] for sc in scs for v in sc.roughness_scale.values()) and \
        all(TEMP_RANGE[0] <= sc.water_temp <= TEMP_RANGE[1] for sc in scs)
    c.append(Check("3.9", "Every Monte Carlo draw stays inside its declared range", True, in_range,
                   kind="bool", ref="§2.9"))

    ds = small_dataset()
    leaky = ds["LEAK_KIND"] > 0
    c.append(Check("3.10", "Every sampled leak actually loses water (placed where water flows)", True,
                   bool(np.all(ds["LEAK_FLOW"][leaky] > 0)), kind="bool", ref="§2.9"))
    c.append(Check("3.11", "Healthy samples have zero leak flow", 0.0,
                   float(np.abs(ds["LEAK_FLOW"][~leaky]).max()), 1e-12, "abs", "§2.9", "m³/s"))
    c.append(Check("3.12", "Mass balance closes in every dataset sample (worst relative error)", 1e-5,
                   float(ds["MASS_ERR"].max()), kind="le", ref="§2.1"))
    sh = shifts[4]
    r = run_steady(FARM, Scenario(id="n", network="farm_demo", seed=0, open_sectors=list(sh), duration=1,
                                  timestep=1, water_temp=25.0), P)
    c.append(Check("3.13", "Unperturbed healthy farm = nominal twin (H_TRUE = H_MODEL)", 0.0,
                   float(np.max(np.abs(r.pressure[0] - nominal[sh][1]))), 1e-6, "abs", "§4.2", "m"))

    series = SensorSeries("P1", "S1", np.arange(5) * 60.0, np.array([15.0, np.nan, 15.2, 15.1, 14.9]))
    msgs = to_messages(series, "demo", dt.datetime(2026, 11, 17, 6, 0, tzinfo=dt.timezone.utc), [0, 1, 2, 3, 4])
    topic, payload = to_mqtt(msgs[0])
    back = SensorMessage(**json.loads(payload))
    c.append(Check("3.14", "MQTT JSON round trip gives the same message; lost packet not sent", True,
                   back == msgs[0] and len(msgs) == 4 and topic == "hydropin/demo/S1", kind="bool", ref="contracts"))
    c.append(Check("3.15", "Message pressure in bar × 10.197 = reading in m", 15.0, msgs[0].p_bar * sm.M_PER_BAR,
                   1e-5, "rel", "§3", "m"))
    return c
