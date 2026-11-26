"""M3 locators: time reversal, matched-field, echo, wave-speed identification."""
import numpy as np
import pytest

from m3.locate import (echo_locate, estimate_wave_speed, matched_field, measure, mfp_bank,
                       time_reversal)
from m3.moc import leak_cda_for_fraction, load_setup

M = load_setup()


def _trace(x, sigma=0.0, seed=0, frac=0.05):
    true = M.with_(x_leak=x, leak_cda=leak_cda_for_fraction(M, frac, x))
    return measure(true, sigma_m=sigma, rng=np.random.default_rng(seed))


@pytest.mark.parametrize("x", [30.0, 75.0, 120.0, 140.0])
def test_time_reversal_focuses_on_leak_noise_free(x):
    t, h = _trace(x)
    r = time_reversal(M, t, h)
    assert r.x_est == pytest.approx(x, abs=1.0)
    far = np.abs(r.x - r.x_est) > 10
    assert r.score[far].max() < 0.3          # one clear focus, no strong side-lobes


@pytest.mark.parametrize("x", [50.0, 100.0])
def test_time_reversal_with_noise(x):
    t, h = _trace(x, sigma=0.05, seed=3)
    assert time_reversal(M, t, h).x_est == pytest.approx(x, abs=2.0)


def test_leak_size_does_not_move_the_focus():
    for frac in (0.02, 0.10):
        t, h = _trace(80.0, frac=frac)
        assert time_reversal(M, t, h).x_est == pytest.approx(80.0, abs=1.0)


@pytest.fixture(scope="module")
def bank():
    return mfp_bank(M, step_m=2.0)


@pytest.mark.parametrize("x", [40.0, 100.0])
def test_matched_field_locates_leak(bank, x):
    t, h = _trace(x, sigma=0.02, seed=1)
    assert matched_field(M, t, h, bank=bank).x_est == pytest.approx(x, abs=2.0)


def test_echo_locates_leak():
    t, h = _trace(90.0, sigma=0.02, seed=2)
    assert echo_locate(M, t, h) == pytest.approx(90.0, abs=2.0)


def test_wave_speed_identified_from_trace():
    t, h = _trace(90.0, sigma=0.05, seed=4)
    wrong = M.with_(a=0.9 * M.a)
    assert estimate_wave_speed(wrong, t, h) == pytest.approx(M.a, rel=0.01)


def test_wrong_wave_speed_scales_the_error_and_identification_fixes_it():
    x = 50.0                                     # 100 m from the sensor
    t, h = _trace(x, sigma=0.02, seed=5)
    wrong = M.with_(a=1.05 * M.a)
    err = abs(time_reversal(wrong, t, h).x_est - x)
    assert 3.0 < err < 7.0                       # ~5 % of the 100 m distance
    a_id = estimate_wave_speed(wrong, t, h)
    fixed = time_reversal(wrong.with_(a=a_id), t, h, a_uncertainty=0.03)
    assert fixed.x_est == pytest.approx(x, abs=1.0)
