"""Oracles – physics library (math note §2.2–2.7, §5.2, §5.7)."""

from __future__ import annotations

import numpy as np

from hydropin_sim.config import load_params
from hydropin_sim.physics import emitters as em
from hydropin_sim.physics import friction as fr
from hydropin_sim.physics import leaks as lk
from hydropin_sim.physics import pump as pu
from hydropin_sim.physics import waves as wv
from oracles.base import Check

P = load_params()
G, RHO, K = P.water.G.v, P.water.RHO_W.v, P.water.K_W.v
NU20 = P.nu_w(20.0)
EPS = P.material("PE100").EPS_R.v

# Reference geometries used across checks
D_LAT = 0.0136                       # Ø16 lateral, internal
D63, E63 = 0.063 - 2 * 0.063 / 11, 0.063 / 11   # HDPE PE100 Ø63 SDR11


def dripper(h):
    return em.dripper_flow(h, P.emitters.Q_NOM.v, P.emitters.H_NOM.v, P.emitters.X_EMIT.v)


def checks() -> list[Check]:
    c: list[Check] = []

    # ── Friction (§2.2) ──
    c.append(Check("1.1", "Laminar friction f = 64/Re at Re = 1000",
                   0.064, float(fr.f_laminar(1000.0)), 1e-12, "abs", "§2.2"))
    c.append(Check("1.2", "Colebrook, smooth pipe, Re = 1e5 vs Moody/Prandtl value 0.0180",
                   0.0180, float(fr.f_colebrook(1e5, 0.0, 1.0)), 0.005, "rel", "§2.2"))
    c.append(Check("1.3", "Blasius vs Colebrook, smooth pipe, Re = 1e5",
                   float(fr.f_colebrook(1e5, 0.0, 1.0)), float(fr.f_blasius(1e5)), 0.02, "rel", "§2.2"))
    re = np.logspace(np.log10(5000), 8, 300)
    errs = [np.max(np.abs(fr.f_swamee_jain(re, e, 1.0) / fr.f_colebrook(re, e, 1.0) - 1))
            for e in np.logspace(-6, -2, 50)]
    c.append(Check("1.4", "Swamee–Jain vs Colebrook, worst case over Re 5e3–1e8, ε/D 1e-6–1e-2",
                   0.03, float(max(errs)), kind="le", ref="§2.2"))
    # Hand calculation: HDPE Ø63 SDR11, Q = 2 L/s, L = 100 m
    q, L = 0.002, 100.0
    v = q / (np.pi * D63 ** 2 / 4)
    f_ref = float(fr.f_colebrook(v * D63 / NU20, EPS, D63))
    hand = f_ref * L / D63 * v ** 2 / (2 * G)
    c.append(Check("1.5", "Darcy–Weisbach head loss, HDPE Ø63, 2 L/s, 100 m (hand calc. with Colebrook)",
                   hand, float(fr.headloss_dw(q, L, D63, EPS, NU20, G)), 0.03, "rel", "§2.2", "m"))
    c.append(Check("1.6", "Head loss changes sign with flow direction",
                   True, bool(np.isclose(fr.headloss_dw(-q, L, D63, EPS, NU20, G),
                                         -fr.headloss_dw(q, L, D63, EPS, NU20, G))), kind="bool", ref="§2.2"))
    d100 = 0.1
    q100 = 1.0 * np.pi * d100 ** 2 / 4
    c.append(Check("1.7", "Hazen–Williams (C=150) ≈ Darcy–Weisbach for a Ø100 main at 1 m/s",
                   float(fr.headloss_dw(q100, 100, d100, EPS, NU20, G)),
                   float(fr.headloss_hw(q100, 100, d100, 150)), 0.10, "rel", "§2.2", "m"))
    q_lam = 500 * NU20 * np.pi * D_LAT / 4         # Re = 500: last metres of a Ø16 lateral
    ratio = float(fr.headloss_hw(q_lam, 10, D_LAT, 150) / fr.headloss_dw(q_lam, 10, D_LAT, EPS, NU20, G))
    c.append(Check("1.8", "Hazen–Williams underestimates laminar loss (Ø16 lateral, Re = 500): HW/DW < 0.7",
                   0.7, ratio, kind="le", ref="§2.2"))

    # ── Drippers and laterals (§2.3–2.4) ──
    c.append(Check("1.9", "Non-compensating dripper delivers Q_NOM at H_NOM",
                   P.emitters.Q_NOM.v, float(dripper(P.emitters.H_NOM.v)), 1e-12, "rel", "§2.3", "m³/s"))
    q_left = float(em.dripper_flow(P.emitters.H_ACT.v * (1 - 1e-9), P.emitters.Q_NOM.v,
                                   P.emitters.H_NOM.v, 0.0, True, P.emitters.H_ACT.v, P.emitters.H_MAX.v))
    c.append(Check("1.10", "PC dripper is continuous at its activation pressure",
                   P.emitters.Q_NOM.v, q_left, 1e-6, "rel", "§2.3", "m³/s"))
    c.append(Check("1.11", "Christiansen F = 1 for a single outlet (m = 2)",
                   1.0, float(em.christiansen_F(1, 2.0)), 1e-12, "abs", "§2.4"))
    c.append(Check("1.12", "Christiansen F → 1/(m+1) for many outlets (n = 10⁵, m = 1.75)",
                   1 / 2.75, float(em.christiansen_F(1e5, 1.75)), 1e-4, "rel", "§2.4"))
    c.append(Check("1.13", "Christiansen formula vs exact sum, n = 250, m = 1.75",
                   em.christiansen_exact(250, 1.75), float(em.christiansen_F(250, 1.75)), 1e-3, "rel", "§2.4"))
    for cid, slope, txt in (("1.14", 0.0, "flat"), ("1.15", 0.01, "1 % downhill"), ("1.16", -0.01, "1 % uphill")):
        ex = em.lateral_explicit(10.0, 250, 0.4, D_LAT, EPS, NU20, dripper, slope=slope)
        eq = em.lateral_equivalent_flow(10.0, 250, 0.4, D_LAT, EPS, NU20, dripper, slope=slope)
        c.append(Check(cid, f"Equivalent lateral vs every dripper modelled, 100 m Ø16, {txt}",
                       ex.q_inlet, eq, 0.02, "rel", "§2.4", "m³/s"))
    ex = em.lateral_explicit(10.0, 250, 0.4, D_LAT, EPS, NU20, dripper)
    c.append(Check("1.17", "Mass balance of the explicit lateral (inflow = sum of drippers)",
                   float(ex.q_dripper.sum()), ex.q_inlet, 1e-12, "rel", "§2.1", "m³/s"))

    # ── Leaks (§2.5) ──
    a_l, cd, h = 1e-5, P.leaks.CD_LEAK.v, 20.0
    c.append(Check("1.18", "Orifice leak, A = 10 mm², h = 20 m (hand calc.)",
                   0.62 * 1e-5 * np.sqrt(2 * 9.81 * 20), float(lk.orifice(h, cd, a_l, G)), 1e-9, "rel", "§2.5", "m³/s"))
    c.append(Check("1.19", "FAVAD with m = 0 equals the orifice law",
                   float(lk.orifice(h, cd, a_l, G)), float(lk.favad(h, cd, a_l, 0.0, G)), 1e-12, "rel", "§2.5", "m³/s"))
    c.append(Check("1.20", "Emitter form with N1 = 0.5 equals the orifice law",
                   float(lk.orifice(h, cd, a_l, G)),
                   float(lk.emitter(h, lk.c_l_from_orifice(cd, a_l, G), 0.5)), 1e-12, "rel", "§2.5", "m³/s"))

    # ── Pump and energy (§2.6–2.7) ──
    c.append(Check("1.21", "Pump curve gives the shut-off head at Q = 0",
                   40.0, float(pu.pump_head(0.0, 40.0, 1e5, 2.0)), 1e-12, "abs", "§2.6", "m"))
    c.append(Check("1.22", "Pumping power ρgQH/η, 5 L/s at 30 m, η = 0.6 (hand calc.)",
                   998.2 * 9.81 * 0.005 * 30 / 0.6, float(pu.hydraulic_power(0.005, 30, RHO, G, 0.6)),
                   1e-12, "rel", "§2.6", "W"))

    # ── Waves (§5.2, §5.7) ──
    c.append(Check("1.23", "Rigid pipe limit: a → √(K/ρ)",
                   float(np.sqrt(K / RHO)), float(wv.wave_speed(K, RHO, 0.1, 0.01, 1e18, 1.0)), 1e-6, "rel", "§5.2", "m/s"))
    c.append(Check("1.24", "Thick-wall c1 → thin-wall 1 − ν² when e/D → 0",
                   1 - 0.46 ** 2, wv.c1_factor("thick_throughout", 0.46, 1.0, 1e-7), 1e-5, "rel", "§5.2"))
    hand_a = np.sqrt((2.2e9 / 998.2) / (1 + 1.0 * 2.2e9 * D63 / (1.1e9 * E63)))
    c.append(Check("1.25", "Wave speed HDPE PE100 Ø63 SDR11, free (hand calc.)",
                   float(hand_a), wv.pipe_wave_speed(P, "PE100", D63, E63), 1e-9, "rel", "§5.2", "m/s"))
    a_air = wv.pipe_wave_speed(P, "PE100", D63, E63, anchoring="thick_throughout", alpha_g=1e-3, h_gauge=20.39)
    c.append(Check("1.26", "0.1 % air at 2 bar slows HDPE to ≈ 286 m/s (math note example)",
                   286.2, a_air, 0.005, "rel", "§5.2", "m/s"))
    c.append(Check("1.27", "Joukowsky: a = 335 m/s, ΔV = −1 m/s → ΔH = +34.15 m",
                   335 / 9.81, float(wv.joukowsky(335.0, -1.0, 9.81)), 1e-12, "rel", "§5.7", "m"))
    q0, h0 = 1e-4, 20.0
    dq = (float(lk.orifice(h0 + 1e-6, 0.62, lk.leak_area_for_flow(q0, h0, 0.62))) - q0) / 1e-6
    c.append(Check("1.28", "Leak admittance Y_L = Q/(2h) equals dQ/dh of the orifice law",
                   dq, float(wv.leak_admittance(q0, h0)), 1e-5, "rel", "§5.7", "m²/s"))
    b = wv.char_impedance(335.0, D63)
    c.append(Check("1.29", "Leak reflection → −B·Y/2 for a small leak",
                   -b * 1e-12 / 2, float(wv.leak_reflection(b, 1e-12)), 1e-6, "rel", "§5.7"))
    c.append(Check("1.30", "Leak reflection → −1 for a huge leak (open end)",
                   -1.0, float(wv.leak_reflection(b, 1e6)), 1e-6, "abs", "§5.7"))
    c.append(Check("1.31", "Cavitation threshold at 20 °C (gauge head)",
                   (2339 - 101325) / (998.2 * 9.81),
                   float(wv.cavitation_head(P.p_vap(20.0), P.water.P_ATM.v, RHO, G)), 1e-9, "rel", "§5.6", "m"))
    return c
