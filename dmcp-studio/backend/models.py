"""API response models for DMCP Studio.

View-only Pydantic models for the HTTP surface. The heavy domain objects
(``TaskSpec``, ``Trace``, ``EvaluationResult``) are reused verbatim from the
``dmcp`` pipeline (INTEGRATION_NOTES §1) — we do not redefine them. These
models cover only what the UI needs that the pipeline doesn't already provide.

Scope of v0: REPLAY responses. LIVE adds no new shapes (same models).
Out of scope: auth, pagination, persistence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Mode = Literal["live", "replay"]


class ServerCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str
    dynamism: str  # static | live_read | stateful_write
    sandbox: bool
    description: str
    tools: list[str]


class GoalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str
    persona: str | None = None


class CandidateCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    note: str


class CheckpointVerdict(BaseModel):
    """One checkpoint's result, flattened for the ledger UI."""

    model_config = ConfigDict(extra="forbid")
    n: int
    checkpoint_id: str
    kind: str
    met: bool
    reason: str


class ScoreDone(BaseModel):
    """Terminal event for /api/score — carries BOTH verdicts every time.

    ``effect_pass`` is the pipeline's deterministic verdict. ``answer_pass`` is a
    studio-side demo foil (INTEGRATION_NOTES §6) — never a benchmark number.
    """

    model_config = ConfigDict(extra="forbid")
    effect_pass: bool
    answer_pass: bool
    final_answer: str
    met_count: int
    required: int
    checkpoints: list[CheckpointVerdict]


class LeaderboardRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    group: str
    pass3: float


class Leaderboard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placeholder: bool = False
    note: str | None = None
    rows: list[LeaderboardRow]
