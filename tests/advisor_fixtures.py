"""Loader for the Benchmark Advisor golden fixtures (BA1.3 / T08).

A small test helper (not a runtime package module) so every advisor test —
validator (T02), planner (T03), API (T05), integration (T09) — loads the same
shared request→outcome oracles instead of inventing local wire shapes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ADVISOR_PKG = _REPO_ROOT / "benchmark_advisor"
FIXTURES_DIR = _ADVISOR_PKG / "fixtures"
GUIDE_PATH = _ADVISOR_PKG / "data" / "STATISTICAL_GUIDE.md"

_GUIDE_ID_RE = re.compile(r"`(G\d+\.[A-Za-z0-9_.]+)`")


def load_all() -> list[dict[str, Any]]:
    """Return every fixture dict, sorted by id."""
    out = [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]
    return sorted(out, key=lambda d: d["id"])


def load(fixture_id: str) -> dict[str, Any]:
    """Return a single fixture dict by id."""
    path = FIXTURES_DIR / f"{fixture_id}.json"
    return json.loads(path.read_text())


def guide_rule_ids() -> set[str]:
    """All `statistical_guide.v1` rule ids declared in STATISTICAL_GUIDE.md."""
    return set(_GUIDE_ID_RE.findall(GUIDE_PATH.read_text()))


def iter_guide_refs(obj: Any) -> list[str]:
    """Collect every guide ``rule_id`` appearing anywhere inside a fixture."""
    found: list[str] = []
    if isinstance(obj, dict):
        if "rule_id" in obj and isinstance(obj["rule_id"], str):
            found.append(obj["rule_id"])
        for v in obj.values():
            found.extend(iter_guide_refs(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(iter_guide_refs(v))
    return found
