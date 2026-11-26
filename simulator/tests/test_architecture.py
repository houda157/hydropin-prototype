"""Structural check: the code respects the layered architecture.

A module may import hydropin_sim modules from a LOWER layer only. This keeps the
physics independent from the solvers, the solvers independent from the
detection methods, and so on.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "hydropin_sim"

LAYER = {
    "config": 0, "contracts": 0,
    "physics": 1,
    "network": 2,
    "steady": 3,
    "transient": 4,
    "sensors": 5,
    "methods": 6,
    "fusion": 7, "placement": 7,
    "viz": 8,
}


def _top_package(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0].removesuffix(".py")


def _hydropin_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("hydropin."):
                    found.add(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0 and node.module.startswith("hydropin."):
                found.add(node.module.split(".")[1])
            elif node.level == 0 and node.module == "hydropin_sim":
                found.update(a.name for a in node.names)
    return found


MODULES = [p for p in SRC.rglob("*.py") if p.name != "__init__.py" or p.parent != SRC]


def test_every_package_has_a_layer():
    packages = {_top_package(p) for p in MODULES}
    assert packages <= set(LAYER), f"unknown packages: {packages - set(LAYER)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(SRC)))
def test_imports_only_from_lower_layers(path):
    me = _top_package(path)
    for dep in _hydropin_imports(path):
        if dep == me:
            continue
        assert dep in LAYER, f"{path.name} imports unknown package hydropin_sim.{dep}"
        assert LAYER[dep] < LAYER[me], (
            f"{path.relative_to(SRC)} (layer {LAYER[me]}) imports "
            f"hydropin_sim.{dep} (layer {LAYER[dep]}): only lower layers are allowed"
        )
