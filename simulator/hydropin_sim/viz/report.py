"""Writes a validation report (GitHub Markdown) as README.md of a results folder."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Sequence

from hydropin_sim.config import PACKAGE_ROOT


def _check_number(cid: str) -> str:
    """Oracle ids are '<group>.<n>' in the code; reports show only <n>."""
    return cid.split(".", 1)[1] if "." in cid else cid


def write_report(path: Path, step: int, title: str, summary: str,
                 built: Sequence[tuple[str, str, str]],
                 checks: Iterable, figures: Sequence[tuple[str, str]],
                 assumptions: Sequence[str], decisions: Sequence[str],
                 findings: Sequence[str] = ()) -> Path:
    """built: (module/function, what it does, math section)
    figures: (png file name, caption)
    step: kept for compatibility, not shown.
    """
    path = Path(path)
    root = os.path.relpath(PACKAGE_ROOT, path.parent).replace(os.sep, "/")
    checks = list(checks)
    n_ok = sum(c.passed for c in checks)
    status = "✅ all checks pass" if n_ok == len(checks) else f"❌ {len(checks) - n_ok} check(s) fail"
    lines = [
        f"# {title}",
        "",
        f"> **{status} ({n_ok}/{len(checks)})**  ",
        f"> {summary}",
        "",
        f"Back to the [overview]({root}/README.md) · Equations: [math]({root}/docs/math.md) · "
        f"Design: [architecture]({root}/docs/architecture.md)",
        "",
        "## 1. What was built",
        "",
        "| Code | What it does | Math |",
        "|---|---|---|",
    ]
    lines += [f"| `{a}` | {b} | {c} |" for a, b, c in built]
    lines += ["", "## 2. Checks", "",
              "Each check compares the code with an analytical solution, a reference software or a physical law.", "",
              "| # | Check | Expected | Obtained | Tolerance | Ref | Result |",
              "|---|---|---|---|---|---|---|"]
    for c in checks:
        res = "✅" if c.passed else "❌"
        unit = f" {c.unit}" if c.unit and c.kind != "bool" else ""
        lines.append(f"| {_check_number(c.id)} | {c.what} | {c.fmt(c.expected)}{unit} | {c.fmt(c.obtained)}{unit} "
                     f"| {c.tolerance_text()} | {c.ref} | {res} |")
    lines += ["", "## 3. Figures", ""]
    for i, (png, cap) in enumerate(figures, 1):
        lines += [f"**Figure {i}.** {cap}", "", f"![Figure {i}]({png})", ""]
    n = 4
    if findings:
        lines += [f"## {n}. What the figures tell us", ""]
        lines += [f"- {f}" for f in findings]
        lines.append("")
        n += 1
    lines += [f"## {n}. Assumptions", ""]
    lines += [f"- {a}" for a in assumptions] or ["- none"]
    lines.append("")
    open_points = [d for d in decisions if not d.lower().startswith("validate")]
    if open_points:
        lines += [f"## {n + 1}. Open points", ""]
        lines += [f"- {d}" for d in open_points]
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
