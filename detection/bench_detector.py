"""Leak detector for the bench as built (rev 1): F0 flow + PT1 (branch A) + PT2 (branch B).

One message in, one *processed frame* out (contract/api.md). The same code runs live in the
backend, in scoring and in the replay export. It never reads labels or events.

Pipeline per sample (CONTEXT §4, role 4 brief):

1. quality gate: unplugged / out-of-range / stuck sensors, one pressure moving alone, data gaps;
2. pump state: PUMP_OFF (no flow) -> SETTLING (20 s) -> LEARNING (30 s healthy baseline);
3. methods
   - ``flow``: smoothed F0 above the learned baseline, in units of its noise (z-score);
   - ``m2``: the smoothed pressure change [dPT1, dPT2] scored against a healthy subspace learned by
     SVD of the baseline window (common-mode supply wander is "healthy"; what falls off it is not);
     the residual is matched against per-tap fingerprints for the branch;
4. fusion: weighted log-odds of the methods that pass the gate -> p_leak; p > tau1 WATCH,
   p > tau2 for N consecutive samples LEAK;
5. outputs: branch (A | B), loc {L1, L2, L3}, leak_lpm = F0 - baseline, lost_l (litres lost).

Branch is the promise; L2 vs L3 share branch B and one sensor, so they split B's probability.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from hydropin import config

STATES = ("PUMP_OFF", "SETTLING", "LEARNING", "HEALTHY", "WATCH", "LEAK", "OFFLINE")
TAPS = ("L1", "L2", "L3")
TAP_BRANCH = {"L1": "A", "L2": "B", "L3": "B"}


@dataclass
class BenchConfig:
    pump_on_lpm: float = 0.3          # F0 above this = pump running
    settle_s: float = 20.0
    learn_s: float = 30.0
    smooth_tau_s: float = 4.0         # EMA on F0, PT1, PT2
    # noise floors (bar, L/min): sensor noise + slow drift the baseline does not follow
    floor_p_bar: float = 0.008
    floor_cm_bar: float = 0.02        # extra allowance along the healthy (common-mode) direction
    floor_f_lpm: float = 0.05         # half a flow step (0.1 L/min at a 2 s window)
    # method -> log-odds: llr = w * (z - z0), clipped
    flow_w: float = 1.5
    flow_z0: float = 2.5
    m2_w: float = 1.0
    m2_z0: float = 2.5
    # In the fusion, M2 cannot vote *against* a leak just because it sees no pressure change:
    # a small leak raises the flow but barely moves the pressures. Its log-odds are floored at this
    # value unless the pressures actually rose (then it keeps its negative vote).
    m2_floor_llr: float = 0.0
    prior_logit: float = 0.0
    llr_clip: tuple[float, float] = (-3.0, 5.0)
    tau1: float = 0.5                 # WATCH
    tau2: float = 0.9                 # LEAK ...
    n_consecutive: int = 10           # ... for 10 samples (5 s at 2 Hz)
    adapt_tau_s: float = 600.0        # slow baseline follow while clearly healthy
    gap_s: float = 3.0                # no frame for 3 s -> OFFLINE
    stuck_s: float = 10.0             # identical raw ADC counts this long = frozen reading
    unplug_s: float = 3.0
    # unit drop direction in [PT1, PT2] for each tap (bench twin: L1 drops PT1 ~2x PT2;
    # L2/L3 drop PT2 more). Replace with measured fingerprints after the calibration runs.
    fingerprints: dict = field(default_factory=lambda: {"L1": [-2.0, -1.0], "L2": [-0.4, -1.0], "L3": [-0.4, -1.0]})
    loc_kappa: float = 8.0            # softmax sharpness on fingerprint cosine similarity
    pt1_range: tuple[float, float] = (0.0, 6.0)
    pt2_range: tuple[float, float] = (-1.0, 1.6)

    @classmethod
    def from_json(cls, path: str | Path) -> "BenchConfig":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        for k in ("llr_clip", "pt1_range", "pt2_range"):
            if k in d:
                d[k] = tuple(d[k])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)


# Trained model first (detection/train_bench.py, from the campaign's training split), then a
# hand-edited config; defaults when neither exists.
MODEL_PATHS = (Path("data/model.json"), Path("data/bench_detector.json"))


def load_config(path: str | Path | None = None) -> BenchConfig:
    """BenchConfig from `path`, else from the first file in MODEL_PATHS that exists, else defaults."""
    for cand in ([Path(path)] if path else list(MODEL_PATHS)):
        if cand.exists():
            return BenchConfig.from_json(cand)
    return BenchConfig()


def values_from_raw(msg: dict) -> dict:
    """The message's ``values`` with both pressures recomputed from the raw ADC counts.

    The firmware rounds bar to 0.01 (10 mbar), coarser than the sensor noise after
    oversampling: rounded values repeat for seconds and look "stuck". One ADC count is
    about 0.2 mbar. Messages without raw counts keep their values.
    """
    values = dict(msg["values"])
    raw = msg.get("raw") or {}
    if raw.get("pressure_adc") is not None:
        p1 = config.adc_to_pressure_bar(raw["pressure_adc"])
        values["pressure_bar"] = min(max(p1, config.PRESSURE_RANGE_BAR[0]), config.PRESSURE_RANGE_BAR[1])
    if raw.get("pressure_b_adc") is not None:
        p2 = config.adc_to_pressure_b_bar(raw["pressure_b_adc"])
        values["pressure_b_bar"] = min(max(p2, config.PRESSURE_B_RANGE_BAR[0]), config.PRESSURE_B_RANGE_BAR[1])
    return values


def _ts_seconds(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class BenchDetector:
    def __init__(self, cfg: BenchConfig | None = None):
        self.cfg = cfg or BenchConfig()
        fp = np.array([self.cfg.fingerprints[t] for t in TAPS], dtype=float)
        self._fp = fp / np.linalg.norm(fp, axis=1, keepdims=True)
        self._last_t: float | None = None
        self._last_ts = None
        self._last_frame: dict | None = None
        self.reset_baseline()
        self._mode = "PUMP_OFF"

    # ------------------------------------------------------------------ state
    def reset_baseline(self) -> None:
        """Forget the baseline and learn it again (after any valve change)."""
        self._mode = "SETTLING"
        self._mode_t0: float | None = None
        self._learn: list[tuple[float, float, float]] = []
        self.base: dict | None = None
        self._ema: np.ndarray | None = None
        self._above = 0
        self._leak_state = "HEALTHY"
        self.lost_l = 0.0
        self._stuck = {"PT1": [None, 0.0], "PT2": [None, 0.0]}
        self._low = {"PT1": 0.0, "PT2": 0.0}
        self._alone = 0.0

    # ------------------------------------------------------------------ helpers
    def _faults(self, f: float, p1: float, p2: float, t: float, dt: float, pump_on: bool) -> list[str]:
        c = self.cfg
        out = []
        # "unplugged" must persist: right after a pump stop the 2 s flow window still shows flow
        # while the pressures are already at zero
        low1 = pump_on and p1 < c.pt1_range[0] + 0.05
        low2 = p2 < c.pt2_range[0] + 0.1
        self._low["PT1"] = self._low["PT1"] + dt if low1 else 0.0
        self._low["PT2"] = self._low["PT2"] + dt if low2 else 0.0
        if self._low["PT1"] >= c.unplug_s:
            out.append("PT1_unplugged")
        elif p1 > c.pt1_range[1] - 0.05:
            out.append("PT1_out_of_range")
        if self._low["PT2"] >= c.unplug_s:
            out.append("PT2_unplugged")
        elif p2 > c.pt2_range[1] - 0.05:
            out.append("PT2_out_of_range")
        for name, v in (("PT1", p1), ("PT2", p2)):
            last, since = self._stuck[name]
            if last is not None and v == last:
                since += dt
            else:
                since = 0.0
            self._stuck[name] = [v, since]
            if pump_on and since >= c.stuck_s and f"{name}_unplugged" not in out:
                out.append(f"{name}_stuck")
        if dt > c.gap_s:
            out.append("data_gap")
        return out

    def _learn_baseline(self) -> dict:
        x = np.array(self._learn)                  # [n, 3] F, PT1, PT2
        mu = x.mean(axis=0)
        c = self.cfg
        p = x[:, 1:] - mu[1:]
        u = np.array([1.0, 1.0]) / math.sqrt(2.0)  # default healthy direction: common mode
        if len(p) >= 10:
            _, s, vt = np.linalg.svd(p, full_matrices=False)
            if s[0] > 2.0 * s[1] and abs(vt[0] @ u) > 0.8:   # clear, common-mode-like main axis
                u = vt[0] * np.sign(vt[0] @ u)
        cov = np.cov(p.T) if len(p) > 2 else np.zeros((2, 2))
        sigma = cov + c.floor_p_bar ** 2 * np.eye(2) + c.floor_cm_bar ** 2 * np.outer(u, u)
        return {"f": float(mu[0]), "p1": float(mu[1]), "p2": float(mu[2]),
                "sd_f": float(max(x[:, 0].std(), c.floor_f_lpm)),
                "u": u.tolist(), "sigma_inv": np.linalg.inv(sigma).tolist(), "n": int(len(x))}

    # ------------------------------------------------------------------ main
    def update(self, values: dict, ts) -> dict:
        """One telemetry ``values`` block (rev 1 contract) -> processed frame."""
        c = self.cfg
        t = _ts_seconds(ts)
        dt = c.smooth_tau_s / 8 if self._last_t is None else max(1e-3, t - self._last_t)
        self._last_t, self._last_ts = t, ts
        f = float(values.get("flow_main_lpm", 0.0))
        p1 = float(values.get("pressure_bar", 0.0))
        p2v = values.get("pressure_b_bar")
        p2 = float(p2v) if p2v is not None else float("nan")
        pump_on = f > c.pump_on_lpm
        faults = self._faults(f, p1, p2 if p2v is not None else 0.0, t, dt, pump_on)
        if p2v is None:
            faults = [x for x in faults if not x.startswith("PT2")] + ["PT2_missing"]
        # a pressure at its "unplugged" level is distrusted at once, reported once it persists
        p_bad = any(x.startswith(("PT1", "PT2")) for x in faults) or self._low["PT1"] > 0 or self._low["PT2"] > 0

        # pump state machine
        if not pump_on:
            if self._mode != "PUMP_OFF":
                self.reset_baseline()
            self._mode = "PUMP_OFF"
        elif self._mode == "PUMP_OFF":
            self._mode, self._mode_t0 = "SETTLING", t
        if self._mode_t0 is None:
            self._mode_t0 = t

        x = np.array([f, p1, p2 if p2v is not None else 0.0])
        if self._ema is None or dt > c.gap_s:
            self._ema = x.copy()
        else:
            a = min(1.0, dt / c.smooth_tau_s)
            self._ema = self._ema + a * (x - self._ema)

        frame = {"ts": ts, "pt1_bar": round(p1, 4), "pt2_bar": None if p2v is None else round(p2, 4),
                 "dp_bar": None if p2v is None else round(p1 - p2, 4), "flow_lpm": round(f, 3),
                 "flow_base_lpm": None, "state": self._mode, "p_leak": 0.0,
                 "methods": {"flow": {"score": None, "z": None, "quality": 1, "excluded": False},
                             "m2": {"score": None, "z": None, "quality": 0 if p_bad else 1, "excluded": p_bad}},
                 "faults": faults, "branch": None, "loc": {k: 0.0 for k in TAPS},
                 "leak_lpm": 0.0, "lost_l": round(self.lost_l, 3)}

        if self._mode == "SETTLING":
            if t - self._mode_t0 >= c.settle_s:
                self._mode, self._mode_t0 = "LEARNING", t
                self._learn = []
            frame["state"] = self._mode
            return self._finish(frame)
        if self._mode == "LEARNING":
            if not p_bad:
                self._learn.append((f, p1, p2))
            if t - self._mode_t0 >= c.learn_s and len(self._learn) >= 10:
                self.base = self._learn_baseline()
                self._mode = "RUN"
                self._ema = np.array([self.base["f"], self.base["p1"], self.base["p2"]])
            frame["state"] = "LEARNING" if self._mode == "LEARNING" else "HEALTHY"
            if self._mode == "LEARNING":
                return self._finish(frame)
        if self._mode == "PUMP_OFF":
            return self._finish(frame)

        # ---- running: methods
        b = self.base
        frame["flow_base_lpm"] = round(b["f"], 3)
        df = float(self._ema[0] - b["f"])
        z_f = df / b["sd_f"]
        llr = {}
        lo, hi = c.llr_clip
        llr["flow"] = float(np.clip(c.flow_w * (z_f - c.flow_z0), lo, hi))
        frame["methods"]["flow"].update(score=round(_sigmoid(llr["flow"]), 3), z=round(z_f, 2))

        d = np.array([self._ema[1] - b["p1"], self._ema[2] - b["p2"]])
        sim = None
        if not p_bad:
            z_m2 = float(math.sqrt(max(0.0, d @ np.array(b["sigma_inv"]) @ d)))
            if d.sum() > 0:                      # pressures rose: not a leak signature
                z_m2 = -z_m2
            raw = float(np.clip(c.m2_w * (z_m2 - c.m2_z0), lo, hi))
            frame["methods"]["m2"].update(score=round(_sigmoid(raw), 3), z=round(z_m2, 2))   # M2 alone
            llr["m2"] = max(raw, c.m2_floor_llr) if z_m2 >= 0 else raw                       # in the fusion
            nd = np.linalg.norm(d)
            if nd > 0:
                sim = self._fp @ (d / nd)        # cosine similarity per tap

        # one pressure moving alone while flow and the other are flat -> sensor fault, not a leak
        if not p_bad:
            zs = np.abs(d) / c.floor_p_bar
            if abs(z_f) < 1.5 and ((zs[0] > 8 and zs[1] < 2) or (zs[1] > 8 and zs[0] < 2)):
                self._alone += dt
            else:
                self._alone = 0.0
            if self._alone >= 5.0:
                name = "PT1_suspect" if zs[0] > zs[1] else "PT2_suspect"
                frame["faults"].append(name)
                frame["methods"]["m2"].update(quality=0, excluded=True)
                llr.pop("m2", None)
                sim = None

        p = _sigmoid(c.prior_logit + sum(llr.values()))
        frame["p_leak"] = round(p, 4)
        self._above = self._above + 1 if p > c.tau2 else 0
        if self._above >= c.n_consecutive:
            state = "LEAK"
        elif p > c.tau1:
            state = "WATCH" if self._leak_state != "LEAK" else "LEAK"
        else:
            state = "HEALTHY"
        if state == "LEAK" and p <= c.tau1:
            state = "HEALTHY"
        self._leak_state = state
        frame["state"] = state

        if state in ("WATCH", "LEAK"):
            frame["leak_lpm"] = round(max(0.0, df), 3)
            if state == "LEAK":
                self.lost_l += max(0.0, df) * dt / 60.0
            if sim is not None:
                w = np.exp(c.loc_kappa * sim)
                w = w / w.sum()
                frame["loc"] = {k: round(float(v), 3) for k, v in zip(TAPS, w)}
                pa = w[0]
                frame["branch"] = "A" if pa >= 0.5 else "B"
            else:
                frame["loc"] = {k: round(1 / 3, 3) for k in TAPS}
        elif p < 0.1 and not frame["faults"]:
            # follow slow drift while clearly healthy
            a = min(1.0, dt / c.adapt_tau_s)
            b["f"] += a * (self._ema[0] - b["f"])
            b["p1"] += a * (self._ema[1] - b["p1"])
            b["p2"] += a * (self._ema[2] - b["p2"])
        frame["lost_l"] = round(self.lost_l, 3)
        return self._finish(frame)

    def update_message(self, msg: dict) -> dict:
        frame = self.update(values_from_raw(msg), msg["ts"])
        frame["device"] = msg.get("device")
        frame["seq"] = msg.get("seq")
        return frame

    def _finish(self, frame: dict) -> dict:
        self._last_frame = frame
        return frame

    def state_at(self, now) -> dict | None:
        """Latest frame, marked OFFLINE when no message arrived for ``gap_s``."""
        if self._last_frame is None:
            return None
        fr = dict(self._last_frame)
        if _ts_seconds(now) - self._last_t > self.cfg.gap_s:
            fr["state"] = "OFFLINE"
        return fr


def run_messages(msgs: list[dict], cfg: BenchConfig | None = None) -> list[dict]:
    """Detector over a whole recorded run (replay export and scoring use this)."""
    det = BenchDetector(cfg)
    return [det.update_message(m) for m in msgs]
