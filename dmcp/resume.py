"""JSONL resume helpers — let long-running runs skip already-completed work.

The autonomous experiment harnesses (`dmcp eval`, `dmcp generate`,
`scripts/cost_calibration.py`, `scripts/build_corpus.py`) write their results
JSONL-style, one row per processed unit (task / goal). Resumability is the
ability to inspect that file on restart and skip every unit already present.

Why a tiny helper instead of inline `set(json.loads(line)['key'])`: the
read-skip pattern must be robust to (a) partial trailing lines from a
hard-killed process, (b) missing or stale files, (c) the user mid-edit on a
JSONL during a kill/relaunch cycle. The helper swallows malformed lines and
warns, instead of crashing the resumer on the very last byte of a previous
run.

Scope of v0: scan-once at startup, return an in-memory set. No incremental
re-reads. No locking — the resume contract assumes only one process appends
at a time to any given output file.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _iter_rows(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for n, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Last line of a killed process can be partial JSON; warn but
                # continue so resume doesn't abort on a stale tail.
                sys.stderr.write(f"[resume] {path}: skipping malformed line {n}\n")


def _pluck(d: dict, *keys: str) -> Any:
    """Try each key in order — fields may live at top level or under nested
    dicts (seed_metadata, provenance, summary)."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def seen_task_ids(path: Path) -> set[str]:
    """Task ids already evaluated in `path` (an EvaluationResult JSONL).

    Used by `dmcp eval --resume`. Empty set when `path` doesn't exist yet —
    fresh runs cleanly degrade to "skip nothing".
    """
    out: set[str] = set()
    for row in _iter_rows(path):
        tid = _pluck(row, "task_id")
        if tid is not None:
            out.add(str(tid))
    return out


def seen_goal_ids(path: Path) -> set[str]:
    """Goal ids already converted to specs in `path` (a TaskSpec JSONL).

    The goal id is the durable identifier — task ids are minted fresh per
    distill call. We pluck from `provenance.goal_id` first (the E8.6
    contract) and fall back to `seed_metadata.goal_id` for traces.
    """
    out: set[str] = set()
    for row in _iter_rows(path):
        prov = row.get("provenance") or {}
        gid = prov.get("goal_id") or _pluck(row.get("seed_metadata") or {}, "goal_id")
        if gid is not None:
            out.add(str(gid))
    return out


def file_row_count(path: Path) -> int:
    """Number of non-empty, parseable JSONL rows in `path`. For cell-level
    skip in the calibration / corpus runners ("if file has ≥ N rows, skip
    the whole cell")."""
    return sum(1 for _ in _iter_rows(path))
