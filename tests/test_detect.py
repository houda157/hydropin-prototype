import pytest

from detection.baseline import FEATURE_COLUMNS, Baseline
from detection.detect import Detector, DetectorConfig, StreamingDetector, estimate_leak_lpm
from detection.evaluate import evaluate_run
from simulator.scenarios import build_scenario
from simulator.sim import simulate


def run(name, duration=120, seed=3, leak_size=None):
    sc = build_scenario(name, duration_s=duration, seed=seed, leak_size=leak_size)
    df, _ = simulate(sc)
    return df


def fitted_detector(seed=3):
    baseline = Baseline.fit_raw(run("baseline", seed=seed))
    return Detector(baseline, DetectorConfig())


def test_abrupt_leaks_are_detected_with_correct_branch_and_short_delay():
    det = fitted_detector()
    for name, branch in (("leak_L1", "l1"), ("leak_L2", "l2"), ("leak_L3", "l3")):
        ev = evaluate_run(name, run(name), det)
        assert ev.recall > 0.85, (name, ev.recall)
        assert ev.precision > 0.90, (name, ev.precision)
        assert ev.branch_pred == branch, (name, ev.branch_pred)
        assert ev.delay_s is not None and ev.delay_s < 12.0, (name, ev.delay_s)


def test_healthy_ripple_drift_do_not_raise_alarms():
    det = fitted_detector()
    for name in ("baseline", "ripple", "calibration_drift", "dropout"):
        ev = evaluate_run(name, run(name), det)
        assert ev.fp == 0, (name, ev.fp)


def test_incipient_leak_is_detected_but_later():
    det = fitted_detector()
    ev = evaluate_run("incipient", run("leak_L1_incipient"), det)
    assert ev.recall > 0.5, ev.recall
    assert ev.branch_pred == "l1"
    assert ev.delay_s is None or ev.delay_s < 70.0


def test_small_leak_is_harder_than_large_leak():
    det = fitted_detector()
    small = evaluate_run("small", run("leak_L1", leak_size="small"), det)
    large = evaluate_run("large", run("leak_L1", leak_size="large"), det)
    assert large.recall >= small.recall


def test_detector_never_reads_labels():
    det = fitted_detector()
    df = run("leak_L2")
    poisoned = df.copy()
    poisoned["label"] = "none"
    a = det.detect_frame(df).frame["alarm"].to_numpy()
    b = det.detect_frame(poisoned).frame["alarm"].to_numpy()
    assert (a == b).all()


def test_events_are_contiguous_and_branch_tagged():
    det = fitted_detector()
    result = det.detect_frame(run("leak_L1"))
    assert result.events, "expected at least one event"
    first = result.events[0]
    assert first["branch"] == "l1"
    assert first["leak_lpm_est"] > 0.1


def test_leak_size_inversion_is_exact():
    share0 = 1.0 / 3.0
    # baseline branch b=0.5, other branches 1.0, total 1.5; leak 0.3
    assert estimate_leak_lpm(0.8, 1.8, share0) == pytest.approx(0.3)
    assert estimate_leak_lpm(0.5, 1.5, share0) == pytest.approx(0.0)


def test_cusum_alarms_after_four_z3_samples():
    mu = {c: 0.0 for c in FEATURE_COLUMNS}
    sigma = {c: 1.0 for c in FEATURE_COLUMNS}
    base = Baseline(mu=mu, sigma=sigma, window=20)
    det = StreamingDetector(
        base,
        DetectorConfig(window=1, cusum_k=0.8, cusum_h=8.0, min_branch_z=2.5, release_n=10),
    )
    row = {
        "share_l1": 3.0,
        "share_l2": -1.5,
        "share_l3": -1.5,
        "pressure_bar": 0.0,
        "total_lpm": 0.0,
        "main_lpm": 0.0,
        "flow_l1_lpm": 1.0,
        "flow_l2_lpm": 1.0,
        "flow_l3_lpm": 1.0,
    }
    assert [det.update(row)["alarm"] for _ in range(3)] == [False, False, False]
    rec = det.update(row)
    assert rec["alarm"] is True
    assert rec["branch"] == "l1"
    assert rec["cusum"] == pytest.approx(8.8)
