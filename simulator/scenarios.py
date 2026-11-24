"""Bench scenarios: physically-motivated, reproducible, and deliberately harsh.

The point of the harsh scenarios (ripple, dropout, incipient leaks) is to stop
the detector and the ML model from looking better than they really are.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

LEAK_SIZES_LPM = {"small": 0.15, "medium": 0.35, "large": 0.70}


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str = "none"
    duration_s: float = 120.0
    leak_branch: str | None = None
    leak_lpm: float = 0.0
    leak_start_s: float = 30.0
    leak_ramp_s: float = 0.0
    ripple_amplitude: float = 0.0
    dropout_prob: float = 0.0
    noise_scale: float = 1.0
    flow_gain_error: float = 0.0
    pressure_gain_error: float = 0.0
    seed: int = 42
    notes: str = ""


SCENARIOS: dict[str, Scenario] = {
    "baseline": Scenario(
        name="baseline",
        notes="Healthy bench, small pump ripple and sensor noise only.",
    ),
    "leak_L1": Scenario(
        name="leak_L1",
        label="leak_L1",
        leak_branch="l1",
        leak_lpm=LEAK_SIZES_LPM["medium"],
        notes="Abrupt medium leak on branch L1.",
    ),
    "leak_L2": Scenario(
        name="leak_L2",
        label="leak_L2",
        leak_branch="l2",
        leak_lpm=LEAK_SIZES_LPM["medium"],
        notes="Abrupt medium leak on branch L2.",
    ),
    "leak_L3": Scenario(
        name="leak_L3",
        label="leak_L3",
        leak_branch="l3",
        leak_lpm=LEAK_SIZES_LPM["medium"],
        notes="Abrupt medium leak on branch L3.",
    ),
    "leak_L1_incipient": Scenario(
        name="leak_L1_incipient",
        label="leak_L1",
        leak_branch="l1",
        leak_lpm=0.50,
        leak_start_s=20.0,
        leak_ramp_s=60.0,
        notes="Leak that grows over 60 s: hard to catch early without false alarms.",
    ),
    "ripple": Scenario(
        name="ripple",
        label="none",
        ripple_amplitude=0.06,
        noise_scale=1.5,
        notes="Pump ripple only; every alarm here is a false positive.",
    ),
    "dropout": Scenario(
        name="dropout",
        label="none",
        dropout_prob=0.08,
        notes="8% packet/sample loss; tests missing-data handling.",
    ),
    "calibration_drift": Scenario(
        name="calibration_drift",
        label="none",
        flow_gain_error=0.10,
        pressure_gain_error=-0.10,
        notes="Gains are 10% off; a brittle threshold detector should struggle.",
    ),
}


def list_scenarios() -> list[str]:
    return list(SCENARIOS)


def build_scenario(
    name: str,
    *,
    leak_size: str | None = None,
    duration_s: float | None = None,
    seed: int | None = None,
) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; choose from {list_scenarios()}")
    sc = SCENARIOS[name]
    if leak_size is not None:
        if leak_size not in LEAK_SIZES_LPM:
            raise KeyError(f"unknown leak size {leak_size!r}; choose from {list(LEAK_SIZES_LPM)}")
        sc = replace(sc, leak_lpm=LEAK_SIZES_LPM[leak_size])
    if duration_s is not None:
        sc = replace(sc, duration_s=float(duration_s))
    if seed is not None:
        sc = replace(sc, seed=int(seed))
    return sc
