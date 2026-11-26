"""Every elastic transient oracle must pass (definitions in oracles/pressure_waves.py)."""

import pytest

from oracles.pressure_waves import checks

CHECKS = checks()


@pytest.mark.parametrize("chk", CHECKS, ids=[c.id for c in CHECKS])
def test_oracle(chk):
    assert chk.passed, (f"{chk.id} {chk.what}: expected {chk.expected}, got {chk.obtained} "
                        f"(tolerance {chk.tolerance_text()})")
