"""Goals seed file — declarative list of exploration goals for batch generation.

A goals file is just a JSON list of GoalEntry records. Each entry declares a
natural-language goal, the server_ids the explorer should connect, an
optional persona, and free-form tags. The explorer pulls each goal,
runs forward exploration constrained to that goal's server pool, and the
batch driver distills the resulting trace into a TaskSpec.

This is the v0 substitute for an automated persona/goal library — the rev. 3
plan's Phase 2A talks about generating personas + goals from each server
cluster's tool surface. Until that exists, a human-written seed file lets us
iterate on the rest of the pipeline at dataset scale.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

GOALS_VERSION = "0.1.0"


class GoalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    goal: str
    servers: list[str] = Field(default_factory=list)
    persona: str | None = None
    tags: list[str] = Field(default_factory=list)
    budget: int | None = None

    @model_validator(mode="after")
    def _check(self) -> GoalEntry:
        if not self.servers:
            raise ValueError(f"{self.goal_id}: must list at least one server_id")
        return self


class Goals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals_version: str = GOALS_VERSION
    entries: list[GoalEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> Goals:
        seen: set[str] = set()
        for e in self.entries:
            if e.goal_id in seen:
                raise ValueError(f"duplicate goal_id: {e.goal_id}")
            seen.add(e.goal_id)
        return self

    @classmethod
    def load(cls, path: Path) -> Goals:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
