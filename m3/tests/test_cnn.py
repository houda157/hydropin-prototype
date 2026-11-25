"""M3 CNN: input features and (if trained weights exist) location accuracy."""
import numpy as np
import pytest

from m3.calibrate import with_creep
from m3.cnn import MODEL_PATH, N_CHANNELS, N_SAMPLES, features, reference_trace
from m3.locate import measure
from m3.moc import leak_cda_for_fraction, load_setup

M = load_setup(viscoelastic=False)
CREEP = with_creep(M, 1.0)


def _trace(pipe, x, sigma=0.0, seed=0):
    true = pipe.with_(x_leak=x, leak_cda=leak_cda_for_fraction(pipe, 0.05, x), duration=1.2)
    return measure(true, sigma_m=sigma, rng=np.random.default_rng(seed))


def test_features_shape_and_scaling():
    t, h = _trace(M, 80.0)
    f = features(h, reference_trace(M), M, M.a, 0.0, 1.0)
    assert f.shape == (N_CHANNELS, N_SAMPLES)
    assert abs(f[0].max() - 1.0) < 0.05          # surge ~ 1 in Joukowsky units
    assert abs(f[1]).max() < 2.0                  # residual in echo units
    assert np.abs(f[2][:int((M.t_close + M.Tc) * 2000)]).max() == 0.0   # rate muted during closure
    assert np.all(f[3] == 0.0) and np.all(f[4] == 1.0)   # creep scale and calibration flag
    batch = features(h[None], reference_trace(M)[None], M, np.array([M.a]), np.array([0.0]), np.array([1.0]))
    assert np.allclose(batch[0], f)


needs_cnn = pytest.mark.skipif(not MODEL_PATH.exists(), reason="CNN not trained (python -m m3.cnn data; train)")


@needs_cnn
@pytest.mark.parametrize("x", [40.0, 90.0, 130.0])
def test_cnn_elastic_pipe_no_calibration(x):
    pytest.importorskip("torch")
    from m3.cnn import cnn_locate
    t, h = _trace(M, x, sigma=0.02, seed=7)
    assert cnn_locate(M, t, h) == pytest.approx(x, abs=5.0)


@needs_cnn
@pytest.mark.parametrize("x", [40.0, 90.0, 130.0])
def test_cnn_creeping_pipe_calibrated(x):
    pytest.importorskip("torch")
    from m3.cnn import cnn_locate
    t, h = _trace(CREEP, x, sigma=0.02, seed=8)
    calibrated = with_creep(M.with_(a=M.a * 1.005, f=0.021), 0.95)   # a near, not perfect, calibration
    assert cnn_locate(M, t, h, calibrated=calibrated) == pytest.approx(x, abs=5.0)
