"""Self-consistency detectors. A spec is broken if its OWN gold/reference trace fails
one of its tool_effect checkpoints — the demanded tool is absent (``tool_absent_
checkpoints``) or was called with non-matching args (``gold_unsatisfied_tool_effects``,
the broader check that subsumes it). The cleaning filter, the merge union, and the
validate-corpus guard all rely on these.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dmcp.evaluator import gold_unsatisfied_tool_effects, tool_absent_checkpoints
from dmcp.manifest import Dynamism
from dmcp.spec import ArgPredicate, ComplexityProfile, TaskSpec, ToolEffectCheckpoint, ToolReference
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


def _gold_calling_args(server: str, tool: str, args: dict) -> Trace:
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id=server,
            tool_name=tool,
            arguments=args,
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
        )
    )
    return tr


def test_gold_unsatisfied_catches_arg_mismatch_not_just_tool_absent():
    # gold called the right tool but with args the checkpoint's predicate rejects:
    # tool_absent misses it (tool IS present), gold_unsatisfied (broader) catches it.
    gold = _gold_calling_args("s", "t", {"target": "abc123sha"})
    cp = ToolEffectCheckpoint(
        checkpoint_id="needs_head",
        description="effect checkpoint",
        equivalence_set=[ToolReference(server_id="s", tool_name="t")],
        arg_predicate=ArgPredicate(must_include={"target": "HEAD~1"}),
    )
    spec = _spec([cp], gold.trace_id)
    assert tool_absent_checkpoints(spec, gold) == []
    assert gold_unsatisfied_tool_effects(spec, gold) == ["needs_head"]


def test_gold_unsatisfied_passes_when_args_match():
    gold = _gold_calling_args("s", "t", {"target": "HEAD~1"})
    cp = ToolEffectCheckpoint(
        checkpoint_id="needs_head",
        description="effect checkpoint",
        equivalence_set=[ToolReference(server_id="s", tool_name="t")],
        arg_predicate=ArgPredicate(must_include={"target": "HEAD~1"}),
    )
    spec = _spec([cp], gold.trace_id)
    assert gold_unsatisfied_tool_effects(spec, gold) == []
