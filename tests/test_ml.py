import numpy as np
import pandas as pd

from ml.features import add_features, feature_columns
from ml.predict import predict_frame
from ml.train import build_dataset, train
from simulator.scenarios import build_scenario
from simulator.sim import simulate


def test_features_are_causal():
    df, _ = simulate(build_scenario("leak_L1", duration_s=40, seed=1))
    base = add_features(df)
    poisoned = df.copy()
    poisoned.loc[60:, [c for c in poisoned.columns if c.endswith("_lpm")]] = 999.0
    after = add_features(poisoned)
    for col in feature_columns():
        assert base[col].iloc[30] == after[col].iloc[30], col


def test_feature_matrix_has_no_nan_and_expected_columns():
    df, _ = simulate(build_scenario("baseline", duration_s=20, seed=1))
    feats = add_features(df)
    X = feats[feature_columns()]
    assert not X.isna().any().any()
    assert len(feature_columns()) == len(set(feature_columns()))


def test_train_and_generalise_to_unseen_seed(tmp_path):
    model_path = tmp_path / "model.joblib"
    metrics = train(seeds=(1, 2), duration_s=90, n_estimators=120, out=model_path, seed=0)
    assert metrics["macro_f1"] > 0.75, metrics
    assert metrics["binary_recall"] > 0.70, metrics
    assert model_path.exists()

    import joblib

    bundle = joblib.load(model_path)
    unseen, _ = simulate(build_scenario("leak_L2", duration_s=90, seed=99, leak_size="medium"))
    out = predict_frame(bundle, unseen)
    assert out["pred_leak"].mean() > 0.5
    predicted = out.loc[out["pred_leak"], "pred_label"].mode().iloc[0]
    assert predicted == "leak_L2"


def test_build_dataset_labels_and_groups_are_consistent():
    X, y, groups = build_dataset(seeds=(1,), duration_s=30)
    assert X.shape[0] == len(y) == len(groups)
    assert set(np.unique(y)).issubset({0, 1, 2, 3})
    assert len(np.unique(groups)) == 14  # baseline + 9 leaks + incipient + ripple + dropout + drift


def test_train_on_real_csv_directory_handles_partial_classes(tmp_path):
    data_dir = tmp_path / "real"
    data_dir.mkdir()
    for seed, name in ((1, "baseline_01"), (2, "baseline_02")):
        df, _ = simulate(build_scenario("baseline", duration_s=40, seed=seed))
        df.to_csv(data_dir / f"{name}.csv", index=False)
    for seed, name in ((1, "leak_L2_01"), (2, "leak_L2_02")):
        df, _ = simulate(build_scenario("leak_L2", duration_s=40, seed=seed, leak_size="medium"))
        df.to_csv(data_dir / f"{name}.csv", index=False)

    model_path = tmp_path / "real_model.joblib"
    metrics = train(
        data_dir=data_dir,
        n_estimators=20,
        out=model_path,
        seed=0,
        holdout_dir=None,
    )
    assert metrics["n_samples"] == 320  # 4 runs x 40 s x 2 Hz
    assert metrics["macro_f1"] > 0.5, metrics

    import joblib

    bundle = joblib.load(model_path)
    assert bundle["classes"] == ["none", "leak_L2"]
    unseen, _ = simulate(build_scenario("leak_L2", duration_s=40, seed=99, leak_size="medium"))
    out = predict_frame(bundle, unseen)
    predicted = out.loc[out["pred_leak"], "pred_label"].mode().iloc[0]
    assert predicted == "leak_L2"
