"""Method-of-characteristics (MOC) transient solver for one pipe (M3, simulation only).

    reservoir (H = H_res) ── pipe, length L, wave speed a ── leak at x_L ── fast valve (sensor)

Equations, with B = a / (g A), R = f dx / (2 g D A^2), dt = dx / a (Courant = 1):

    C+ : H_P = C_P - B Q_P,   C_P = H[i-1] + B Q[i-1] - R Q[i-1] |Q[i-1]|
    C- : H_P = C_M + B Q_P,   C_M = H[i+1] - B Q[i+1] + R Q[i+1] |Q[i+1]|

Boundaries
    reservoir : H_P = H_res
    valve     : Q_P = tau(t) Cv sqrt(H_P)          (quadratic in sqrt(H_P) with C+)
    leak node : Q_up - Q_down = Cd A_L sqrt(2 g H_P),  H_P = C_P - B Q_up = C_M + B Q_down

Heads are pressure heads above a horizontal pipe. Steady friction only (quasi-steady);
no column separation (check `min_head` in the result).

Optional pipe-wall viscoelasticity (PE creep), Kelvin-Voigt elements k = 1..K
(generalised Kelvin-Voigt model, as in Covas et al. 2005):
    continuity gains a retarded-strain term  ... + (2 a^2 / g) d(eps_r)/dt = 0,
    eps_r = sum_k eps_k,   tau_k d(eps_k)/dt + eps_k = J_k * c * (H - H0),   c = alpha rho g D / (2 e)
Along both characteristics this adds  - kv * eps_r'  with kv = 2 a^2 dt / g, so
    H_P = (C_P + C_M)/2 - kv eps_r',   Q_P unchanged = (C_P - C_M) / (2B)
Each eps_k' uses the exact exponential update over dt:
    eps_k' = beta_k (J_k c (H_P - H0) - eps_k_old),   beta_k = (1 - exp(-dt/tau_k)) / dt
which keeps every boundary linear (or quadratic in sqrt(H)) in H_P.
With no elements the solver is exactly the elastic one. `a` is then the instantaneous
(elastic) wave speed; creep slows, smooths and damps the wave over time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import yaml

G = 9.80665
PARAMS_PATH = Path(__file__).resolve().parent / "params.yaml"


@dataclass
class PipeSetup:
    L: float = 150.0
    D: float = 0.05
    a: float = 350.0
    f: float = 0.02
    H_res: float = 30.0
    V0: float = 0.5                 # velocity through the valve before closure (m/s)
    x_leak: float | None = None     # leak position from the reservoir (m); None = no leak
    leak_cda: float = 0.0           # Cd * A_leak (m^2)
    Tc: float = 0.025               # valve closure time (s); 0 = instantaneous
    t_close: float = 0.05           # closure start (s)
    closure_exp: float = 1.0
    N: int = 900
    duration: float = 2.0
    # viscoelastic pipe wall (empty = elastic)
    ve_J: tuple = ()                # creep compliance of each Kelvin-Voigt element (1/Pa)
    ve_tau: tuple = ()              # their retardation times (s)
    wall: float = 0.0058            # wall thickness (m)
    ve_alpha: float = 1.0           # pipe constraint coefficient

    @property
    def viscoelastic(self) -> bool:
        return any(j > 0 for j in self.ve_J)

    @property
    def A(self) -> float:
        return math.pi * self.D ** 2 / 4

    @property
    def dx(self) -> float:
        return self.L / self.N

    @property
    def dt(self) -> float:
        return self.dx / self.a

    @property
    def Q0(self) -> float:
        return self.V0 * self.A

    def with_(self, **kw) -> "PipeSetup":
        return replace(self, **kw)


def load_setup(path: str | Path = PARAMS_PATH, viscoelastic: bool | None = None, **overrides) -> PipeSetup:
    """Pipe from params.yaml. viscoelastic=None follows params ('enabled'); True/False forces it."""
    with open(path, encoding="utf-8") as fh:
        p = yaml.safe_load(fh)
    ve = p.get("viscoelastic", {})
    on = ve.get("enabled", False) if viscoelastic is None else viscoelastic
    s = PipeSetup(
        L=p["pipe"]["length_m"], D=p["pipe"]["diameter_m"], a=p["pipe"]["wave_speed_mps"],
        f=p["pipe"]["darcy_f"], H_res=p["boundary"]["reservoir_head_m"],
        V0=p["boundary"]["initial_velocity_mps"], Tc=p["valve"]["closure_time_s"],
        t_close=p["valve"]["closure_start_s"], closure_exp=p["valve"]["closure_exponent"],
        N=p["numerics"]["n_reaches"], duration=p["numerics"]["duration_s"],
        ve_J=tuple(float(j) for j in ve.get("J_per_Pa", [])) if on else (),
        ve_tau=tuple(float(t) for t in ve.get("tau_s", [])) if on else (),
        wall=float(ve.get("wall_m", 0.0058)), ve_alpha=float(ve.get("alpha", 1.0)),
    )
    return s.with_(**overrides) if overrides else s


def leak_cda_for_fraction(setup: PipeSetup, fraction: float, x_leak: float) -> float:
    """Cd*A giving a steady leak flow of `fraction` x Q0 at x_leak (friction included)."""
    s = setup.with_(x_leak=x_leak, leak_cda=0.0)
    q_l = fraction * s.Q0
    R = s.f * s.dx / (2 * G * s.D * s.A ** 2)
    i = _leak_index(s)
    h = s.H_res - R * (s.Q0 + q_l) ** 2 * i
    return q_l / math.sqrt(2 * G * h)


def _leak_index(s: PipeSetup) -> int | None:
    if s.x_leak is None:
        return None
    return int(min(max(round(s.x_leak / s.dx), 1), s.N - 1))


@dataclass
class SteadyState:
    H: np.ndarray
    Qu: np.ndarray   # flow on the upstream side of each node
    Qd: np.ndarray   # flow on the downstream side of each node
    Cv: float        # valve coefficient, Q = tau Cv sqrt(H)
    i_leak: int | None
    q_leak: float


def steady_state(s: PipeSetup) -> SteadyState:
    R = s.f * s.dx / (2 * G * s.D * s.A ** 2)
    i_l = _leak_index(s)
    idx = np.arange(s.N + 1)
    q_l = 0.0
    if i_l is not None and s.leak_cda > 0:
        for _ in range(100):                       # fixed point, converges in a few steps
            h_l = s.H_res - R * (s.Q0 + q_l) ** 2 * i_l
            q_new = s.leak_cda * math.sqrt(2 * G * max(h_l, 0.0))
            if abs(q_new - q_l) < 1e-14:
                break
            q_l = q_new
    q_up = s.Q0 + q_l
    if i_l is None:
        H = s.H_res - R * s.Q0 ** 2 * idx
        Qu = np.full(s.N + 1, s.Q0)
        Qd = Qu.copy()
    else:
        h_l = s.H_res - R * q_up ** 2 * i_l
        H = np.where(idx <= i_l, s.H_res - R * q_up ** 2 * idx, h_l - R * s.Q0 ** 2 * (idx - i_l))
        Qu = np.where(idx <= i_l, q_up, s.Q0).astype(float)
        Qd = np.where(idx < i_l, q_up, s.Q0).astype(float)
    if H[-1] <= 0:
        raise ValueError("steady head at the valve is not positive: lower V0 or friction")
    return SteadyState(H.astype(float), Qu, Qd, s.Q0 / math.sqrt(H[-1]), i_l, q_l)


def tau(s: PipeSetup, t: float) -> float:
    if t < s.t_close:
        return 1.0
    if s.Tc <= 0:
        return 0.0
    r = 1.0 - (t - s.t_close) / s.Tc
    return max(r, 0.0) ** s.closure_exp


@dataclass
class Result:
    setup: PipeSetup
    t: np.ndarray            # solver time steps (s)
    H_valve: np.ndarray      # head at the valve / sensor (m)
    q_leak: np.ndarray       # leak flow over time (m3/s)
    x: np.ndarray            # node positions (m)
    frame_t: np.ndarray = field(default_factory=lambda: np.empty(0))
    frames: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))  # [n_frames x N+1]
    min_head: float = 0.0
    x_leak_actual: float | None = None

    @property
    def H0(self) -> float:
        return float(self.H_valve[0])

    def sampled(self, fs: float) -> tuple[np.ndarray, np.ndarray]:
        """Valve head resampled to a sensor rate fs (linear interpolation)."""
        ts = np.arange(0.0, self.t[-1], 1.0 / fs)
        return ts, np.interp(ts, self.t, self.H_valve)


def simulate(s: PipeSetup, frame_every_s: float | None = None) -> Result:
    st = steady_state(s)
    B = s.a / (G * s.A)
    R = s.f * s.dx / (2 * G * s.D * s.A ** 2)
    H, Qu, Qd = st.H.copy(), st.Qu.copy(), st.Qd.copy()
    n_steps = int(math.ceil(s.duration / s.dt))
    t = np.arange(n_steps + 1) * s.dt
    Hv = np.empty(n_steps + 1)
    ql = np.empty(n_steps + 1)
    Hv[0], ql[0] = H[-1], st.q_leak
    k_leak = s.leak_cda * math.sqrt(2 * G)
    i_l = st.i_leak
    frame_k = max(1, int(round(frame_every_s / s.dt))) if frame_every_s else 0
    frames, frame_t = [], []
    if frame_k:
        frames.append(H.copy())
        frame_t.append(0.0)
    hmin = float(H.min())

    # viscoelastic wall (no elements -> elastic solver, code paths below are skipped)
    H0n = st.H.copy()
    ve = s.viscoelastic
    if ve:
        if len(s.ve_J) != len(s.ve_tau):
            raise ValueError("ve_J and ve_tau need the same number of elements")
        c_wall = s.ve_alpha * 1000.0 * G * s.D / (2 * s.wall)        # Pa of hoop stress-ish per m of head
        Jc = np.array(s.ve_J)[:, None] * c_wall                     # [K, 1] strain per m of head
        beta = np.array([(1 - math.exp(-s.dt / tk)) / s.dt for tk in s.ve_tau])[:, None]
        k_ve = 2 * s.a ** 2 * s.dt / G
        eps = np.zeros((len(s.ve_J), len(H)))                       # [K, N+1] retarded strains
        sv = 1 + k_ve * float((beta * Jc).sum())                    # H_P scale factor

        def eps_rate(h_new, idx=slice(None)):
            """Total retarded strain rate at nodes idx for heads h_new."""
            return (beta * (Jc * (h_new - H0n[idx]) - eps[:, idx])).sum(axis=0)
    for n in range(1, n_steps + 1):
        tn = t[n]
        CP = H[:-2] + B * Qd[:-2] - R * Qd[:-2] * np.abs(Qd[:-2])      # nodes 1..N-1
        CM = H[2:] - B * Qu[2:] + R * Qu[2:] * np.abs(Qu[2:])
        Hn = np.empty_like(H)
        Qun = np.empty_like(Qu)
        if ve:
            src = k_ve * (beta * (Jc * H0n + eps)).sum(axis=0)       # creep "source" per node
            Hn[1:-1] = (0.5 * (CP + CM) + src[1:-1]) / sv
        else:
            Hn[1:-1] = 0.5 * (CP + CM)
        Qun[1:-1] = (CP - CM) / (2 * B)
        Qdn = Qun.copy()
        q_leak_n = 0.0
        if i_l is not None and k_leak > 0:
            cp, cm = CP[i_l - 1], CM[i_l - 1]
            if ve:
                cbar = (0.5 * (cp + cm) + src[i_l]) / sv
                c = 0.5 * B * k_leak / sv
            else:
                cbar = 0.5 * (cp + cm)
                c = 0.5 * B * k_leak
            sq = (-c + math.sqrt(c * c + 4 * max(cbar, 0.0))) / 2
            hp = sq * sq
            q_leak_n = k_leak * sq
            Hn[i_l] = hp
            kd = k_ve * float(eps_rate(hp, slice(i_l, i_l + 1))[0]) if ve else 0.0
            Qun[i_l] = (cp - kd - hp) / B
            Qdn[i_l] = (hp + kd - cm) / B
        # upstream reservoir (fixed head: creep term only from relaxing strain)
        cm0 = H[1] - B * Qu[1] + R * Qu[1] * abs(Qu[1])
        Hn[0] = s.H_res
        kd0 = k_ve * float(eps_rate(s.H_res, slice(0, 1))[0]) if ve else 0.0
        Qun[0] = Qdn[0] = (s.H_res - cm0 + kd0) / B
        # downstream valve
        cpn = H[-2] + B * Qd[-2] - R * Qd[-2] * abs(Qd[-2])
        Bv = B
        if ve:
            cpn = (cpn + src[-1]) / sv
            Bv = B / sv
        tv = tau(s, tn)
        if tv > 0:
            c = Bv * tv * st.Cv
            sq = (-c + math.sqrt(c * c + 4 * max(cpn, 0.0))) / 2
            Hn[-1] = sq * sq
            Qun[-1] = Qdn[-1] = tv * st.Cv * sq
        else:
            Hn[-1] = cpn
            Qun[-1] = Qdn[-1] = 0.0
        if ve:
            eps += s.dt * beta * (Jc * (Hn - H0n) - eps)
        H, Qu, Qd = Hn, Qun, Qdn
        Hv[n], ql[n] = H[-1], q_leak_n
        hmin = min(hmin, float(H.min()))
        if frame_k and n % frame_k == 0:
            frames.append(H.copy())
            frame_t.append(tn)

    return Result(
        setup=s, t=t, H_valve=Hv, q_leak=ql, x=np.arange(s.N + 1) * s.dx,
        frame_t=np.array(frame_t), frames=np.array(frames) if frames else np.empty((0, 0)),
        min_head=hmin, x_leak_actual=None if i_l is None else i_l * s.dx,
    )


def joukowsky_head(s: PipeSetup) -> float:
    """Head rise for an instantaneous full closure: a * V0 / g."""
    return s.a * s.V0 / G
