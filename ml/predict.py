"""Run a trained model over a telemetry CSV and write per-sample predictions.

    python -m ml.predict --model models/hydropin_rf.joblib --csv data/raw/leak_L1_seed7.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from hydropin import config

from .features import add_features


def predict_frame(bundle: dict, df: pd.DataFrame) -> pd.DataFrame:
    feats = add_features(df)
    X = feats[bundle["features"]].to_numpy(dtype=float)
    proba = bundle["model"].predict_proba(X)
    idx = proba.argmax(axis=1)
    classes = list(bundle["classes"])
    out = df.copy()
    out["pred_label"] = [classes[i] for i in idx]
    out["pred_leak"] = out["pred_label"] != "none"
    out["pred_confidence"] = proba.max(axis=1)
    out["pred_none_prob"] = proba[:, classes.index("none")] if "none" in classes else 0.0
    return out


def summarise(out: pd.DataFrame) -> dict:
    leak = out["pred_leak"].to_numpy(dtype=bool)
    segments: list[dict] = []
    start = None
    for i, a in enumerate(leak):
        if a and start is None:
            start = i
        elif not a and start is not None:
            segments.append({"start": int(start), "end": int(i - 1)})
            start = None
    if start is not None:
        segments.append({"start": int(start), "end": int(len(out) - 1)})
    preds = out.loc[leak, "pred_label"]
    return {
        "samples": int(len(out)),
        "leak_fraction": float(leak.mean()),
        "segments": len(segments),
        "dominant_branch": str(preds.mode().iloc[0]) if len(preds) else "none",
        "mean_confidence": float(out["pred_confidence"].mean()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predict leaks with a trained model")
    parser.add_argument("--model", default="models/hydropin_rf.joblib")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    bundle = joblib.load(args.model)
    df = pd.read_csv(args.csv, parse_dates=["ts"])
    out = predict_frame(bundle, df)
    summary = summarise(out)
    print(summary)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
