"""Field calibration of the M3 pipe model from one leak-free valve test."""
import numpy as np
import pytest

from m3.calibrate import CAL_WINDOW_S, TYPICAL, calibrate, creep_scale, with_creep
from m3.locate import measure, time_reversal
from m3.moc import leak_cda_for_fraction, load_setup

BASE = load_setup(viscoelastic=False)


def test_creep_scale_round_trip():
    assert creep_scale(with_creep(BASE, 0.0)) == 0.0
    assert not with_creep(BASE, 0.0).viscoelastic
    assert creep_scale(with_creep(BASE, 0.7)) == pytest.approx(0.7)
    assert with_creep(BASE, 0.7).ve_tau == TYPICAL.ve_tau


@pytest.fixture(scope="module")
def calibrated_creeping_pipe():
    true = with_creep(BASE.with_(a=335.0, f=0.026), 0.8)
    t, h = measure(true.with_(duration=CAL_WINDOW_S + 0.01), sigma_m=0.05, rng=np.random.default_rng(11))
    model, info = calibrate(BASE, t, h)
    return true, model, info


def test_calibration_recovers_wave_speed_friction_creep(calibrated_creeping_pipe):
    true, model, info = calibrated_creeping_pipe
    assert model.a == pytest.approx(335.0, rel=0.005)
    assert model.f == pytest.approx(0.026, rel=0.05)
    assert creep_scale(model) == pytest.approx(0.8, abs=0.05)
    assert info["rms_m"] < 0.06                    # fit error ~ the 0.05 m sensor noise


def test_calibrated_model_locates_leak_on_creeping_pipe(calibrated_creeping_pipe):
    true, model, _ = calibrated_creeping_pipe
    for x in (40.0, 110.0):
        leak = true.with_(x_leak=x, leak_cda=leak_cda_for_fraction(true, 0.05, x))
        t, h = measure(leak, sigma_m=0.05, rng=np.random.default_rng(int(x)))
        assert time_reversal(model, t, h, a_uncertainty=0.03).x_est == pytest.approx(x, abs=1.0)
        assert abs(time_reversal(BASE, t, h).x_est - x) > 10     # the uncalibrated elastic model fails
