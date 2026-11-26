"""Oracle checks shared by pytest and by the step reports.

Each step defines a function ``checks() -> list[Check]``. pytest asserts that
every check passes; the step script writes the same checks into the report
table. One definition, two uses: the report can never disagree with the tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

Value = Union[float, int, bool, str]


@dataclass
class Check:
    id: str
    what: str                  # one-line description, plain language
    expected: Value
    obtained: Value
    tol: float = 0.0           # relative (kind="rel") or absolute (kind="abs") tolerance
    kind: Literal["rel", "abs", "le", "ge", "bool"] = "rel"
    ref: str = ""              # math note section or reference
    unit: str = ""

    @property
    def error(self) -> float:
        if self.kind == "rel":
            return abs(self.obtained - self.expected) / max(abs(self.expected), 1e-300)
        if self.kind == "abs":
            return abs(self.obtained - self.expected)
        return float("nan")

    @property
    def passed(self) -> bool:
        if self.kind == "bool":
            return bool(self.obtained) == bool(self.expected)
        if self.kind == "le":
            return self.obtained <= self.expected
        if self.kind == "ge":
            return self.obtained >= self.expected
        return self.error <= self.tol

    def fmt(self, v: Value) -> str:
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, (int, float)):
            if v == 0:
                return "0"
            if 1e-3 <= abs(v) < 1e5:
                return f"{v:.5g}"
            return f"{v:.4e}"
        return str(v)

    def tolerance_text(self) -> str:
        if self.kind == "rel":
            return f"± {self.tol * 100:.3g} %"
        if self.kind == "abs":
            return f"± {self.fmt(self.tol)} {self.unit}".strip()
        if self.kind == "le":
            return "≤ expected"
        if self.kind == "ge":
            return "≥ expected"
        return "–"
