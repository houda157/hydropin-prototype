"""The prototype's real measurement chain, simulated part by part. Math note §10.3–10.5.

Pressure (P1, P2):  Swagelok S transducer (−1 … 1.6 bar → 0–10 V, or 4–20 mA)
                    → 20 kΩ / 10 kΩ divider (or 150 Ω shunt) → ADS1115 (PGA ±4.096 V,
                    DR shared by the channels) → ESP32 firmware (× 3.0, bar formula, 1 s mean).
Flow (F0):          brass Hall sensor, f = K_F Q + f_0 pulses/s → ESP32 edge counter
                    over T_w → Q̂ = n / (K_fw T_w).
Hydraulic inputs:   steady board states (steady.board), pump ripple at f_r, slow wander of
                    the 12 V adapter (Ornstein–Uhlenbeck), lab temperature swing.

The ADC conversion is a boxcar mean over 1/DR (first-order model of the ADS1115
digital filter); ripple and sensor lag are applied analytically (exact for a sine),
so no sub-millisecond grid is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

import numpy as np

from hydropin_sim.config import Params
from hydropin_sim.contracts import SensorSeries
from hydropin_sim.network.prototype import BoardSetting
from hydropin_sim.sensors.model import box_temperature
from hydropin_sim.steady.board import LPM, M_PER_BAR, BoardState, run_board

SECONDS_PER_YEAR = 3.15576e7


# ════════════════════════════════════════════════════════════════════════════
# Hydraulic inputs seen by the sensors
# ════════════════════════════════════════════════════════════════════════════

def ou_process(t, sigma, tau, rng: np.random.Generator):
    """Stationary Ornstein–Uhlenbeck process, exact discretisation. Math note §10.3."""
    t = np.asarray(t, dtype=float)
    x = np.empty_like(t)
    x[0] = rng.normal(0.0, sigma)
    for k in range(1, len(t)):
        a = np.exp(-(t[k] - t[k - 1]) / tau)
        x[k] = a * x[k - 1] + sigma * np.sqrt(1 - a * a) * rng.normal()
    return x


def speed_sensitivity(P: Params, setting: BoardSetting, ds: float = 0.01) -> dict:
    """∂(p_i, Q_F0)/∂s by central difference on the twin (s = V_supply / V_nom). Math note §10.3."""
    b = P.prototype
    v0 = setting.v_supply if setting.v_supply is not None else b.PB_V_SUPPLY.v
    out = {}
    states = []
    for sgn in (+1, -1):
        st = BoardSetting(theta=setting.theta, leak_d=setting.leak_d,
                          v_supply=v0 * (1 + sgn * ds), water_temp=setting.water_temp)
        states.append(run_board(P, st))
    for s in ("P1", "P2"):
        out[s] = (states[0].p_sensor[s] - states[1].p_sensor[s]) / (2 * ds)
    out["F0"] = (states[0].q_f0 - states[1].q_f0) / (2 * ds)
    return out


@dataclass
class Segment:
    """A period during which the hand setting does not change."""
    t_start: float
    state: BoardState
    sens: dict          # speed sensitivities of this state


def timeline(P: Params, schedule: Sequence[tuple[float, BoardSetting]]) -> list[Segment]:
    """Solve the twin once per setting of a schedule [(t_start, setting), ...]."""
    segs = []
    for t0, st in schedule:
        segs.append(Segment(float(t0), run_board(P, st), speed_sensitivity(P, st)))
    return segs


def _segment_index(segs: list[Segment], t):
    starts = np.array([s.t_start for s in segs])
    return np.clip(np.searchsorted(starts, np.asarray(t, dtype=float), side="right") - 1, 0, len(segs) - 1)


def true_pressure(segs, sensor: str, t, s_dev):
    """Slow (sub-Hz) pressure head at the diaphragm: steady value + pump-speed wander. Math note §10.3."""
    idx = _segment_index(segs, t)
    base = np.array([segs[i].state.p_sensor[sensor] for i in idx])
    sens = np.array([segs[i].sens[sensor] for i in idx])
    return base + sens * s_dev


def true_flow(segs, t, s_dev):
    idx = _segment_index(segs, t)
    base = np.array([segs[i].state.q_f0 for i in idx])
    sens = np.array([segs[i].sens["F0"] for i in idx])
    return base + sens * s_dev


# ════════════════════════════════════════════════════════════════════════════
# Pressure chain: Swagelok → divider → ADS1115 → firmware
# ════════════════════════════════════════════════════════════════════════════

def sinc(x):
    return np.sinc(x)          # numpy: sin(πx)/(πx)


def ripple_seen(t_end, amp, f, phase, tau, t_conv):
    """Ripple after the sensor lag τ and the ADC boxcar over t_conv, for a conversion that
    ends at t_end (exact for a sine). Math note §10.4."""
    w = 2 * np.pi * f
    gain = 1.0 / np.sqrt(1.0 + (w * tau) ** 2) * sinc(f * t_conv)
    lag = np.arctan(w * tau)
    return amp * gain * np.sin(w * (np.asarray(t_end) - t_conv / 2) + phase - lag)


@dataclass
class PressureChain:
    """One physical pressure channel: sensor + its interface resistors + ADS1115 input."""
    sensor_id: str
    output: Literal["voltage", "current"]
    gamma: float         # sensor gain error (fraction)
    bias: float          # sensor zero error (fraction of span)
    drift_sign: float
    r_top: float         # Ω, as built (tolerance drawn)
    r_bot: float
    r_shunt: float
    adc_gain: float
    adc_offset_lsb: float
    ripple_phase: float
    channel: int = 0

    @classmethod
    def create(cls, sensor_id: str, P: Params, rng: np.random.Generator,
               output: Literal["voltage", "current"] = "voltage", channel: int = 0) -> "PressureChain":
        b = P.prototype
        tol = b.DIV_TOL.v
        return cls(sensor_id, output,
                   gamma=float(rng.normal(0.0, b.PS_ACC.v / 2)),
                   bias=float(rng.normal(0.0, b.PS_ACC.v / 2)),
                   drift_sign=float(rng.choice([-1.0, 1.0])),
                   r_top=b.DIV_R_TOP.v * (1 + rng.uniform(-tol, tol)),
                   r_bot=b.DIV_R_BOT.v * (1 + rng.uniform(-tol, tol)),
                   r_shunt=b.CL_R_SHUNT.v * (1 + rng.uniform(-tol, tol)),
                   adc_gain=float(rng.normal(0.0, b.ADS_GAIN_ERR.v)),
                   adc_offset_lsb=float(rng.normal(0.0, b.ADS_OFFSET_LSB.v)),
                   ripple_phase=float(rng.uniform(0, 2 * np.pi)),
                   channel=channel)

    # -- pieces, each one testable on its own ------------------------------------------------
    @staticmethod
    def span_fraction(p_bar, P: Params):
        b = P.prototype
        return (np.asarray(p_bar, dtype=float) - b.PS_P_MIN.v) / (b.PS_P_MAX.v - b.PS_P_MIN.v)

    def divider_ratio(self, P: Params) -> float:
        """k = R2' / (R1 + R2'),  R2' = R2 ∥ Z_in. Math note §10.4."""
        z = P.prototype.ADS_Z_IN.v
        r2 = self.r_bot * z / (self.r_bot + z)
        return r2 / (self.r_top + r2)

    def sensor_output(self, u_meas, P: Params):
        """Transducer output (V on the ADC side of the divider/shunt), saturating at its range."""
        b = P.prototype
        u = np.clip(u_meas, 0.0, 1.0)
        if self.output == "voltage":
            return b.PS_V_MAX.v * u * self.divider_ratio(P)
        return (4e-3 + 16e-3 * u) * self.r_shunt

    def adc(self, v_in, P: Params, rng: np.random.Generator):
        """ADS1115 conversion: gain/offset error, noise, clipping, 16-bit code. Math note §10.4."""
        b = P.prototype
        lsb = 2 * b.ADS_FSR.v / 2 ** int(b.ADS_BITS.v)
        v = ((1 + self.adc_gain) * np.asarray(v_in, dtype=float) + self.adc_offset_lsb * lsb
             + rng.normal(0.0, b.ADS_NOISE.v, size=np.shape(v_in)))
        v = np.clip(v, -b.ADS_FSR.v, min(b.ADS_FSR.v, b.ADS_VDD.v))
        return np.round(v / lsb).astype(int), lsb

    def firmware(self, code, lsb, P: Params):
        """The team's formulas: V_s = FW_DIV_FACTOR (3.0 on rev 1) × V_adc; p = −1 + (V_s / 10) × 2.6 (bar). Math note §10.4."""
        b = P.prototype
        v_adc = np.asarray(code) * lsb
        span = b.PS_P_MAX.v - b.PS_P_MIN.v
        if self.output == "voltage":
            return b.PS_P_MIN.v + b.FW_DIV_FACTOR.v * v_adc / b.PS_V_MAX.v * span
        return b.PS_P_MIN.v + (v_adc / b.CL_R_SHUNT.v - 4e-3) / 16e-3 * span

    # -- full chain ---------------------------------------------------------------------------
    def read(self, segs, t_end, s_dev, P: Params, rng: np.random.Generator, n_channels: int = 2,
             with_ripple: bool = True, age_years: float = 0.0) -> SensorSeries:
        """Raw ADS1115 conversions ending at t_end (s): returns firmware pressure in m of water."""
        b = P.prototype
        t_conv = 1.0 / b.ADS_DR.v
        h = true_pressure(segs, self.sensor_id, np.asarray(t_end) - t_conv / 2, s_dev)
        if with_ripple:
            # the motor speed follows the supply: ripple phase = 2π f_r ∫ s dt (time warped by δs)
            te = np.asarray(t_end, dtype=float)
            sd = np.broadcast_to(np.asarray(s_dev, dtype=float), te.shape)
            warp = np.concatenate([[0.0], np.cumsum(0.5 * (sd[1:] + sd[:-1]) * np.diff(te))])
            h = h + ripple_seen(te + warp, b.PB_RIPPLE_M.v, b.PB_F_RIPPLE.v, self.ripple_phase,
                                b.PS_TAU.v, t_conv)
        p_bar = h / M_PER_BAR
        dT = box_temperature(t_end, b.PB_T_AMP_LAB.v)
        age = age_years + np.asarray(t_end) / SECONDS_PER_YEAR
        u = ((1 + self.gamma) * self.span_fraction(p_bar, P) + self.bias + b.PS_TEMPCO.v * dT
             + self.drift_sign * b.PS_DRIFT_YR.v * age
             + rng.normal(0.0, b.PS_SIGMA_N.v, size=np.shape(p_bar)))
        code, lsb = self.adc(self.sensor_output(u, P), P, rng)
        p_hat = self.firmware(code, lsb, P)
        return SensorSeries(self.sensor_id, self.sensor_id, np.asarray(t_end, dtype=float),
                            p_hat * M_PER_BAR, meta=dict(code=code, lsb=lsb, p_true=h,
                                                         saturated=bool(np.any(u > 1) or np.any(u < 0))))


def conversion_times(duration, P: Params, channel: int, n_channels: int = 2, t0: float = 0.0):
    """End times of the conversions of one channel when the ADS1115 reads n channels in turn."""
    dr = P.prototype.ADS_DR.v
    k = np.arange(int(duration * dr / n_channels))
    return t0 + (k * n_channels + channel + 1) / dr


def firmware_average(series: SensorSeries, P: Params) -> SensorSeries:
    """ESP32 publishes the mean of the conversions of each T_fw window (one value per window)."""
    t_avg = P.prototype.FW_T_AVG.v
    w = np.floor(series.time / t_avg).astype(int)
    keys = np.unique(w)
    vals = np.array([series.value[w == k].mean() for k in keys])
    return SensorSeries(series.sensor_id, series.node_id, (keys + 1) * t_avg, vals,
                        meta=dict(n_per_window=float(np.mean([np.sum(w == k) for k in keys]))))


# ════════════════════════════════════════════════════════════════════════════
# Flow chain: Hall sensor → ESP32 pulse counter
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class FlowReading:
    """What the ESP32 reports for F0: one value per counting window (flow in m3/s)."""
    time: np.ndarray       # end of each window (s)
    q_hat: np.ndarray      # m3/s, as computed by the firmware
    counts: np.ndarray     # pulses in each window
    q_true: np.ndarray     # m3/s, true mean flow of each window


@dataclass
class HallFlowMeter:
    k_dev: float          # pulses/s per L/min of THIS device
    f_off: float          # Hz
    phase0: float         # fraction of a pulse at t = 0

    @classmethod
    def create(cls, P: Params, rng: np.random.Generator) -> "HallFlowMeter":
        b = P.prototype
        return cls(k_dev=b.FM_K.v * (1 + rng.normal(0.0, b.FM_ACC.v / 2)), f_off=b.FM_F_OFF.v,
                   phase0=float(rng.uniform()))

    def frequency(self, q_m3s):
        """f = max(0, K_F Q[L/min] + f_0). Math note §10.5."""
        return np.maximum(0.0, self.k_dev * np.asarray(q_m3s, dtype=float) * LPM + self.f_off)

    def read(self, segs, duration, s_fun, P: Params, rng: np.random.Generator,
             k_fw: Optional[float] = None, f0_fw: float = 0.0) -> FlowReading:
        """Pulses counted in successive windows T_w; Q̂ = (n / T_w − f0_fw) / K_fw (L/min → m3/s).
        s_fun(t) gives the pump-speed wander at time t. Math note §10.5."""
        b = P.prototype
        tw = b.FM_T_WIN.v
        k_fw = b.FM_K_FW.v if k_fw is None else k_fw
        n_win = int(duration / tw)
        t_mid = (np.arange(n_win) + 0.5) * tw
        q = true_flow(segs, t_mid, s_fun(t_mid))
        f = self.frequency(q) * (1 + rng.normal(0.0, b.FM_JITTER.v, size=n_win))
        phase = self.phase0 + np.concatenate([[0.0], np.cumsum(np.maximum(f, 0.0) * tw)])
        counts = np.diff(np.floor(phase)).astype(int)
        q_hat = (counts / tw - f0_fw) / k_fw / LPM
        return FlowReading((np.arange(n_win) + 1) * tw, q_hat, counts, q)
