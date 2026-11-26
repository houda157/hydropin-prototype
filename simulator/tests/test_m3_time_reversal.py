"""Every M3 oracle must pass (definitions in oracles/m3_time_reversal.py)."""

import pytest

from oracles.m3_time_reversal import checks

CHECKS = checks()


@pytest.mark.parametrize("chk", CHECKS, ids=[c.id for c in CHECKS])
def test_oracle(chk):
    assert chk.passed, (f"{chk.id} {chk.what}: expected {chk.expected}, got {chk.obtained} "
                        f"(tolerance {chk.tolerance_text()})")
