"""tool_absent_checkpoints: a spec whose tool_effect checkpoint demands a tool its
own gold trace never called is self-inconsistent — unpassable by construction (no
candidate replaying that world can call the missing tool). The cleaning filter and
the validate-corpus guard both rely on this.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dmcp.evaluator import tool_absent_checkpoints
from dmcp.manifest import Dynamism
from dmcp.spec import ComplexityProfile, TaskSpec, ToolEffectCheckpoint, ToolReference
from dmcp.trace import Step, StepKind, StepStatus, Trace


def _tool_cp(cp_id: str, server: str, tool: str) -> ToolEffectCheckpoint:
    return ToolEffectCheckpoint(
        checkpoint_id=cp_id,
        description="effect checkpoint",
        equivalence_set=[ToolReference(server_id=server, tool_name=tool)],
    )


def _spec(checkpoints: list, source_trace_id: uuid.UUID) -> TaskSpec:
    return TaskSpec(
        source_trace_id=source_trace_id,
        prompt="x",
        dynamism=Dynamism.live_read,
        servers_used=["s"],
        complexity=ComplexityProfile(
            trace_depth=1,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=checkpoints,
    )


def _gold_calling(server: str, tool: str) -> Trace:
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id=server,
            tool_name=tool,
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
        )
    )
    return tr


def test_present_tool_is_not_flagged():
    gold = _gold_calling("s", "t")
    spec = _spec([_tool_cp("present", "s", "t")], gold.trace_id)
    assert tool_absent_checkpoints(spec, gold) == []


def test_absent_tool_is_flagged():
    gold = _gold_calling("s", "t")
    spec = _spec([_tool_cp("needs_missing", "s", "missing")], gold.trace_id)
    assert tool_absent_checkpoints(spec, gold) == ["needs_missing"]


def test_mixed_returns_only_absent():
    gold = _gold_calling("s", "t")
    spec = _spec([_tool_cp("present", "s", "t"), _tool_cp("absent", "other", "x")], gold.trace_id)
    assert tool_absent_checkpoints(spec, gold) == ["absent"]


def test_wrong_server_same_tool_is_flagged():
    # same tool name on a different server is NOT a match (the SAE primitive)
    gold = _gold_calling("server_a", "lookup")
    spec = _spec([_tool_cp("needs_b", "server_b", "lookup")], gold.trace_id)
    assert tool_absent_checkpoints(spec, gold) == ["needs_b"]
