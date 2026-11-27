# M3 data pipeline – how the wave data is made, what it contains, how it is used

**Everything in this document is simulation.** No data here comes from a real pipe or
from the bench. Every value is set in `m3/params.yaml` or in the code named below.

```
 m3/params.yaml ──► moc.load_setup() ──► PipeSetup (nominal pipe)
                                              │
            ┌─────────────────────────────────┼──────────────────────────────────┐
            ▼                                 ▼                                  ▼
  (A) validation traces             (B) sweep traces                    (C) CNN training traces
  validate.py, tests/               sweep.py, plot_focus.py              cnn.py data
  → out/validation.json             → out/sweep.json                     → out/cnn_data.npz (not in git)
  → m3_validation.png               → m3_accuracy.png                          │
                                    → m3_time_reversal.png                     ▼
                                              ▲                          cnn.py train
                                              │                          → out/cnn.pt, out/cnn_eval.json
                                              └──────── cnn_locate() ◄─────────┘

  (E) calibration: calibrate.py → out/calibration.json  (one leak-free valve test → fitted a, f, creep)
        │ used by tr_cal / mfp_cal / cnn_cal and by the CNN training (section 4.1)
        ▼
  (D) creep study: ve_study.py → out/ve_study.json, m3_viscoelastic.png
      (3 real pipes: elastic / creep / creep of another shape; every locator, without calibration,
       with lab creep, and calibrated)
```

---

## 1. The physics model all datasets come from

### 1.1 The pipe (`m3/params.yaml` → `PipeSetup`)

| Parameter | Value | Where it comes from |
|---|---|---|
| Length `L` | 150 m | assumption (as in the earlier simulation) |
| Inner diameter `D` | 0.05 m (area 1.963 × 10⁻³ m²) | assumption (PE 63 class) |
| Wave speed `a` | 350 m/s | brief: 300–400 m/s in PE |
| Darcy friction `f` | 0.02 | assumption |
| Reservoir head `H_res` | 30 m | assumption (~3 bar sub-main) |
| Velocity before closure `V0` | 0.5 m/s → `Q0` = 0.982 L/s | assumption |
| Valve closure time `Tc` | 25 ms, linear (`closure_exp` = 1) | brief |
| Closure start `t_close` | 0.05 s | chosen so each trace has 50 ms before the wave |
| Grid | `N` = 900 reaches → `dx` = 0.1667 m, `dt` = `dx/a` = 0.476 ms | chosen so `dt` < 0.5 ms (2 kHz output) |
| Simulated time | 2.0 s (CNN traces: 1.3 s, first 1.1 s kept) | ≥ one full round trip 2L/a = 0.857 s |
| Sensor sampling | 2 kHz | master document (24-bit ADC ≥ 2 kHz) |
| Pipe wall | elastic by default; optional creep (section 6) | `params.yaml: viscoelastic` |

Layout: **reservoir (x = 0) → pipe → leak at `x_leak` → fast valve at x = 150 m. The
sensor sits at the valve.** Positions are measured from the reservoir.

### 1.2 The solver (`m3/moc.py`)

1. **Leak size.** `leak_cda_for_fraction(setup, fraction, x)` turns "leak = fraction × Q0"
   into an orifice size Cd·A:
   - Q_L = fraction × Q0;
   - h = H_res − R (Q0 + Q_L)² i, with R = f·dx / (2 g D A²) and i = the leak's grid index;
   - Cd·A = Q_L / √(2 g h).
2. **Grid snapping.** The leak sits on grid node `i = round(x / dx)`, clamped to 1…N−1, so
   the real position is `i·dx`. That is at most 0.083 m from the requested one.
3. **Steady state.** `steady_state()` computes the starting condition: head falls linearly
   with friction, the flow is Q0 + Q_L upstream of the leak and Q0 downstream. The valve
   coefficient is Cv = Q0 / √H(valve).
4. **Time stepping.** `simulate()` uses the method of characteristics (equations at the
   top of `moc.py`):
   - interior nodes: C+ and C− characteristics with friction;
   - reservoir: H = H_res;
   - valve: Q = τ(t)·Cv·√H, where τ goes 1 → 0 over `Tc`;
   - leak node: a quadratic in √H, with separate flows on each side of the leak;
   - optional wall creep: an extra retarded-strain term on both characteristics (section 6.1).
5. **Sampling.** `Result.sampled(fs)` linearly interpolates the valve head onto a 2 kHz
   grid. That 2 kHz series is "the sensor recording".
6. **Noise.** `locate.measure(setup, fs, sigma_m, rng)` = `sampled(2000)` + Gaussian noise
   N(0, `sigma_m`) on every sample. Noise is in **metres of head**; 0.1 m ≈ 1 kPa.

### 1.3 Checks that the model is right (before any data was used)

`m3/tests/test_moc.py` and `python -m m3.validate`:

| Check | Expected | Result |
|---|---|---|
| Joukowsky jump (no friction, instantaneous closure) | a·V0/g = 17.845 m | 17.845 m (error 0) |
| Oscillation period | 4L/a = 1.714 s | 1.714 s (error 2 × 10⁻¹⁶) |
| Grid convergence (N vs 2N) | difference < 2 % of the jump | passes |
| Steady state + leak mass balance | Q_up − Q_down = Q_L | passes (1e-9) |
| Echo position, 5 % leak at 20/60/100/140 m | within 1 m | 0.25 m off |

---

## 2. Dataset A – validation traces

| | |
|---|---|
| Made by | `python -m m3.validate` (also re-made inside `m3/tests/test_moc.py`) |
| Cases | 1) no friction, instantaneous closure, no leak, 4 s; 2) nominal pipe, no leak; 3) nominal pipe, 5 % leak at 100 m |
| Noise | none |
| Output | `m3/out/validation.json`, `report/figures/m3_validation.png` |

**`validation.json` fields**

| Field | Meaning |
|---|---|
| `setup` | `L_m, D_m, a_mps, darcy_f, H_res_m, V0_mps, closure_ms, dx_m, dt_ms, fs_hz` |
| `joukowsky` | `expected_m`, `simulated_m` (mean head rise on the first plateau), `rel_error` |
| `period` | `expected_s` (4L/a), `simulated_s` (2 × mean time between sign changes of H − H0), `rel_error` |
| `echo` | `x_leak_true_m`, `x_leak_est_m`, `error_m`, `echo_amplitude_m` (0.235 m), `leak_fraction`, `note` |
| `min_head_m` | lowest head anywhere in the pipe (> 0, so no column separation) |

**Used for:** proving the solver is correct (report).

---

## 3. Dataset B – comparison ("sweep") traces

### 3.1 How each trace is made (`m3/sweep.py`, `_evaluate`)

1. **The true pipe** is always the nominal pipe (a = 350 m/s), with a 5 % leak (`LEAK_FRACTION`).
2. **Leak positions:** `POSITIONS` = 30, 50, 75, 100, 125, 140 m. These are inside the zone all
   methods cover. Blind zones: ~4 m at the sensor, ~12 % of L at the reservoir end.
3. **The recording:** `measure(true, sigma_m=σ, rng=default_rng([seed, int(x·10), int(σ·10⁴)]))`,
   a 2 s trace at 2 kHz = 4,000 samples.
4. **Noise sweep:** σ ∈ {0, 0.01, 0.02, 0.05, 0.1, 0.2} m × 6 positions × 3 seeds (0, 1, 2)
   = **108 traces**. The locators use the correct model (a = 350).
5. **Wave-speed sweep:** model error e ∈ {−10, −5, −2, 0, +2, +5, +10} %, σ = 0.02 m,
   × 6 positions × 3 seeds = **126 traces**. The locators get a model with
   a = 350·(1 + e) while the true pipe stays at 350. This plays the role of "we don't
   know the real wave speed".

### 3.2 What is run on each trace (`m3/locate.py`, `m3/cnn.py`)

All model-based locators start from the **residual rate** `residual_rate()`:
1. simulate the intact pipe (no leak) with the *model's* parameters and sample it at 2 kHz;
2. r = recording − model trace, low-pass filtered (4th-order Butterworth, 60 Hz, zero-phase);
3. take dr/dt;
4. multiply by a window: 0 until `t_close + Tc + 2 ms` (5 ms ramp), 1 until
   `t_close + 2L(1 − u)/a` (10 ms ramp down), with u = 0.12. This keeps the first round
   trip only.

| Key in the row | Method | How |
|---|---|---|
| `tr` | time reversal, model `a` | inject the time-reversed residual rate at the sensor of a linear frictionless MOC model; E(x) = Σₜ p_back(x, T−t) · ṗ_inc(x, t); estimate = argmax \|E\| |
| `tr_id` | time reversal, identified `a` | `estimate_wave_speed()` reads the reservoir-return time (half-height crossing of the surge drop) → a = 2L / (t − t_close − Tc/2); then `tr` with that `a` and u = 0.03 |
| `mfp` | matched-field | replica bank `mfp_bank()`: a 5 % leak simulated at every 1 m (x = 1…149, 149 replicas) with the model; score = normalised squared correlation (Bartlett) with the measured residual rate; estimate = argmax |
| `echo` | echo time | time of the largest \|residual rate\| → d = a (t − t_close − Tc/2)/2, x = L − d |
| `cnn` | trained CNN, no calibration | `cnn_locate(model, t, h)`: wave speed read off the recording, f = 0.02, typical creep → reference → features (4.3) → network → x. `model.a` is not used |
| `cnn_cal` | trained CNN, calibrated | `cnn_locate(model, t, h, calibrated=…)`: the pipe was calibrated once on a leak-free test (section 5; `calibration` in the JSON) |
| `a_identified` | — | the wave speed found by `estimate_wave_speed()` |

### 3.3 Output: `m3/out/sweep.json`

| Field | Meaning |
|---|---|
| `setup` | `L_m, a_true_mps, closure_ms, fs_hz, leak_fraction, positions_m, seeds, echo_amplitude_m, sigma_for_a_sweep_m` |
| `calibration` | the calibrated model's `a_mps, f, creep_scale, rms_m, n_eval, a_start_mps` |
| `rows.noise[]` | one per trace: `x_true, sigma_m, seed, a_identified, tr, tr_id, mfp, echo, cnn, cnn_cal` (estimates in m from the reservoir) |
| `rows.wave_speed[]` | the same, plus `a_err` (the model's relative wave-speed error) |
| `noise.<method>.<σ>` | `mae_m` (mean \|estimate − true\|) and `within_5m` (fraction ≤ 5 m), over 18 traces |
| `wave_speed.<method>.<a_err>` | the same, per wave-speed error |
| `a_identified_rel_error` | `mean` and `max` of \|a_identified / 350 − 1\| (0.46 % / 0.47 %) |
| `runtime_s` | about 7–8 minutes (445 s for the committed run) |

**Used for:** the report chart `report/figures/m3_accuracy.png` (error vs noise, error vs
wave-speed error, all methods). `plot_focus.py` re-makes 3 traces the same way
(x = 35, 90, 135 m; σ = 0.02 m; rng seed = x) for `report/figures/m3_time_reversal.png`.

---

## 4. Dataset C – CNN training traces

### 4.1 How each training pipe is made (`python -m m3.cnn data` → `make_data()`, `_sample_pipe(k)`)

For k = 0 … 11,999 (in parallel, one process per core), with `rng = default_rng([20261125, k])`,
the values are drawn **in this order**:

| # | Value | Distribution | Why |
|---|---|---|---|
| 1 | wave speed `a` | 350 × Uniform(0.90, 1.10) → 315…385 m/s | the real `a` is never known exactly |
| 2 | friction `f` | Uniform(0.015, 0.030) | pipe age and roughness |
| 3 | elastic wall? | yes with probability 0.25 | some pipes barely creep |
| 4 | creep scale `s` | 0 if elastic, else Uniform(0, 1.5) × typical PE creep | creep varies with PE grade, temperature, age |
| 5 | creep of another shape? | probability 0.5 (if creeping): each retardation time × Uniform(0.5, 2) | the model family never matches a real pipe exactly |
| 6 | leak fraction | log-uniform 1 %…10 % of Q0 | small and large leaks |
| 7 | leak position `x` | Uniform(3, 147) m | the whole pipe, blind zones included |
| 8 | calibrated? | yes with probability 0.7 | the CNN must work with and without a field test |
| 9 | calibration errors | a × N(1, 0.01), f × N(1, 0.10), s + N(0, 0.10) | see below |

Then:
1. **true pipe** = nominal geometry with `a`, `f`, creep (`s` × typical compliances, with the typical or the
   drawn retardation times), and a leak sized by `leak_cda_for_fraction(true, fraction, x)`;
2. `x_actual` = `round(x / dx)·dx` (where the solver really puts the leak): **the label**;
3. simulate **1.3 s**, sample at 2 kHz;
4. **reference model** (what the monitoring side believes about the pipe):
   - *calibrated*: the true `a`, `f`, `s` plus the calibration errors (typical creep shape);
   - *uncalibrated*: wave speed read off the trace (`estimate_wave_speed`), `f` = 0.02, `s` = 1 (typical creep);
5. simulate the **intact** reference model → `ref`;
6. keep the first **2,200 samples** (0…1.1 s) of the recording and of `ref`;
7. **no noise is stored**: noise is added during training (4.4).

**Why such large calibration errors?** In simulation, calibration is nearly perfect (section 5:
0.003 % on `a`, 0.4 % on `f`, 0.001 on `s`) because the simulated pipe belongs to the model
family. A real pipe will not, so the CNN is trained with deliberately larger errors
(creep ±0.1 is the tolerance limit found in section 6).

### 4.2 File: `m3/out/cnn_data.npz` (125 MB, compressed, **not committed**; re-make in ~10 min)

| Array | Shape, type | Content |
|---|---|---|
| `traces` | [12000 × 2200] float32 | valve head (m) at 2 kHz, noise-free |
| `refs` | [12000 × 2200] float32 | intact reference-model trace (m) |
| `meta` | [12000 × 10] float32 | `x_actual, a, f, leak_fraction, creep_scale, other_shape, a_ref, f_ref, creep_ref, calibrated` |
| `meta_columns` | [10] str | the column names above |

Shares in the generated file: 25 % elastic, 37 % creep of another shape, 70 % calibrated, creep up to 1.50.

### 4.3 From a trace to the network input (`features(h, ref, model, a_ref, s_ref, calibrated)`)

With `n_pre` = 100 samples (the 50 ms before closure), `t` = sample time:

| Channel | Formula | Meaning |
|---|---|---|
| 0 | (h − mean(h[0:100])) / (a_ref · V0 / g) | the trace in units of the Joukowsky surge (≈ 1 on the plateau); full 1.1 s, so it carries the reservoir-return timing |
| 1 | ((h − ref) − mean of the same over [0:100]) / 0.25 × window | difference from the reference, in echo units |
| 2 | d/dt(low-pass 60 Hz (h − ref)) / 5 m/s × mute × window | the **residual rate**: slow model mismatches vanish, the echo stays sharp (the signal time reversal uses) |
| 3 | `s_ref` (constant) | creep scale of the reference |
| 4 | `calibrated` (constant) | 1 = field-calibrated reference, 0 = not |

- mute = 0 before `t_close + Tc + 2 ms`, ramp to 1 over 5 ms (no echo can return earlier);
- window = 1 until `t_close + 2L(1 − 0.12)/a_ref`, ramp to 0 over 10 ms (first round trip only:
  a slightly wrong reference speed would otherwise put the 17 m reservoir-return mismatch there).

Input shape per trace: **[5 × 2200]**. Target: **`x_actual / 150`** (0…1).

**In use** (`cnn_locate(model, t, h, calibrated=None)`):
- with `calibrated` (the model fitted by `calibrate.calibrate`, section 5): reference = that model, flag 1;
- without: wave speed read off the recording, f = 0.02, typical creep, flag 0.

### 4.4 Training (`python -m m3.cnn train 100` → `train()`)

1. **Split** with `default_rng(20261125).permutation(12000)`: the first **2,000 = test**, the next
   **1,000 = validation**, the remaining **9,000 = training**. The test pipes are never used
   for training or for choosing the model.
2. **Noise, per sample, per batch** (`rng = default_rng([20261125, 100 + epoch])`):
   σ = exp(Uniform(ln 0.003, ln 0.2)) m, 0 for ~10 % of samples; h_noisy = h + N(0, σ).
3. **Validation set:** noise drawn once with `default_rng([20261125, 1])`.
4. **Network** (`build_net()`): 6 blocks [Conv1d k = 7 → BatchNorm → ReLU → Conv1d k = 5 →
   BatchNorm → ReLU → MaxPool 2], channels 16, 32, 32, 64, 64, 64 (first block takes 5 inputs);
   flatten (64 × 34) → Linear 2176 → 128 → ReLU → Dropout 0.1 → Linear 128 → 1.
5. **Optimisation:** SmoothL1 (β = 0.01) on x/L; AdamW (lr 2 × 10⁻³, weight decay 10⁻⁴), OneCycle
   (max lr 3 × 10⁻³); batch 64; **100 epochs** (40 was not enough for this harder task:
   validation error was still falling); `torch.manual_seed(20261125)`.
6. **Model choice:** the epoch with the lowest validation mean error is saved to `m3/out/cnn.pt`.
7. **Test (once, at the end):** σ ∈ {0, 0.02, 0.05, 0.1, 0.2} m, noise with `default_rng([20261125, 2])`.

### 4.5 Output: `m3/out/cnn_eval.json`

| Field | Meaning |
|---|---|
| `n_train`, `n_val`, `n_test` | 9000, 1000, 2000 |
| `val_mae_m` | best validation mean error (m) |
| `calibration_error_sd` | the calibration errors used (4.1) |
| `test_by_sigma.<σ>.<group>` | `n`, `mae_covered_m` (mean \|error\|, leaks 18 m < x < 145 m), `within_5m` |

Groups: `all, calibrated, uncalibrated, elastic_pipe, creeping_pipe, creep_other_shape,
creeping_calibrated, creeping_uncalibrated`.

error (leaks 18–145 m); best validation error 3.69 m:

| σ (m) | all | elastic pipe | creeping, calibrated | creeping, not calibrated | creep of another shape | within 5 m (all) |
|---|---|---|---|---|---|---|
| 0.0 | 0.96 m | 0.91 m | 0.93 m | 1.08 m | 1.07 m | 95 % |
| 0.02 | 1.22 m | 0.99 m | 1.27 m | 1.37 m | 1.63 m | 94 % |
| 0.05 | 3.14 m | 2.82 m | 3.13 m | 3.48 m | 4.12 m | 87 % |
| 0.1 | 6.94 m | 5.65 m | 6.96 m | 8.28 m | 9.01 m | 76 % |
| 0.2 | 11.31 m | 11.73 m | 10.43 m | 12.90 m | 11.99 m | 57 % |

- It now works on **every kind of pipe** (elastic, creeping, creep of another shape, calibrated or not) at about 1 m at normal noise. The v2 CNN failed on creeping pipes (~60 m).
- Calibration helps most when noise is high (σ = 0.1 m: 6.7 m calibrated vs 7.6 m not).
- The errors at high noise come from **tiny leaks**: a 1 % leak's echo (~0.05 m) is buried at σ = 0.1 m. By leak size at σ = 0.1 m (`test_by_leak_size`): 1–2 % → 17.6 m, 2–4 % → 3.3 m, 4–7 % → 1.5 m, 7–10 % → 1.2 m. On the 5 % leaks of the comparison sweep (dataset B) the CNN scores 0.9 m uncalibrated and 0.7 m calibrated up to σ = 0.1 m.
- Calibrated time reversal remains the most precise M3 method (0.3–0.5 m); the CNN is the most robust to very high noise (σ = 0.2 m) and needs no transient model at run time.

**History of the CNN:**

| Version | Trained on | Inputs | Low noise | σ = 0.1 m | Problem |
|---|---|---|---|---|---|
| v1 (24 Nov) | elastic pipes, nominal reference | 2 | 2.1 m | 4.5 m | fails if the model's wave speed is wrong |
| v2 (25 Nov) | elastic pipes, wave speed read off the trace | 2 | 0.65 m | 1.5 m | fails on creeping pipes (~60 m) |
| v3 (25 Nov) | elastic + creeping, calibrated or not | 5 | 0.96 m | 6.9 m (1.5 m for leaks ≥ 4 %) | tiny leaks in noise (section 8) |

**Used for:** the CNN numbers in the report, `cnn` / `cnn_cal` in datasets B and D.

---

## 5. Calibration from one leak-free valve test (`m3/calibrate.py`)

**The field procedure:** at installation, close the valve once while the pipe is known to be
leak-free, and record the sensor. Fit the model's unknowns so its intact trace matches that recording:

| Unknown | Start value | How it enters the model |
|---|---|---|
| wave speed `a` | read off the trace (`estimate_wave_speed`) | elastic, instantaneous wave speed |
| friction `f` | 0.02 | Darcy friction |
| creep scale `s` | 1 (and a second start at 0) | creep compliances = s × typical PE values; retardation times fixed |

- **Fit:** Nelder-Mead on (a / a₀, f / f₀, s), minimising the mean squared difference between the
  recording (0…1.3 s at 2 kHz) and the intact model; 2 starts (creeping / elastic); about 45 s.
- **Output:** a `PipeSetup` used by every locator (`tr_cal`, `mfp_cal`, `cnn_cal`).

### 5.1 Accuracy (`python -m m3.calibrate` → `m3/out/calibration.json`)

48 random pipes: a = 350 × U(0.9, 1.1), f = U(0.015, 0.030), creep 0 (1 pipe in 4) or U(0, 1.5),
σ = 0.05 m, rng `default_rng([20261125, k])`.

| | mean error | spread (std) | worst |
|---|---|---|---|
| wave speed | 0.0002 % | 0.001 % | 0.003 % |
| friction | 0.01 % | 0.16 % | 0.38 % |
| creep scale | 0.000001 | 0.0004 | 0.0012 |

The fit's remaining error is 0.050 m on average: exactly the sensor noise, i.e. the model
reproduces the pipe perfectly. **This is optimistic:** the simulated pipe has the same kind of creep as the model.

### 5.2 Model-form test (`python -m m3.calibrate formtest` → `calibration.json: model_form_test`)

Real pipe with creep of **another shape** (retardation times 0.1 / 1 / 3 s, or 2 elements
0.2 / 2 s). The model family cannot match it: the fit is off by 0.41 m and 0.76 m RMS (more than
the echo). Yet time reversal with the calibrated model still finds 5 % leaks at
30–140 m within **0.33 m on average** (worst 1.2 m). The leftover mismatch is slow and smooth,
and the residual rate ignores it.

**Fields:** `setup`, `errors.{a_rel, f_rel, creep_scale_abs}.{mean, std, max_abs}`, `fit_rms_m`,
`rows[]` (`k, a_true, f_true, s_true, a_mps, f, creep_scale, rms_m, n_eval, a_start_mps`),
`model_form_test.cases[]` (`case, true_J_per_Pa, true_tau_s, calibrated, tr_error_m_by_position, tr_mae_m`).

---

## 6. Dataset D – pipe-wall creep study (`python -m m3.ve_study`)

### 6.1 The creep model (`m3/moc.py`, `params.yaml: viscoelastic`)

Real PE pipe walls **creep**: they keep stretching for a while after the pressure changes,
which absorbs wave energy. The solver models a **generalised Kelvin-Voigt** wall (Covas et al.
2005): K elements, each with a compliance J_k and a retardation time τ_k.
- Retarded strain: τ_k dε_k/dt + ε_k = J_k · c · (H − H0), with c = α ρ g D / (2e).
- This adds −(2a²Δt/g)·Σ dε_k/dt to both characteristics, so H_P = (C_P + C_M)/2 − (2a²Δt/g)·Σ dε_k/dt;
  Q_P is unchanged. Each dε_k/dt uses an exact exponential update over Δt, so every
  boundary (reservoir, valve, leak) stays solvable in closed form.
- With no elements the solver is **exactly** the elastic one (bit-for-bit, tested).

| Parameter | Value | Source |
|---|---|---|
| `J_per_Pa` | 1.0, 1.0, 1.0 × 10⁻¹⁰ 1/Pa (total ~40 % of PE's elastic compliance) | **illustrative assumption** |
| `tau_s` | 0.05, 0.5, 1.5 s | **illustrative**; HDPE fits use several elements from ~0.05 s to seconds |
| `wall_m` | 0.0058 m (D/e ≈ 8.6) | PE 63 PN10 |
| `alpha` | 1.0 | pipe constraint coefficient |
| `enabled` | false | off for datasets A–B; `load_setup(viscoelastic=True)` turns it on |

### 6.2 Traces

- **Three real pipes:** `elastic`; `creep` (typical); `creep_other` (same compliances, retardation
  times 0.1 / 1 / 3 s).
- 5 % leak at x = 30, 50, 75, 100, 125, 140 m; σ ∈ {0.02, 0.05, 0.1} m; seeds 0, 1, 2; noise rng
  `default_rng([seed, int(x·10), int(σ·10⁴)])` (the same draws as dataset B) → 3 × 3 × 6 × 3 = **162 traces**.
- **Calibration:** one leak-free test per real pipe (σ = 0.05 m, rng `default_rng([20261125, 9, i])`).
- **Methods:**
  - no calibration: `tr`, `tr_id`, `mfp`, `echo` (elastic model), `cnn` (uncalibrated route);
  - lab creep: `tr_ve`, `mfp_ve` (the typical creep, as if measured in a lab);
  - calibrated: `tr_cal`, `mfp_cal`, `cnn_cal` (each pipe's own calibrated model).
- **Sensitivity:** real pipe = typical creep, σ = 0.05 m, seed 0; time reversal with the lab creep
  compliances × 0.5…1.5.

### 6.3 Output: `m3/out/ve_study.json`

| Field | Meaning |
|---|---|
| `creep_model` | `J_per_Pa, tau_s, wall_m, alpha, other_shape_tau_s, note` |
| `setup` | `positions_m, noise_m, seeds, leak_fraction, calibration_sigma_m, truths` |
| `calibration.<truth>` | the fitted `a_mps, f, creep_scale, rms_m, n_eval, a_start_mps` |
| `signal.<truth>` | `surge_m, swing_first_s_m, swing_after_5s_m, echo_step_90m_m` |
| `traces.<truth>` | `t_s, H_m`: 6 s no-leak valve trace (every 40th step), for the figure |
| `summary.<truth>.<method>.<σ>` | `mae_m`, `within_5m` over 18 traces |
| `labels` | method key → readable name |
| `creep_model_sensitivity.by_scale.<s>` | `mae_m, max_m, errors_m` |
| `rows[]` | one per trace: `truth, x_true, sigma_m, seed, a_identified` and every method's estimate |

### 6.4 Results and use

Mean absolute error at σ = 0.05 m (σ = 0.1 m in brackets), 5 % leak, 18 traces per cell:

| Method | elastic pipe | typical creep | creep of another shape |
|---|---|---|---|
| time reversal, elastic model | 0.3 m (0.4) | 57.3 m (55.9) | 51.4 m (48.4) |
| time reversal, elastic model, a identified | 0.2 m (0.4) | 57.3 m (55.9) | 51.3 m (48.4) |
| matched-field, elastic model | 0.1 m (0.2) | 57.2 m (55.9) | 43.5 m (44.6) |
| echo, elastic model | 0.8 m (19.2) | 58.5 m (49.2) | 37.2 m (39.0) |
| CNN, no calibration | 1.0 m (0.9) | 0.9 m (2.2) | 1.2 m (1.5) |
| time reversal, lab creep | 58.2 m (58.2) | 0.3 m (0.6) | 6.7 m (22.7) |
| matched-field, lab creep | 58.2 m (58.3) | 0.2 m (0.4) | 0.2 m (13.4) |
| time reversal, calibrated | 0.3 m (0.4) | 0.3 m (0.6) | 0.2 m (0.5) |
| matched-field, calibrated | 0.1 m (0.2) | 0.2 m (1.2) | 0.1 m (0.4) |
| CNN, calibrated | 0.8 m (0.9) | 0.9 m (1.1) | 4.6 m (13.1) |

- **Calibration** fitted: elastic pipe a = 350.0 m/s, creep 0.00; typical creep a = 350.0, creep 1.00 (fit RMS = noise, 0.05 m); creep of another shape a = 350.9, f = 0.033 (true 0.02), creep 0.67, fit RMS 0.41 m (the model family cannot match it).
- **Without calibration, every model-based method fails on creeping pipes** (about 37–58 m): creep changes the whole trace by up to 1.8 m, about 10× the echo, and the estimates collapse next to the sensor.
- **Lab creep** works only if the real creep matches it: it fails on the elastic pipe (58 m) and on the other shape (time reversal 6.7 m; matched-field 13 m at σ = 0.1 m).
- **Calibrated time reversal and matched-field work on all three pipes** (0.1–0.6 m; matched-field 1.2 m on typical creep at σ = 0.1 m), including the pipe the model family cannot reproduce. **This is the recommended M3 procedure.**
- **CNN without calibration** works on all three pipes (0.9–2.2 m), reading the wave speed off the trace.
- **CNN calibrated** works on elastic and typical-creep pipes (0.7–1.2 m) but **fails on the other creep shape** (4.6 m, 13 m at σ = 0.1 m): there the real calibration compensates the wrong shape with a much too high friction (+65 %), a kind of reference error the CNN never saw (its training used synthetic calibration errors of ±10 % on f). Fix: run the real calibration on every training pipe (~7 h of computing); until then, use the uncalibrated CNN as the cross-check.
- **Sensitivity** (no calibration, typical creep): time reversal stays < 0.7 m when the model's creep is within −10 % to +20 % of the truth; at −20 % the mean error is already 19 m.

**Used for:** `report/figures/m3_viscoelastic.png` (`python -m m3.ve_study plot` redraws it from the
JSON) and the report's message: **on PE pipes, calibrate the model once per pipe.**

---

## 7. Re-making everything

```powershell
.venv-sim\Scripts\python -m pytest m3/tests          # solver, creep, calibration, locators, CNN
.venv-sim\Scripts\python -m m3.validate              # dataset A
.venv-sim\Scripts\python -m m3.calibrate             # calibration accuracy (~7 min)
.venv-sim\Scripts\python -m m3.calibrate formtest    # model-form test (~2 min)
.venv-sim\Scripts\python -m m3.cnn data              # dataset C (~10 min)
.venv-sim\Scripts\python -m m3.cnn train 100         # CNN (~45 min on CPU)
.venv-sim\Scripts\python -m m3.sweep                 # dataset B + comparison chart (~8 min)
.venv-sim\Scripts\python -m m3.ve_study              # dataset D + creep figure (~6 min)
.venv-sim\Scripts\python -m m3.plot_focus            # focusing figure
```

All random draws use fixed seeds, so re-running gives the same data. The CNN weights can
differ in the last digits between machines (floating-point and thread order).

## 8. Limits of this data (say them in the report)

- One straight pipe, one sensor at the valve: no junctions, no branches, no trapped air.
- Steady friction only (no unsteady friction).
- Creep values are **illustrative** and still need an expert check. Real pipes need the
  one-time calibration; its simulated accuracy is optimistic (5.1), the model-form test (5.2) is the fairer check.
- The leak is a fixed orifice. Noise is white Gaussian. Wave speed, friction and creep are
  uniform along the pipe.
- The CNN (v3) handles creep and missing calibration, but **tiny leaks (1–2 %) are lost in noise** (17.6 m at σ = 0.1 m, while leaks ≥ 4 % stay at 1.2–1.5 m). The 1 % farm-scale leaks need a quieter sensor, longer averaging or repeated valve tests.
