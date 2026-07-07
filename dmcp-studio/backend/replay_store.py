"""Load and serve frozen REPLAY fixtures.

A fixture is the curated showcase produced by ``experiments/e3_curate.py``: the
servers view, a generated goal, a reference ``Trace``, a distilled ``TaskSpec``,
and the candidate ``Trace``s. The store parses the domain objects back into
``dmcp`` models so the adapter can run the real ``evaluate()`` on them.

Scope of v0: the single ``showcase_aapl`` fixture + the leaderboard. Out of
scope: multiple fixtures, hot-reload.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from dmcp.spec import TaskSpec
from dmcp.trace import Trace

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class Fixture:
    """One frozen showcase, with domain objects already parsed."""

    def __init__(self, raw: dict) -> None:
        self.id: str = raw["id"]
        self.servers: list[dict] = raw["servers"]
        self.goal: dict = raw["goal"]
        self.reference_trace: Trace = Trace.model_validate(raw["reference_trace"])
        self.task_spec: TaskSpec = TaskSpec.model_validate(raw["task_spec"])
        # name -> {"note", "answer_looks_right", "trace": Trace}
        self.candidates: dict[str, dict] = {}
        for c in raw["candidates"]:
            self.candidates[c["name"]] = {
                "note": c["note"],
                "answer_looks_right": bool(c["answer_looks_right"]),
                "trace": Trace.model_validate(c["trace"]),
            }


@lru_cache(maxsize=1)
def load_showcase() -> Fixture:
    path = FIXTURES_DIR / "showcase_aapl.json"
    if not path.exists():
        raise FileNotFoundError(
            f"missing fixture {path}; build it with `uv run python dmcp-studio/experiments/e3_curate.py`"
        )
    return Fixture(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_leaderboard() -> dict:
    path = FIXTURES_DIR / "leaderboard.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_advisor_replay_demo_report() -> dict:
    path = FIXTURES_DIR / "advisor_replay_demo_report.json"
    return json.loads(path.read_text(encoding="utf-8"))
