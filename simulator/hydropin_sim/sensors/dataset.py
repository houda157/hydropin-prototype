"""Synthetic dataset: Monte Carlo scenarios → steady twin → virtual sensors.

One sample = one decision window (default 60 one-minute readings) during one
irrigation shift, healthy or with one leak. Saved as a compressed .npz file.

Arrays (N samples, S sensors, T readings, V network nodes):
  X        (N, S, T)  sensor readings, pressure head in m (NaN = lost packet)
  Q        (N, T)     flow-meter readings at the pump, m3/s
  TEMP     (N, T)     sensor-box temperature offset ΔT, K (measured, for compensation)
  H_TRUE   (N, S)     exact pressure head at the sensors, m
  H_MODEL  (N, S)     nominal digital-twin prediction for the same shift, m
  P_NODES  (N, V)     exact pressure head at every network node, m
  Q_TRUE, LEAK_FLOW (N,)   m3/s
  SHIFT    (N,)       index into `shifts`
  LEAK_KIND (N,)      0 none, 1 pipe, 2 lateral
  LEAK_ID  (N,)       pipe id (kind 1) or block node id (kind 2), '' if none
  LEAK_XY  (N, 2)     leak coordinates in m (NaN if none)
  X_BASE, Q_BASE, TEMP_BASE   the same farm state WITHOUT leak, on another day of the
                      same shift (water temperature ± BASE_TEMP_SD, new time of day and
                      noise): the "last healthy irrigation" a deployed system compares to
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import NetworkSpec, Scenario
from hydropin_sim.sensors.model import LowRateSensor, box_temperature, read_flow
from hydropin_sim.steady.scenarios import ScenarioSampler, ShiftInfo, default_shifts
from hydropin_sim.steady.solver import run_steady

FARM_SENSORS = ("HEAD", "S1", "B13", "S2", "B23", "S3", "B33", "S4", "B43")
BASE_TEMP_SD = 2.0      # degC, water-temperature change between the baseline day and today


def nominal_shift_info(spec: NetworkSpec, P: Params, shifts: Sequence[tuple[str, ...]],
                       temp: float = 25.0) -> dict[tuple[str, ...], tuple[ShiftInfo, np.ndarray, list[str]]]:
    """Healthy, unperturbed twin for every shift: nominal flow, mean block pressure, node pressures."""
    out = {}
    for sh in shifts:
        r = run_steady(spec, Scenario(id="nominal", network=spec.name, seed=0, open_sectors=list(sh),
                                      duration=1, timestep=1, water_temp=temp), P)
        ix = {n: i for i, n in enumerate(r.node_ids)}
        blocks = [b for s in spec.sectors if s.id in sh for b in s.lateral_blocks]
        h_nom = float(np.mean([r.pressure[0, ix[b]] for b in blocks]))
        out[sh] = (ShiftInfo(sh, float(r.pump_flow[0]), h_nom), r.pressure[0], r.node_ids)
    return out


def leak_xy(spec: NetworkSpec, sc: Scenario) -> tuple[float, float]:
    if not sc.leaks:
        return (np.nan, np.nan)
    lk = sc.leaks[0]
    xy = {n.id: (n.x, n.y) for n in spec.nodes}
    p = next(p for p in spec.pipes if p.id == lk.pipe)
    (x1, y1), (x2, y2) = xy[p.start], xy[p.end]
    return (x1 + lk.position * (x2 - x1), y1 + lk.position * (y2 - y1))


def generate(spec: NetworkSpec, P: Params, n: int, seed: int,
             sensor_nodes: Sequence[str] = FARM_SENSORS, window: int = 60,
             leak_prob: float = 0.5, shifts: Optional[Sequence[tuple[str, ...]]] = None,
             verbose: bool = False) -> dict:
    shifts = list(shifts or default_shifts(spec))
    nominal = nominal_shift_info(spec, P, shifts)
    info = {sh: v[0] for sh, v in nominal.items()}
    node_order = [nid for nid in nominal[shifts[0]][2]]
    rng = np.random.default_rng(seed)
    sampler = ScenarioSampler(spec, P, info, seed=seed, leak_prob=leak_prob)
    sensors = [LowRateSensor.create(f"P{k}", nid, P, rng) for k, nid in enumerate(sensor_nodes)]
    S, V = len(sensors), len(node_order)
    out = dict(X=np.empty((n, S, window), np.float32), Q=np.empty((n, window), np.float32),
               TEMP=np.empty((n, window), np.float32), H_TRUE=np.empty((n, S), np.float32),
               H_MODEL=np.empty((n, S), np.float32), P_NODES=np.empty((n, V), np.float32),
               Q_TRUE=np.empty(n), LEAK_FLOW=np.empty(n), SHIFT=np.empty(n, np.int16),
               LEAK_KIND=np.zeros(n, np.int8), LEAK_ID=np.empty(n, dtype="<U12"),
               LEAK_XY=np.full((n, 2), np.nan), T0=np.empty(n), MASS_ERR=np.empty(n),
               X_BASE=np.empty((n, S, window), np.float32), Q_BASE=np.empty((n, window), np.float32),
               TEMP_BASE=np.empty((n, window), np.float32))
    t_start = time.time()
    for i in range(n):
        sc = sampler.sample(i)
        r = run_steady(spec, sc, P)
        ix = {nid: k for k, nid in enumerate(r.node_ids)}
        h_true = np.array([r.pressure[0, ix[s.node_id]] for s in sensors])
        sh = tuple(sc.open_sectors)
        nom_p, nom_ids = nominal[sh][1], nominal[sh][2]
        nix = {nid: k for k, nid in enumerate(nom_ids)}
        h_model = np.array([nom_p[nix[s.node_id]] for s in sensors])
        t0 = float(rng.uniform(0, 86400 - 60 * window))
        t = t0 + 60.0 * np.arange(window)
        dT = box_temperature(t, P.sensors.T_AMP.v)
        for k, s in enumerate(sensors):
            out["X"][i, k] = s.read(h_true[k], t, P, rng, temp_offset=dT).value
        out["Q"][i] = read_flow(np.full(window, r.pump_flow[0]), rng, P)
        out["TEMP"][i] = dT
        out["H_TRUE"][i], out["H_MODEL"][i] = h_true, h_model
        out["P_NODES"][i] = [r.pressure[0, ix[nid]] for nid in node_order]
        out["Q_TRUE"][i], out["LEAK_FLOW"][i] = r.pump_flow[0], r.leak_flow[0]
        out["SHIFT"][i] = shifts.index(sh)
        out["T0"][i] = t0
        dem = r.meta["demand"][0]
        out["MASS_ERR"][i] = abs(r.pump_flow[0] - sum(dem[k] for nid, k in ix.items()
                                                       if nid not in {nn.id for nn in spec.nodes if nn.kind.value == "source"})) / r.pump_flow[0]
        # paired baseline: same farm state, no leak, another day of the same shift
        temp_b = float(np.clip(sc.water_temp + rng.normal(0, BASE_TEMP_SD), 10.0, 40.0))
        rb = run_steady(spec, sc.model_copy(update=dict(leaks=[], water_temp=temp_b)), P)
        ixb = {nid: k for k, nid in enumerate(rb.node_ids)}
        tb0 = float(rng.uniform(0, 86400 - 60 * window))
        tb = tb0 + 60.0 * np.arange(window)
        dTb = box_temperature(tb, P.sensors.T_AMP.v)
        for k, s in enumerate(sensors):
            out["X_BASE"][i, k] = s.read(rb.pressure[0, ixb[s.node_id]], tb, P, rng, temp_offset=dTb).value
        out["Q_BASE"][i] = read_flow(np.full(window, rb.pump_flow[0]), rng, P)
        out["TEMP_BASE"][i] = dTb
        if sc.leaks:
            lk = sc.leaks[0]
            lateral = lk.position >= 1.0
            out["LEAK_KIND"][i] = 2 if lateral else 1
            out["LEAK_ID"][i] = next(p.end for p in spec.pipes if p.id == lk.pipe) if lateral else lk.pipe
            out["LEAK_XY"][i] = leak_xy(spec, sc)
        else:
            out["LEAK_ID"][i] = ""
        if verbose and (i + 1) % 250 == 0:
            print(f"  {i + 1}/{n} scenarios ({time.time() - t_start:.0f} s)")
    out["shifts"] = np.array(["+".join(s) for s in shifts])
    out["sensor_nodes"] = np.array(list(sensor_nodes))
    out["node_order"] = np.array(node_order)
    out["sensor_bias"] = np.array([s.bias for s in sensors])
    out["sensor_gain"] = np.array([s.gain for s in sensors])
    out["seed"] = np.array(seed)
    return out


def save(ds: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **ds)
    return path


def load(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}
