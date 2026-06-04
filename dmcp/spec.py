"""TaskSpec — the path-agnostic ground truth produced by the distiller.

A TaskSpec is what the evaluator scores agents against. It is deliberately
*not* a tool list: AGB's headline failure mode was that GT tool lists are
~50% noise. Instead, a TaskSpec carries:

  - prompt          — the fuzzy natural-language goal
  - checkpoints     — effects that must hold (each may admit equivalence
                      across tools/servers, so multiple trajectories pass)
  - minefields      — effects that must NOT happen
  - ordering        — a partial order on checkpoints (only where one effect
                      genuinely depends on a prior one)
  - complexity      — emergent trace features for stratification (Claim 3)
  - dynamism        — static / live_read / stateful_write

v0 ships two concrete checkpoint kinds (tool_effect, value_produced). A
state_condition kind is reserved for Phase 4 when per-server state probes
exist; the distiller does not emit it yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from dmcp.manifest import Dynamism

SPEC_SCHEMA_VERSION = "0.2.0"  # E8.6: added TaskSpec.provenance


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CheckpointKind(str, Enum):
    tool_effect = "tool_effect"
    value_produced = "value_produced"
    state_condition = "state_condition"


class ToolReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str
    tool_name: str


class ArgValueMatch(BaseModel):
    """How a single argument value should match. At most one matcher kind is
    used per instance (equals OR starts_with OR contains OR regex). Combining
    them is allowed and ANDs the conditions."""

    model_config = ConfigDict(extra="forbid")
    equals: Any = None
    starts_with: str | None = None
    contains: str | None = None
    regex: str | None = None


class ArgPredicate(BaseModel):
    """Constraints on a candidate tool call's arguments.

    - must_include: exact equality. {"k": v} ⇒ args[k] == v.
    - must_match:   richer per-key matchers (prefix / substring / regex).
                    Use this when the distilled value is partial — e.g. a
                    branch must START WITH "snapshot-" rather than equal it.
    Both can be set together; all conditions must hold.
    """

    model_config = ConfigDict(extra="forbid")
    must_include: dict[str, Any] = Field(default_factory=dict)
    must_match: dict[str, ArgValueMatch] = Field(default_factory=dict)


class ValuePredicate(BaseModel):
    """v0: substring / regex match on the rendered result text."""

    model_config = ConfigDict(extra="forbid")
    contains_any: list[str] | None = None
    contains_all: list[str] | None = None
    regex: str | None = None


class ToolEffectCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[CheckpointKind.tool_effect] = CheckpointKind.tool_effect
    checkpoint_id: str
    description: str
    equivalence_set: list[ToolReference]
    arg_predicate: ArgPredicate | None = None
    must_succeed: bool = True


class ValueProducedCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[CheckpointKind.value_produced] = CheckpointKind.value_produced
    checkpoint_id: str
    description: str
    predicate: ValuePredicate
    scope: Literal["any_tool_result", "final_assistant_message"] = "any_tool_result"


class StateConditionCheckpoint(BaseModel):
    """Reserved for Phase 4 — distiller v0 does not emit this kind."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal[CheckpointKind.state_condition] = CheckpointKind.state_condition
    checkpoint_id: str
    description: str
    probe: dict[str, Any] = Field(default_factory=dict)


Checkpoint = Annotated[
    ToolEffectCheckpoint | ValueProducedCheckpoint | StateConditionCheckpoint,
    Field(discriminator="kind"),
]


class Minefield(BaseModel):
    """A trajectory tripping any minefield is an immediate fail."""

    model_config = ConfigDict(extra="forbid")
    minefield_id: str
    description: str
    forbidden_tool: ToolReference | None = None
    forbidden_arg_predicate: ArgPredicate | None = None


class OrderConstraint(BaseModel):
    """Partial order — only emit where one effect genuinely depends on a
    prior one. Parallelizable effects are deliberately left unordered."""

    model_config = ConfigDict(extra="forbid")
    before_id: str
    after_id: str


class ComplexityProfile(BaseModel):
    """Emergent features of the reference trace. Stratification axes for
    Phase 3 dataset construction and RQ3 difficulty analysis."""

    model_config = ConfigDict(extra="forbid")
    trace_depth: int
    distinct_servers: int
    cross_server: bool
    runtime_branching: bool
    state_coupling: bool
    recovery_required: bool


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    schema_version: str = SPEC_SCHEMA_VERSION
    distiller_version: str = "0.1.0"
    source_trace_id: UUID
    prompt: str
    dynamism: Dynamism
    servers_used: list[str]
    complexity: ComplexityProfile
    checkpoints: list[Checkpoint]
    minefields: list[Minefield] = Field(default_factory=list)
    ordering: list[OrderConstraint] = Field(default_factory=list)
    notes: str | None = None
    # E8.6: cross-family generation panel — records explorer / distiller /
    # validator models + families per spec so RQ1/G0 can stratify by author.
    # Free-form dict (no inner Pydantic model) so the runner can extend it
    # (shard ids, retry counts, validator verdicts) without further bumps.
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)

    def to_jsonl(self) -> str:
        return self.model_dump_json(exclude_none=False)
