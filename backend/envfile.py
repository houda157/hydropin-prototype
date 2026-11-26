"""Load KEY=VALUE pairs from the repo's .env into os.environ (no extra dependency).

Variables already set in the shell win. Not loaded under pytest, so a developer's .env
(Telegram token, HYDROPIN_NOTIFY=1, ...) never leaks into the tests. Copy .env.example to .env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def parse(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key:
            out[key] = val
    return out


def load_env(path: Path = ENV_PATH, force: bool = False) -> dict[str, str]:
    """Set the variables from `path` that are not set yet. Returns what was set."""
    if not force and "pytest" in sys.modules:
        return {}
    if not path.exists():
        return {}
    done = {}
    for k, v in parse(path.read_text(encoding="utf-8")).items():
        if v and k not in os.environ:
            os.environ[k] = v
            done[k] = v
    return done
