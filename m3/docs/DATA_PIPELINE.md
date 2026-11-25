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
```

---

## 1. The physics model all three datasets come from

### 1.1 The pipe (`m3/params.yaml` → `PipeSetup`)

| Parameter | Value | Where it comes from |
|---|---|---|
| Length `L` | 150 m | role 5 brief (as in the earlier simulation) |
| Inner diameter `D` | 0.05 m (area 1.963 × 10⁻³ m²) | assumption (PE 63 class) |
| Wave speed `a` | 350 m/s | brief: 300–400 m/s in PE |
| Darcy friction `f` | 0.02 | assumption |
| Reservoir head `H_res` | 30 m | assumption (~3 bar sub-main) |
| Velocity before closure `V0` | 0.5 m/s → `Q0` = 0.982 L/s | assumption |
| Valve closure time `Tc` | 25 ms, linear (`closure_exp` = 1) | brief |
| Closure start `t_close` | 0.05 s | chosen so each trace has 50 ms before the wave |
| Grid | `N` = 900 reaches → `dx` = 0.1667 m, `dt` = `dx/a` = 0.476 ms | chosen so `dt` < 0.5 ms (2 kHz output) |
| Simulated time | 2.0 s (CNN traces: 1.11 s) | ≥ one full round trip 2L/a = 0.857 s |
| Sensor sampling | 2 kHz | master document (24-bit ADC ≥ 2 kHz) |

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
   - leak node: a quadratic in √H, with separate flows on each side of the leak.
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

**Used for:** proving the solver is correct (report, mentor review).

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
| `cnn` | trained CNN | `cnn_locate(model, t, h)`: features (section 4.3) from the recording and the model's intact trace → network → x |
| `a_identified` | — | the wave speed found by `estimate_wave_speed()` |

### 3.3 Output: `m3/out/sweep.json`

| Field | Meaning |
|---|---|
| `setup` | `L_m, a_true_mps, closure_ms, fs_hz, leak_fraction, positions_m, seeds, echo_amplitude_m, sigma_for_a_sweep_m` |
| `rows.noise[]` | one per trace: `x_true, sigma_m, seed, a_identified, tr, tr_id, mfp, echo, cnn` (estimates in m from the reservoir) |
| `rows.wave_speed[]` | the same, plus `a_err` (the model's relative wave-speed error) |
| `noise.<method>.<σ>` | `mae_m` (mean \|estimate − true\|) and `within_5m` (fraction ≤ 5 m), over 18 traces |
| `wave_speed.<method>.<a_err>` | the same, per wave-speed error |
| `a_identified_rel_error` | `mean` and `max` of \|a_identified / 350 − 1\| (0.46 % / 0.47 %) |
| `runtime_s` | about 6 minutes |

**Used for:** the report chart `report/figures/m3_accuracy.png` (error vs noise, error vs
wave-speed error, all methods). `plot_focus.py` re-makes 3 traces the same way
(x = 35, 90, 135 m; σ = 0.02 m; rng seed = x) for `report/figures/m3_time_reversal.png`.

---

## 4. Dataset C – CNN training traces

### 4.1 How each trace is made (`python -m m3.cnn data` → `make_data()`, `_sample_pipe(k)`)

For k = 0 … 8,999 (in parallel, one process per core), with `rng = default_rng([20261124, k])`,
the values are drawn **in this order**:

| # | Value | Distribution | Why |
|---|---|---|---|
| 1 | wave speed `a` | 350 × Uniform(0.90, 1.10) → 315…385 m/s | the real `a` is never known exactly |
| 2 | friction `f` | Uniform(0.015, 0.030) | pipe age and roughness |
| 3 | leak fraction | log-uniform 1 %…10 % of Q0 | small and large leaks, small ones as frequent |
| 4 | leak position `x` | Uniform(3, 147) m | the whole pipe, blind zones included |

Then:
- true pipe = nominal with these `a` and `f`, and a leak sized by `leak_cda_for_fraction(true, fraction, x)`;
- `x_actual` = `round(x / dx)·dx` (where the solver really puts the leak); **this is the label**;
- simulate 1.11 s and sample at 2 kHz, keeping the first **2,200 samples** (0…1.1 s): 50 ms
  before closure, the whole first round trip even at a = 315 m/s, and the reservoir return;
- **no noise is stored**: noise is added during training (4.4).

The nominal **intact** trace (a = 350, f = 0.02, no leak) is stored once as `ref`.

### 4.2 File: `m3/out/cnn_data.npz` (49 MB, compressed, **not committed**; re-make in ~2 min)

| Array | Shape, type | Content |
|---|---|---|
| `traces` | [9000 × 2200] float32 | valve head (m) at 2 kHz, noise-free |
| `meta` | [9000 × 4] float32 | columns: `x_actual` (m), `a` (m/s), `f`, `leak_fraction` |
| `ref` | [2200] float32 | intact nominal pipe trace (m) |

Ranges in the generated file: x 3.0–147.0 m, a 315.0–385.0 m/s, f 0.0150–0.0300, leak 1.0–10.0 %.

### 4.3 From a trace to the network input (`features()`)

With `n_pre` = 100 samples (the 50 ms before closure):
- **channel 0** = (h − mean(h[0:100])) / 17.845, i.e. the head change in units of the
  nominal Joukowsky surge (≈ 1 on the plateau);
- **channel 1** = ((h − ref) − mean of the same over [0:100]) / 0.25, i.e. the difference
  from the intact model in units of a typical echo (0.25 m).

Input shape per trace: **[2 × 2200]**. Target: **`x_actual / 150`** (0…1).

### 4.4 Training (`python -m m3.cnn train` → `train()`)

1. **Split** with `default_rng(20261124).permutation(9000)`: the first **1,500 = test**, the next
   **750 = validation**, the remaining **6,750 = training**. The test traces are never used
   for training or for choosing the model.
2. **Noise, per sample, per batch** (`rng = default_rng([20261124, 100 + epoch])`):
   σ = exp(Uniform(ln 0.003, ln 0.2)) m, set to 0 for ~10 % of samples. Then
   h_noisy = h + N(0, σ). The network never sees the same noisy trace twice.
3. **Validation set:** noise drawn once with `default_rng([20261124, 1])`, the same for every epoch.
4. **Network** (`build_net()`, 436,033 parameters):
   - 6 blocks: [Conv1d k = 7 → BatchNorm → ReLU → Conv1d k = 5 → BatchNorm → ReLU → MaxPool 2];
     channels 16, 32, 32, 64, 64, 64;
   - flatten (64 × 34) → Linear 2176 → 128 → ReLU → Dropout 0.1 → Linear 128 → 1.
5. **Optimisation:**
   - loss: SmoothL1 (β = 0.01) on x/L;
   - optimiser: AdamW (lr 2 × 10⁻³, weight decay 10⁻⁴), OneCycle schedule (max lr 3 × 10⁻³);
   - batch 64, **40 epochs**, `torch.manual_seed(20261124)`.
6. **Model choice:** the epoch with the lowest validation mean error is kept (5.24 m on
   noisy validation traces over the whole pipe). It is saved to `m3/out/cnn.pt`
   (`state_dict, n_samples, fs, seed, val_mae_m`).
7. **Test (once, at the end):** for each σ in {0, 0.01, 0.02, 0.05, 0.1, 0.2} m, noise drawn
   with `default_rng([20261124, 2])` on all 1,500 test traces.

### 4.5 Output: `m3/out/cnn_eval.json`

| Field | Meaning |
|---|---|
| `n_train`, `n_val`, `n_test` | 6750, 750, 1500 |
| `val_mae_m` | best validation mean error (m) |
| `test_by_sigma.<σ>.mae_m` | mean \|error\| on all test traces |
| `test_by_sigma.<σ>.mae_covered_m` | the same, on test leaks with 18 m < x < 145 m (the zone the other methods cover) |
| `test_by_sigma.<σ>.within_5m` | fraction with error ≤ 5 m |

Results: `mae_covered_m` = 2.1 m at σ = 0, 2.2 m at 0.02, 4.5 m at 0.1, 9.6 m at 0.2.

**Used for:** the CNN numbers in the report, and the `cnn` estimate in dataset B (the CNN
is run on exactly the same 234 sweep traces as the other methods).

---

## 5. Re-making everything

```powershell
.venv-sim\Scripts\python -m pytest m3/tests          # solver + locators + CNN checks
.venv-sim\Scripts\python -m m3.validate              # dataset A
.venv-sim\Scripts\python -m m3.cnn data              # dataset C (~2 min)
.venv-sim\Scripts\python -m m3.cnn train             # CNN (~10 min on CPU)
.venv-sim\Scripts\python -m m3.sweep                 # dataset B + comparison chart (~6 min)
.venv-sim\Scripts\python -m m3.plot_focus            # focusing figure
```

All random draws use fixed seeds, so re-running gives the same data. The CNN weights can
differ in the last digits between machines (floating-point and thread order).

## 6. Limits of this data (say them in the report)

- One straight pipe, one sensor at the valve: no junctions, no branches, no trapped air.
- Steady friction only: no unsteady friction, no PE viscoelastic damping. Real echoes
  would be weaker and more spread out.
- The leak is a fixed orifice. Noise is white Gaussian. Wave speed and friction are
  uniform along the pipe.
- In the wave-speed sweep, the model is wrong while the pipe is nominal. In the CNN
  training, the pipe varies while the model stays nominal. The CNN was not trained for
  the first case, which is why it does worse there.
