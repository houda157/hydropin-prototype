"""Fit bench calibration constants from measured reference values.

Flow:
    python -m tools.calibrate flow --pulses 900 --litres 2.0 --seconds 60

Pressure (ADC counts : reference bar, repeat --point):
    python -m tools.calibrate pressure --point 1667:2.0 --point 3333:4.0 --point 5000:6.0

The pressure fit is `bar = gain * sensor_volts + offset`, where sensor_volts is
reconstructed through the 3.2 divider. Print the fitted constants and copy them
into `hydropin/config.py` and `firmware/include/config.h`.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from hydropin import config


def flow_calibration(pulses: float, litres: float, seconds: float) -> dict:
    if pulses <= 0 or litres <= 0 or seconds <= 0:
        raise ValueError("pulses, litres and seconds must be > 0")
    pulses_per_litre = pulses / litres
    measured_lpm = litres / seconds * 60.0
    raw_lpm_nominal = (pulses / seconds) / config.FLOW_PULSES_PER_LPM
    gain = measured_lpm / raw_lpm_nominal if raw_lpm_nominal else float("nan")
    return {
        "pulses_per_litre": pulses_per_litre,
        "measured_lpm": measured_lpm,
        "raw_lpm_nominal": raw_lpm_nominal,
        "gain_with_nominal_k": gain,
        "current_k": config.FLOW_K_PULSES_PER_LITRE,
        "current_gain": config.FLOW_GAIN,
    }


def pressure_calibration(adc: np.ndarray, reference_bar: np.ndarray) -> dict:
    adc = np.asarray(adc, dtype=float)
    reference_bar = np.asarray(reference_bar, dtype=float)
    if adc.size != reference_bar.size or adc.size < 2:
        raise ValueError("need at least 2 paired ADC/reference points")
    volts = adc / config.ADS_COUNTS * config.ADS_VOLTAGE_RANGE * config.PRESSURE_DIVIDER
    gain, offset = np.polyfit(volts, reference_bar, 1)
    predicted = gain * volts + offset
    residual = reference_bar - predicted
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((reference_bar - reference_bar.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return {
        "gain": float(gain),
        "offset_bar": float(offset),
        "r2": float(r2),
        "max_abs_residual_bar": float(np.max(np.abs(residual))),
        "n_points": int(adc.size),
        "current_gain": config.PRESSURE_GAIN,
        "current_offset": config.PRESSURE_OFFSET_BAR,
    }


def _pressure_points(args) -> tuple[np.ndarray, np.ndarray]:
    adc: list[float] = []
    bar: list[float] = []
    if args.csv:
        df = pd.read_csv(args.csv)
        for col in ("raw_pressure_adc", "reference_bar"):
            if col not in df.columns:
                raise ValueError(f"{args.csv} needs a {col} column")
        paired = df[["raw_pressure_adc", "reference_bar"]].apply(pd.to_numeric, errors="coerce").dropna()
        adc += paired["raw_pressure_adc"].tolist()
        bar += paired["reference_bar"].tolist()
    for point in args.point or []:
        try:
            a, b = point.split(":")
            adc.append(float(a))
            bar.append(float(b))
        except ValueError as exc:
            raise ValueError(f"bad --point {point!r}; use ADC:BAR") from exc
    return np.asarray(adc), np.asarray(bar)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit hydropin calibration constants")
    sub = parser.add_subparsers(dest="command", required=True)

    flow = sub.add_parser("flow", help="fit pulses/L and gain from a measured fill")
    flow.add_argument("--pulses", type=float, required=True)
    flow.add_argument("--litres", type=float, required=True)
    flow.add_argument("--seconds", type=float, required=True)

    pressure = sub.add_parser("pressure", help="fit gain and offset from gauge points")
    pressure.add_argument("--point", action="append", help="ADC:BAR (repeatable)")
    pressure.add_argument("--csv", help="CSV with raw_pressure_adc,reference_bar")

    args = parser.parse_args(argv)
    try:
        if args.command == "flow":
            result = flow_calibration(args.pulses, args.litres, args.seconds)
            print(f"pulses/L measured : {result['pulses_per_litre']:.3f} (current {result['current_k']:.3f})")
            print(f"measured flow     : {result['measured_lpm']:.3f} L/min")
            print(f"nominal raw flow  : {result['raw_lpm_nominal']:.3f} L/min")
            print()
            print("Option A (keep K, change gain):")
            print(f"  FLOW_K_PULSES_PER_LITRE = {result['current_k']:.1f}")
            print(f"  FLOW_GAIN               = {result['gain_with_nominal_k']:.4f}")
            print("Option B (set K from this fill, gain = 1.0):")
            print(f"  FLOW_K_PULSES_PER_LITRE = {result['pulses_per_litre']:.1f}")
            print("  FLOW_GAIN               = 1.0")
            print()
            print("Do not hide a plumbing error behind a gain; check for air and leaks first.")
        else:
            adc, bar = _pressure_points(args)
            result = pressure_calibration(adc, bar)
            print(f"points           : {result['n_points']}")
            print(f"gain (bar/V)     : {result['gain']:.4f} (current {result['current_gain']:.4f})")
            print(f"offset (bar)     : {result['offset_bar']:.4f} (current {result['current_offset']:.4f})")
            print(f"R^2              : {result['r2']:.5f}")
            print(f"max |residual|   : {result['max_abs_residual_bar']:.4f} bar")
            print()
            print("Set in both config files:")
            print(f"  PRESSURE_GAIN       = {result['gain']:.4f}")
            print(f"  PRESSURE_OFFSET_BAR = {result['offset_bar']:.4f}")
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
