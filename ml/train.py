"""Train the leak classifier on simulated runs with group-aware validation.

    python -m ml.train --out models/hydropin_rf.joblib --seeds 1 2 3

Splits are by *run*, never by sample, because neighbouring samples are almost
identical. Reporting sample-wise random CV here would be cheating.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict

from hydropin import config
from simulator.scenarios import build_scenario
from simulator.sim import simulate

from .features import add_features, feature_columns

LABEL_TO_INT = {lab: i for i, lab in enumerate(config.LABELS)}
INT_TO_LABEL = {i: lab for lab, i in LABEL_TO_INT.items()}


def build_dataset(
    seeds: tuple[int, ...] = (1, 2, 3, 4), duration_s: float = 120.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames: list[pd.DataFrame] = []
    run_id = 0
    for seed in seeds:
        jobs = [("baseline", None)]
        for branch in ("L1", "L2", "L3"):
            for size in ("small", "medium", "large"):
                jobs.append((f"leak_{branch}", size))
        jobs += [
            ("leak_L1_incipient", None),
            ("ripple", None),
            ("dropout", None),
            ("calibration_drift", None),
        ]
        for name, size in jobs:
            sc = build_scenario(name, duration_s=duration_s, seed=seed, leak_size=size)
            df, _ = simulate(sc)
            feats = add_features(df)
            feats["run_id"] = run_id
            frames.append(feats)
            run_id += 1

    data = pd.concat(frames, ignore_index=True)
    X = data[feature_columns()].to_numpy(dtype=float)
    y = data["label"].map(LABEL_TO_INT).to_numpy(dtype=int)
    groups = data["run_id"].to_numpy()
    return X, y, groups


def _load_runs(directory: str | Path) -> tuple[pd.DataFrame, dict]:
    files = sorted(Path(directory).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSV runs in {directory}")
    required = ["ts", "label", *[f"flow_{c}_lpm" for c in config.FLOW_CHANNELS], "pressure_bar"]
    frames: list[pd.DataFrame] = []
    for run_id, path in enumerate(files):
        df = pd.read_csv(path)
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="raise")
        bad = sorted(set(df["label"].astype(str)) - set(config.LABELS))
        if bad:
            raise ValueError(f"{path.name}: unknown labels {bad}")
        feats = add_features(df)
        feats["run_id"] = run_id
        feats["source"] = path.name
        frames.append(feats)
    data = pd.concat(frames, ignore_index=True)
    meta = {
        "kind": "csv",
        "directory": str(directory),
        "files": [p.name for p in files],
        "rows": int(len(data)),
    }
    return data, meta


def build_dataset_from_dir(directory: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    data, meta = _load_runs(directory)
    X = data[feature_columns()].to_numpy(dtype=float)
    y = data["label"].map(LABEL_TO_INT).to_numpy(dtype=int)
    groups = data["run_id"].to_numpy()
    return X, y, groups, meta


def _n_splits(y: np.ndarray, groups: np.ndarray) -> int:
    runs_per_class = pd.Series(groups).groupby(pd.Series(y)).nunique()
    min_runs = int(runs_per_class.min())
    if min_runs < 2:
        raise ValueError(
            "each class needs at least 2 independent runs for grouped CV; "
            f"got {dict((INT_TO_LABEL[int(k)], int(v)) for k, v in runs_per_class.items())}"
        )
    return max(2, min(5, min_runs, len(np.unique(groups))))


def _metrics(y: np.ndarray, pred: np.ndarray, groups: np.ndarray, n_splits: int) -> dict:
    report = classification_report(y, pred, output_dict=True, zero_division=0)
    binary_true = (y != 0).astype(int)
    binary_pred = (pred != 0).astype(int)
    return {
        "n_samples": int(len(y)),
        "n_groups": int(len(np.unique(groups))),
        "n_splits": int(n_splits),
        "accuracy": float(report["accuracy"]),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "binary_precision": float(precision_score(binary_true, binary_pred, zero_division=0)),
        "binary_recall": float(recall_score(binary_true, binary_pred, zero_division=0)),
        "binary_f1": float(f1_score(binary_true, binary_pred, zero_division=0)),
        "per_class": {
            INT_TO_LABEL[i]: {
                "precision": float(report[str(i)]["precision"]),
                "recall": float(report[str(i)]["recall"]),
                "f1": float(report[str(i)]["f1-score"]),
                "support": int(report[str(i)]["support"]),
            }
            for i in INT_TO_LABEL
            if str(i) in report
        },
        "confusion": confusion_matrix(y, pred).tolist(),
    }


def evaluate_model(X: np.ndarray, y: np.ndarray, groups: np.ndarray, model: RandomForestClassifier) -> dict:
    n_splits = _n_splits(y, groups)
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=0)
    pred = cross_val_predict(model, X, y, groups=groups, cv=cv, n_jobs=-1)
    return _metrics(y, pred, groups, n_splits)


def train(
    seeds: tuple[int, ...] = (1, 2, 3, 4),
    duration_s: float = 120.0,
    n_estimators: int = 300,
    out: str | Path = "models/hydropin_rf.joblib",
    seed: int = 0,
    data_dir: str | Path | None = None,
    holdout_dir: str | Path | None = None,
) -> dict:
    if data_dir is not None:
        X, y, groups, data_source = build_dataset_from_dir(data_dir)
    else:
        X, y, groups = build_dataset(seeds=seeds, duration_s=duration_s)
        data_source = {"kind": "simulator", "seeds": list(seeds), "duration_s": duration_s}

    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=12,
        min_samples_leaf=3,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=-1,
    )
    metrics = evaluate_model(X, y, groups, model)
    model.fit(X, y)
    # The bundle must list the labels in the same order as model.classes_, not
    # all four config labels: a real dataset may not contain every branch.
    classes = [INT_TO_LABEL[int(c)] for c in model.classes_]

    bundle = {
        "model": model,
        "features": feature_columns(),
        "classes": classes,
        "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "seeds": list(seeds),
        "duration_s": duration_s,
        "data_source": data_source,
    }

    if holdout_dir is not None:
        Xh, yh, gh, holdout_source = build_dataset_from_dir(holdout_dir)
        pred = model.predict(Xh)
        holdout = _metrics(yh, pred, gh, n_splits=0)
        holdout["data_source"] = holdout_source
        metrics["holdout"] = holdout
        bundle["holdout"] = holdout

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out)
    meta_path = out.with_suffix(".json")
    meta_path.write_text(
        json.dumps({k: v for k, v in bundle.items() if k != "model"}, indent=2),
        encoding="utf-8",
    )

    importances = sorted(
        zip(feature_columns(), model.feature_importances_), key=lambda t: t[1], reverse=True
    )[:12]
    metrics["top_features"] = [{"feature": f, "importance": float(v)} for f, v in importances]
    metrics["model_path"] = str(out)
    return metrics


def print_metrics(metrics: dict) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover
        print(json.dumps(metrics, indent=2))
        return
    console = Console()
    console.print(
        f"[bold]grouped CV[/] samples={metrics['n_samples']} runs={metrics['n_groups']} folds={metrics['n_splits']}"
    )
    console.print(
        f"accuracy={metrics['accuracy']:.3f} macroF1={metrics['macro_f1']:.3f} "
        f"binary P={metrics['binary_precision']:.3f} R={metrics['binary_recall']:.3f} F1={metrics['binary_f1']:.3f}"
    )
    holdout = metrics.get("holdout")
    if holdout:
        console.print(
            f"[bold]holdout[/] samples={holdout['n_samples']} runs={holdout['n_groups']} "
            f"accuracy={holdout['accuracy']:.3f} macroF1={holdout['macro_f1']:.3f} "
            f"binary P={holdout['binary_precision']:.3f} R={holdout['binary_recall']:.3f} "
            f"F1={holdout['binary_f1']:.3f}"
        )
    table = Table(title="Per-class (grouped CV)", header_style="bold magenta")
    table.add_column("class", style="cyan")
    table.add_column("precision", justify="right")
    table.add_column("recall", justify="right")
    table.add_column("f1", justify="right")
    table.add_column("support", justify="right")
    for label, m in metrics["per_class"].items():
        table.add_row(label, f"{m['precision']:.3f}", f"{m['recall']:.3f}", f"{m['f1']:.3f}", str(m["support"]))
    console.print(table)
    top = Table(title="Top features", header_style="bold magenta")
    top.add_column("feature", style="cyan")
    top.add_column("importance", justify="right")
    for row in metrics.get("top_features", []):
        top.add_row(row["feature"], f"{row['importance']:.3f}")
    console.print(top)
    console.print(f"model -> [green]{metrics['model_path']}[/]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the hydropin leak classifier")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--trees", type=int, default=300)
    parser.add_argument("--out", default="models/hydropin_rf.joblib")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--data-dir", help="train on real CSVs in this directory instead of the simulator")
    parser.add_argument("--holdout-dir", help="evaluate the fitted model on this separate directory")
    args = parser.parse_args(argv)
    metrics = train(
        seeds=tuple(args.seeds),
        duration_s=args.duration,
        n_estimators=args.trees,
        out=args.out,
        seed=args.seed,
        data_dir=args.data_dir,
        holdout_dir=args.holdout_dir,
    )
    print_metrics(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
