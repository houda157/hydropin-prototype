"""Structural check: the data contracts reject inconsistent inputs."""

import pytest
from pydantic import ValidationError

from hydropin_sim.contracts import MethodOutput, NetworkSpec


def _mini(**over):
    spec = dict(
        name="mini",
        nodes=[
            dict(id="S", kind="source", x=0, y=0, z=0, head=30.0),
            dict(id="J1", kind="junction", x=100, y=0, z=0),
        ],
        pipes=[dict(id="P1", start="S", end="J1", material="PE100",
                    length=100.0, d_out=0.063, e_wall=0.0058)],
    )
    spec.update(over)
    return spec


def test_valid_network():
    net = NetworkSpec(**_mini())
    assert net.pipes[0].d_int == pytest.approx(0.063 - 2 * 0.0058)


def test_unknown_node_rejected():
    spec = _mini()
    spec["pipes"][0]["end"] = "NOPE"
    with pytest.raises(ValidationError):
        NetworkSpec(**spec)


def test_source_without_head_rejected():
    spec = _mini()
    del spec["nodes"][0]["head"]
    with pytest.raises(ValidationError):
        NetworkSpec(**spec)


def test_wall_thicker_than_radius_rejected():
    spec = _mini()
    spec["pipes"][0]["e_wall"] = 0.04
    with pytest.raises(ValidationError):
        NetworkSpec(**spec)


def test_unknown_material_rejected():
    spec = _mini()
    spec["pipes"][0]["material"] = "STEEL"
    with pytest.raises(ValidationError):
        NetworkSpec(**spec)


def test_method_output_location_must_sum_to_one():
    with pytest.raises(ValueError):
        MethodOutput(method="M2", score=0.5, location={"P1": 0.3, "P2": 0.3},
                     quality=1.0, quality_ok=True)
