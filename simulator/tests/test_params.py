"""Structural check: params.yaml is complete, consistent and traceable to the math note."""

import re
from pathlib import Path

import pytest
import yaml

from hydropin_sim.config import (DERIVED, PER_ELEMENT, MissingParameterError,
                             Param, load_params)

ROOT = Path(__file__).resolve().parents[1]
MATH_NOTE = ROOT / "docs" / "math.md"


@pytest.fixture(scope="module")
def P():
    return load_params()


def test_loads(P):
    assert P.water.G.v == pytest.approx(9.81)


def test_every_param_documented(P):
    for name, p in P.all_params().items():
        assert p.unit, f"{name} has no unit"
        assert p.source, f"{name} has no source"
        assert p.meaning, f"{name} has no meaning"


def test_every_material_has_the_same_parameters(P):
    keys = [set(g.items()) for g in P.materials.values()]
    assert all(k == keys[0] for k in keys)


def test_math_note_names_are_all_covered(P):
    """Every code name in section 0 of the math note exists in params.yaml,
    or is declared as derived or per-element in hydropin_sim.config."""
    if not MATH_NOTE.exists():
        pytest.skip("docs/math.md not found")
    text = MATH_NOTE.read_text(encoding="utf-8")
    section0 = text.split("\n## 0. ")[1].split("\n## 1. ")[0]
    names = set(re.findall(r"`([A-Z][A-Z0-9_]*)`", section0))
    assert len(names) > 40, "could not parse the math note"
    covered = P.code_names() | set(DERIVED) | set(PER_ELEMENT)
    missing = sorted(names - covered)
    assert not missing, f"math note names without a home: {missing}"


def test_no_param_without_math_note_name(P):
    """The reverse: params.yaml does not invent constants the math note doesn't define
    (T_WATER is the only documented addition)."""
    if not MATH_NOTE.exists():
        pytest.skip("docs/math.md not found")
    text = MATH_NOTE.read_text(encoding="utf-8")
    extra = {n for n in P.code_names() if f"`{n}`" not in text}
    assert extra <= {"T_WATER"}, f"undocumented parameters: {extra}"


def test_out_of_range_value_is_rejected():
    with pytest.raises(ValueError):
        Param(value=5.0, unit="m", symbol="x", meaning="m", source="s", range=(0, 1))


def test_missing_value_fails_loudly(P):
    with pytest.raises(MissingParameterError):
        _ = P.energy.C_ELEC.v


def test_tabulated_interpolation(P):
    # 25 degC is halfway between the 20 and 30 degC table points
    assert P.nu_w(25.0) == pytest.approx((1.004e-6 + 0.801e-6) / 2)
    with pytest.raises(ValueError):
        P.nu_w(60.0)  # outside the table: no silent extrapolation


def test_broken_file_is_rejected(tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "params.yaml").read_text(encoding="utf-8"))
    raw["decision"]["TAU1"]["value"] = 0.9   # TAU1 > TAU2
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_params(bad)
