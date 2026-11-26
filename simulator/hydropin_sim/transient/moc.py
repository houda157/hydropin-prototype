"""Method-of-characteristics transient solver. Math note §5.1–5.7.

Network model
-------------
Built from the *prepared* WNTR model of a scenario (so leaks, clogging and
sector valves are exactly those of the steady twin) and its steady result
(initial conditions). Every node is one of:

* fixed head      – reservoir / basin (H_P = H_res)
* pump-fed        – the node downstream of a pump drawing from a reservoir:
                    inflow Q = sqrt((H_res + h0 - H) / r)
* emitter         – any junction; outflow C_e(t) sqrt(H - z) where C_e is the
                    sum of lateral-block, outlet, leak and excitation-valve
                    coefficients (a closed end is C_e = 0)

The excitation valve is a time-varying emitter: C_v(t) = tau(t) C_v0 with
tau(t) = (1 - t/T_c)^E_m (math note §5.6).

Optional (board twin, math note §10.7):
* lumped valves  – a short valve pipe replaced by a lumped element between its two
                   nodes, Q|Q| = c_v² (H_a - H_b), solved exactly with both nodes'
                   characteristics (stable for any c_v, including shut-off)
* pipe → emitter – a pipe from a junction to a reservoir (tap + orifice) replaced by
                   an emitter at the junction, calibrated on the steady flow
* pump exponent  – inflow ((H_res + s h0 - H) / r')^(1/n), r' = r s^(1-n), speed s(t)

Numerics
--------
All pipe points live in one global array (vectorised). The grid uses Courant
number 1 with per-pipe wave-speed adjustment |a'-a|/a <= PSI_MAX (§5.5).
Optional terms:
* friction      : "quasi-steady" (Darcy–Weisbach, f from the local flow) or "none"
* unsteady      : Brunone–Vardy unsteady friction, a·sgn(Q)·|∂Q/∂x| form (§5.4)
* viscoelastic  : generalised Kelvin–Voigt creep, implicit in H_P (§5.3)

Viscoelastic treatment: the creep term -(2a²Δt/g) dε_r/dt at point P is linear
in H_P with the exact exponential update of each Kelvin–Voigt element, so
H_P (1+α) = C ± B Q_P + β. Dividing by (1+α) gives modified C', B' and every
interior/boundary formula keeps its elastic form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np
import wntr

from hydropin_sim.config import Params
from hydropin_sim.contracts import NetworkSpec, SteadyResult, TransientResult
from hydropin_sim.physics.friction import friction_factor
from hydropin_sim.physics.waves import c1_factor, wave_speed

PipeMaterial = Callable[[str], str]


@dataclass
class Grid:
    dt: float
    pipes: list[str]
    n_seg: np.ndarray        # segments per pipe
    a: np.ndarray            # adjusted wave speed per pipe
    a_true: np.ndarray       # physical wave speed per pipe
    offset: np.ndarray       # index of the first point of each pipe in the global arrays

    @property
    def n_points(self) -> int:
        return int(np.sum(self.n_seg + 1))

    @property
    def max_adjustment(self) -> float:
        return float(np.max(np.abs(self.a / self.a_true - 1)))


def make_grid(pipes: Sequence[str], lengths: np.ndarray, a: np.ndarray, psi: float,
              dt_max: float = 1e-3, min_seg: int = 2) -> Grid:
    """Largest Δt <= dt_max giving Courant 1 with every |a'/a - 1| <= psi. Math note §5.5."""
    lengths, a = np.asarray(lengths, float), np.asarray(a, float)
    t_travel = lengths / a
    best = None
    for n_ref in range(min_seg, 20000):
        dt = float(np.min(t_travel)) / n_ref
        if dt > dt_max:
            continue
        n = np.maximum(np.round(t_travel / dt), min_seg).astype(int)
        a_adj = lengths / (n * dt)
        if np.max(np.abs(a_adj / a - 1)) <= psi:
            best = (dt, n, a_adj)
            break
    if best is None:
        raise RuntimeError("could not build a grid within the wave-speed adjustment limit")
    dt, n, a_adj = best
    offset = np.concatenate([[0], np.cumsum(n + 1)[:-1]])
    return Grid(dt, list(pipes), n, a_adj, a, offset)


@dataclass
class ValveEvent:
    """Excitation: the emitter coefficient of `node` goes from c0 to c0*(1-closure) in T_c."""
    node: str
    c0: float
    t_start: float
    t_close: float
    e_m: float = 1.5
    closure: float = 1.0      # 1 = full closure; 0.1 = closes by 10 % (small-signal test)

    def coeff(self, t: float) -> float:
        if t <= self.t_start:
            return self.c0
        s = min((t - self.t_start) / self.t_close, 1.0) if self.t_close > 0 else 1.0
        tau = (1.0 - s) ** self.e_m
        return self.c0 * (1.0 - self.closure * (1.0 - tau))


@dataclass
class RampEvent:
    """Coefficient of an emitter node or lumped valve goes linearly from c0 to c1 in t_ramp."""
    node: str
    c0: float
    c1: float
    t_start: float
    t_ramp: float

    def coeff(self, t: float) -> float:
        if t <= self.t_start:
            return self.c0
        s = min((t - self.t_start) / self.t_ramp, 1.0) if self.t_ramp > 0 else 1.0
        return self.c0 + (self.c1 - self.c0) * s


@dataclass
class TransientModel:
    grid: Grid
    node_ids: list[str]
    z: np.ndarray                      # node elevation
    kind: np.ndarray                   # 0 emitter, 1 fixed head, 2 pump-fed
    h_fixed: np.ndarray
    c_e: np.ndarray                    # static emitter coefficient per node
    pump: Optional[dict]               # {node, h_res, h0, r}
    up_node: np.ndarray                # node index at pipe start
    dn_node: np.ndarray                # node index at pipe end
    d: np.ndarray
    area: np.ndarray
    eps: np.ndarray
    e_wall: np.ndarray
    c1: np.ndarray
    j_k: list[np.ndarray]              # per pipe
    tau_k: list[np.ndarray]
    q0: np.ndarray                     # initial flow per pipe
    h0_pts: np.ndarray                 # initial head per point
    q0_pts: np.ndarray
    z_pts: np.ndarray
    k_minor: np.ndarray                # minor-loss coefficient per pipe (spread over its segments)
    nu: float
    g: float
    rho: float
    meta: dict = field(default_factory=dict)
    z_em: Optional[np.ndarray] = None  # emitter reference head per node (default: elevation)
    valves: list = field(default_factory=list)   # lumped valves: dict(id, up, dn, c)


def build_model(spec: NetworkSpec, wn: wntr.network.WaterNetworkModel, steady: SteadyResult, P: Params,
                psi: Optional[float] = None, dt_max: float = 1e-3, alpha_air: Optional[float] = None,
                anchoring: str = "free", wave_speed_override: Optional[float] = None,
                lumped: Sequence[str] = (), to_emitter: Sequence[str] = ()) -> TransientModel:
    """Transient model from the prepared WNTR model + its steady solution (math note §5).

    lumped:     valve pipes turned into lumped valves, c_v = Q0 / sqrt(|ΔH0|) from the steady state
    to_emitter: junction → reservoir pipes turned into emitters at the junction, c = Q0 / sqrt(H0 - H_res)
    (math note §10.7)"""
    psi = P.transient.PSI_MAX.v if psi is None else psi
    g, rho, k_w = P.water.G.v, P.water.RHO_W.v, P.water.K_W.v
    nu = steady.meta.get("nu") or P.nu_w()
    spec_pipe = {p.id: p for p in spec.pipes}

    def parent(pid: str):
        if pid in spec_pipe:
            return spec_pipe[pid]
        base = pid.split("_L")[0]
        return spec_pipe[base]

    nodes = list(wn.node_name_list)
    nix = {n: i for i, n in enumerate(nodes)}
    six = {n: i for i, n in enumerate(steady.node_ids)}
    lix = {n: i for i, n in enumerate(steady.link_ids)}
    pipes = [p for p in wn.pipe_name_list
             if wn.get_link(p).initial_status != wntr.network.LinkStatus.Closed
             and p not in lumped and p not in to_emitter]
    # closed sector valves isolate their sector: drop the closed pipes and the nodes they feed
    lengths, a_true, d, eps, e_wall, c1, jk, tk, kmin = [], [], [], [], [], [], [], [], []
    for pid in pipes:
        link = wn.get_link(pid)
        sp = parent(pid)
        mat = P.material(sp.material)
        lengths.append(link.length)
        d.append(link.diameter)
        eps.append(link.roughness)
        kmin.append(link.minor_loss or 0.0)
        e_wall.append(sp.e_wall)
        c = P.pipes.C1.v if anchoring == "free" else c1_factor(anchoring, mat.NU_P.v, link.diameter, sp.e_wall)
        c1.append(c)
        a = float(wave_speed(k_w, rho, link.diameter, sp.e_wall, mat.E_PIPE.v, c))
        if wave_speed_override is not None:
            a = wave_speed_override
        alpha = P.transient.ALPHA_AIR.v if alpha_air is None else alpha_air
        if alpha > 0:
            h_avg = 0.5 * (steady.pressure[0, six[link.start_node_name]] + steady.pressure[0, six[link.end_node_name]])
            p_abs = P.water.P_ATM.v + rho * g * max(h_avg, 0.0)
            a = a / np.sqrt(1 + alpha * rho * a ** 2 / p_abs)
        a_true.append(a)
        jk.append(np.asarray(mat.J_K.v, float))
        tk.append(np.asarray(mat.TAU_K.v, float))
    grid = make_grid(pipes, np.array(lengths), np.array(a_true), psi, dt_max)

    n = len(nodes)
    z = np.array([wn.get_node(nm).elevation if hasattr(wn.get_node(nm), "elevation") else 0.0 for nm in nodes])
    kind = np.zeros(n, int)
    h_fixed = np.zeros(n)
    c_e = np.zeros(n)
    for i, nm in enumerate(nodes):
        node = wn.get_node(nm)
        if node.node_type == "Reservoir":
            kind[i] = 1
            h_fixed[i] = node.base_head
            z[i] = node.base_head
        else:
            c_e[i] = node.emitter_coefficient or 0.0
    pump = None
    for pu_spec in spec.pumps:
        node_i = nix[pu_spec.end]
        kind[node_i] = 2
        pump = dict(node=node_i, h_res=float(h_fixed[nix[pu_spec.start]]), h0=pu_spec.h0, r=pu_spec.r,
                    n=float(pu_spec.n))
    z_em = z.copy()
    for pid in to_emitter:                      # tap + orifice → emitter calibrated on the steady flow
        link = wn.get_link(pid)
        a_i, b_i = nix[link.start_node_name], nix[link.end_node_name]
        if kind[b_i] != 1:
            raise ValueError(f"{pid}: to_emitter needs a pipe ending at a reservoir")
        q = float(steady.flow[0, lix[pid]])
        dh = float(steady.head[0, six[link.start_node_name]]) - h_fixed[b_i]
        c_e[a_i] += q / np.sqrt(dh) if q > 0 and dh > 0 else 0.0
        z_em[a_i] = h_fixed[b_i]
    valves = []
    for pid in lumped:                          # valve pipe → lumped valve
        link = wn.get_link(pid)
        q = float(steady.flow[0, lix[pid]])
        dh = float(steady.head[0, six[link.start_node_name]] - steady.head[0, six[link.end_node_name]])
        c = abs(q) / np.sqrt(abs(dh)) if abs(dh) > 0 else 0.0
        valves.append(dict(id=pid, up=nix[link.start_node_name], dn=nix[link.end_node_name], c=c))

    up = np.array([nix[wn.get_link(p).start_node_name] for p in pipes])
    dn = np.array([nix[wn.get_link(p).end_node_name] for p in pipes])
    q0 = np.array([steady.flow[0, lix[p]] for p in pipes])
    d_a = np.array(d)
    area = np.pi * d_a ** 2 / 4
    npts = grid.n_points
    h0p, q0p, zp = np.empty(npts), np.empty(npts), np.empty(npts)
    for j, pid in enumerate(pipes):
        o, m = grid.offset[j], grid.n_seg[j]
        x = np.linspace(0, 1, m + 1)
        h_up = steady.head[0, six[wn.get_link(pid).start_node_name]]
        h_dn = steady.head[0, six[wn.get_link(pid).end_node_name]]
        h0p[o:o + m + 1] = h_up + (h_dn - h_up) * x
        q0p[o:o + m + 1] = q0[j]
        zp[o:o + m + 1] = z[up[j]] + (z[dn[j]] - z[up[j]]) * x
    return TransientModel(grid, nodes, z, kind, h_fixed, c_e, pump, up, dn, d_a, area, np.array(eps),
                          np.array(e_wall), np.array(c1), jk, tk, q0, h0p, q0p, zp, np.array(kmin), nu, g, rho,
                          meta=dict(steady_head={nm: steady.head[0, six[nm]] for nm in nodes if nm in six}),
                          z_em=z_em, valves=valves)


@dataclass
class Options:
    duration: float
    friction: str = "quasi-steady"      # or "none"
    unsteady: bool = False
    viscoelastic: bool = False
    record: Sequence[str] = ()          # node ids to record
    record_points: Sequence[tuple[str, float]] = ()   # (pipe id, x/L) interior points
    record_every: int = 1
    pump_speed: Optional[Callable[[float], float]] = None   # s(t), 1 = nominal (math note §10.7)


def run(model: TransientModel, opts: Options, events: Sequence[ValveEvent] = (),
        p_vap_head: Optional[float] = None) -> TransientResult:
    G = model.grid
    g = model.g
    dt = G.dt
    npts = G.n_points
    pipe_of = np.repeat(np.arange(len(G.pipes)), G.n_seg + 1)
    a_pt = G.a[pipe_of]
    B_pt = a_pt / (g * model.area[pipe_of])
    dx_pt = (a_pt * dt)
    d_pt = model.d[pipe_of]
    A_pt = model.area[pipe_of]
    eps_pt = model.eps[pipe_of]
    km_pt = (model.k_minor / G.n_seg)[pipe_of]     # minor loss spread evenly over the segments
    first = G.offset
    last = G.offset + G.n_seg
    is_first = np.zeros(npts, bool)
    is_first[first] = True
    is_last = np.zeros(npts, bool)
    is_last[last] = True
    interior = np.where(~is_first & ~is_last)[0]

    H = model.h0_pts.copy()
    Q = model.q0_pts.copy()
    Q_prev = Q.copy()

    # unsteady friction coefficient k3 per pipe (Vardy, from the initial Reynolds number)
    if opts.unsteady:
        re0 = np.abs(model.q0) / model.area * model.d / model.nu
        cstar = np.where(re0 < 2000, 0.00476, 7.41 / np.maximum(re0, 1.0) ** np.log10(14.3 / np.maximum(re0, 1.0) ** 0.05))
        k3_pt = (np.sqrt(cstar) / 2)[pipe_of]
    # viscoelastic state
    ve = opts.viscoelastic and any(len(j) for j in model.j_k)
    if ve:
        K = max(len(j) for j in model.j_k)
        Jk = np.zeros((npts, K))
        ek = np.ones((npts, K))
        for j in range(len(G.pipes)):
            sl = slice(G.offset[j], G.offset[j] + G.n_seg[j] + 1)
            nk = len(model.j_k[j])
            Jk[sl, :nk] = model.j_k[j]
            ek[sl, :nk] = np.exp(-dt / model.tau_k[j])
        kf_pt = (model.c1 * model.d * model.rho * g / (2 * model.e_wall))[pipe_of]
        eps_k = np.zeros((npts, K))
        H_ref = model.h0_pts.copy()
        alpha_ve = (2 * a_pt ** 2 / g) * kf_pt * np.sum((1 - ek) * Jk, axis=1)

    rec_nodes = [model.node_ids.index(n) for n in opts.record]
    rec_pts = []
    for pid, frac in opts.record_points:
        j = G.pipes.index(pid)
        rec_pts.append(G.offset[j] + int(round(frac * G.n_seg[j])))
    n_steps = int(round(opts.duration / dt))
    n_rec = n_steps // opts.record_every + 1
    t_rec = np.empty(n_rec)
    h_rec = np.empty((n_rec, len(rec_nodes) + len(rec_pts)))
    q_rec = np.empty_like(h_rec)
    nodeH = np.zeros(len(model.node_ids))
    min_margin = np.inf

    # node → connected pipe ends
    n_nodes = len(model.node_ids)
    end_pts = last                     # downstream ends (C+)
    start_pts = first                  # upstream ends (C-)
    dn_node, up_node = model.dn_node, model.up_node
    c_static = model.c_e.copy()
    z_em = model.z if model.z_em is None else model.z_em
    vids = {v["id"]: k for k, v in enumerate(model.valves)}
    ev_idx = [(model.node_ids.index(e.node), e) for e in events if e.node not in vids]
    ev_valve = [(vids[e.node], e) for e in events if e.node in vids]
    vnodes = np.array([v["up"] for v in model.valves] + [v["dn"] for v in model.valves], int)

    def friction_term(Qx, idx):
        if opts.friction == "none":
            return np.zeros(len(idx))
        q = Qx[idx]
        re = np.abs(q) / A_pt[idx] * d_pt[idx] / model.nu
        f = np.where(re > 0, friction_factor(np.maximum(re, 1e-9), eps_pt[idx], d_pt[idx]), 0.0)
        r = f * dx_pt[idx] / (2 * g * d_pt[idx] * A_pt[idx] ** 2) + km_pt[idx] / (2 * g * A_pt[idx] ** 2)
        return r * q * np.abs(q)

    def record(k, t):
        t_rec[k] = t
        cols = [nodeH[i] for i in rec_nodes] + [H[p] for p in rec_pts]
        h_rec[k] = cols
        qcols = [np.nan] * len(rec_nodes) + [Q[p] for p in rec_pts]
        q_rec[k] = qcols

    # initial node heads
    for i in range(n_nodes):
        nodeH[i] = model.meta["steady_head"].get(model.node_ids[i], np.nan)
    record(0, 0.0)
    for step in range(1, n_steps + 1):
        t = step * dt
        # characteristics from the previous time level
        A_ = np.arange(npts - 1)          # point i uses i-1 (C+) and i+1 (C-)
        CP = np.full(npts, np.nan)
        CM = np.full(npts, np.nan)
        src_p = np.where(~is_first)[0]    # points that have a C+ coming from i-1
        src_m = np.where(~is_last)[0]     # points that have a C- coming from i+1
        CP[src_p] = H[src_p - 1] + B_pt[src_p] * Q[src_p - 1] - friction_term(Q, src_p - 1)
        CM[src_m] = H[src_m + 1] - B_pt[src_m] * Q[src_m + 1] + friction_term(Q, src_m + 1)
        if opts.unsteady:
            dqt = Q - Q_prev
            # C+ at P from A = P-1 ; C- at P from B = P+1 ; math note §5.4: a sgn(Q) |∂Q/∂x|
            ia = src_p - 1
            dqx_a = Q[np.minimum(ia + 1, npts - 1)] - Q[ia]
            CP[src_p] -= B_pt[src_p] * k3_pt[ia] * (dqt[ia] + np.sign(Q[ia]) * np.abs(dqx_a))
            ib = src_m + 1
            dqx_b = Q[ib] - Q[np.maximum(ib - 1, 0)]
            CM[src_m] += B_pt[src_m] * k3_pt[ib] * (dqt[ib] + np.sign(Q[ib]) * np.abs(dqx_b))
        Bp = B_pt
        if ve:
            beta = (2 * a_pt ** 2 / g) * (kf_pt * H_ref * np.sum((1 - ek) * Jk, axis=1)
                                          + np.sum((ek - 1) * eps_k, axis=1))
            scale = 1.0 / (1.0 + alpha_ve)
            CP = (CP + beta) * scale
            CM = (CM + beta) * scale
            Bp = B_pt * scale
        H_new = np.empty(npts)
        Q_new = np.empty(npts)
        # interior points
        i = interior
        H_new[i] = 0.5 * (CP[i] + CM[i])
        Q_new[i] = (CP[i] - CM[i]) / (2 * Bp[i])
        # nodes: S = sum_in CP/B + sum_out CM/B ; W = sum 1/B
        S = np.zeros(n_nodes)
        W = np.zeros(n_nodes)
        np.add.at(S, dn_node, CP[end_pts] / Bp[end_pts])
        np.add.at(W, dn_node, 1.0 / Bp[end_pts])
        np.add.at(S, up_node, CM[start_pts] / Bp[start_pts])
        np.add.at(W, up_node, 1.0 / Bp[start_pts])
        ce = c_static.copy()
        for ni, ev in ev_idx:
            ce[ni] = ce[ni] - ev.c0 + ev.coeff(t)
        Hn = np.empty(n_nodes)
        em = model.kind == 0
        Wz = W[em] * z_em[em]
        disc = ce[em] ** 2 + 4 * W[em] * np.maximum(S[em] - Wz, 0.0)
        u = np.where(W[em] > 0, (-ce[em] + np.sqrt(disc)) / (2 * np.where(W[em] > 0, W[em], 1)), 0.0)
        Hn_em = np.where(S[em] - Wz > 0, u ** 2 + z_em[em], S[em] / np.where(W[em] > 0, W[em], 1))
        Hn[em] = Hn_em
        fx = model.kind == 1
        Hn[fx] = model.h_fixed[fx]
        if model.pump is not None:
            pi = model.pump["node"]
            hs, h0p, rp = model.pump["h_res"], model.pump["h0"], model.pump["r"]
            npu = model.pump.get("n", 2.0)
            if opts.pump_speed is not None:
                sp_ = max(float(opts.pump_speed(t)), 0.0)
                h0p, rp = sp_ * h0p, (rp * sp_ ** (1.0 - npu) if sp_ > 0 else rp)
            Sp, Wp, cp_, zp_ = S[pi], W[pi], ce[pi], z_em[pi]
            # f(H) = S - W H + ((hs+h0-H)/r)^(1/n) - c sqrt(H - z) = 0, decreasing in H
            # f is decreasing; above hs + h0 the pump (check valves) passes nothing, so the root is
            # at most max(hs + h0, S/W). A stopped pump must not cap the node head at hs.
            lo, hi = min(zp_, Hh0 := nodeH[pi]) - 50.0, max(hs + h0p, Sp / Wp if Wp > 0 else hs + h0p)
            Hh = min(Hh0, hi)
            for _ in range(60):
                qin = (max(hs + h0p - Hh, 0.0) / rp) ** (1.0 / npu)
                qout = cp_ * np.sqrt(max(Hh - zp_, 0.0))
                f = Sp - Wp * Hh + qin - qout
                if abs(f) < 1e-12:
                    break
                if f > 0:
                    lo = Hh
                else:
                    hi = Hh
                dqin = -(1.0 / npu) * rp ** (-1.0 / npu) * max(hs + h0p - Hh, 1e-18) ** (1.0 / npu - 1.0)
                dqout = 0.5 * cp_ / np.sqrt(max(Hh - zp_, 1e-18)) if cp_ > 0 else 0.0
                df = -Wp + dqin - dqout
                Hn_try = Hh - f / df
                Hh = Hn_try if lo < Hn_try < hi else 0.5 * (lo + hi)
            Hn[pi] = Hh
        # lumped valves: Q|Q| = c² (H_a - H_b) with H_a = (S_a - Q)/W_a, H_b = (S_b + Q)/W_b
        for k, v in enumerate(model.valves):
            c = v["c"]
            for kk, ev in ev_valve:
                if kk == k:
                    c = ev.coeff(t)
            ia, ib = v["up"], v["dn"]
            C = S[ia] / W[ia] - S[ib] / W[ib]
            D = 1.0 / W[ia] + 1.0 / W[ib]
            if c <= 0:
                q = 0.0
            else:
                R = 1.0 / c ** 2
                q = np.sign(C) * (-D + np.sqrt(D * D + 4 * R * abs(C))) / (2 * R)
            Hn[ia] = (S[ia] - q) / W[ia]
            Hn[ib] = (S[ib] + q) / W[ib]
            v["q"] = q
        nodeH = Hn
        H_new[end_pts] = Hn[dn_node]
        Q_new[end_pts] = (CP[end_pts] - H_new[end_pts]) / Bp[end_pts]
        H_new[start_pts] = Hn[up_node]
        Q_new[start_pts] = (H_new[start_pts] - CM[start_pts]) / Bp[start_pts]
        if ve:
            F = kf_pt * (H_new - H_ref)
            eps_k = ek * eps_k + (1 - ek) * Jk * F[:, None]
        Q_prev = Q
        H, Q = H_new, Q_new
        if p_vap_head is not None:
            min_margin = min(min_margin, float(np.min(H - model.z_pts - p_vap_head)))
        if step % opts.record_every == 0:
            record(step // opts.record_every, t)

    ids = list(opts.record) + [f"{p}@{f:g}" for p, f in opts.record_points]
    return TransientResult(scenario_id="", time=t_rec, point_ids=ids, head=h_rec, flow=q_rec,
                           wave_speed=dict(zip(G.pipes, G.a)),
                           meta=dict(dt=dt, grid=G, cavitation_margin=min_margin,
                                     cavitation=bool(min_margin < 0)))
