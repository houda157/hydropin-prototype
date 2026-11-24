"""M3 CNN: input features and (if trained weights exist) location accuracy."""
import numpy as np
import pytest

from m3.cnn import MODEL_PATH, N_SAMPLES, features, reference_trace
from m3.locate import measure
from m3.moc import leak_cda_for_fraction, load_setup

M = load_setup()


def _trace(x, sigma=0.0, seed=0):
    true = M.with_(x_leak=x, leak_cda=leak_cda_for_fraction(M, 0.05, x), duration=1.2)
    return measure(true, sigma_m=sigma, rng=np.random.default_rng(seed))


def test_features_shape_and_scaling():
    t, h = _trace(80.0)
    f = features(h.astype(np.float32), reference_trace(M), M)
    assert f.shape == (2, N_SAMPLES)
    assert abs(f[0].max() - 1.0) < 0.05          # surge ~ 1 in Joukowsky units
    assert abs(f[1]).max() < 2.0                  # residual in echo units
    assert np.allclose(features(h[None].astype(np.float32), reference_trace(M), M)[0], f)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="CNN not trained (python -m m3.cnn data; train)")
@pytest.mark.parametrize("x", [40.0, 90.0, 130.0])
def test_cnn_locates_leak_with_moderate_noise(x):
    torch = pytest.importorskip("torch")  # noqa: F841
    from m3.cnn import cnn_locate
    t, h = _trace(x, sigma=0.02, seed=7)
    assert cnn_locate(M, t, h) == pytest.approx(x, abs=5.0)
