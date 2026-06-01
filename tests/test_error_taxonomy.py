"""E2.5: error-taxonomy classification (E1-E7) over synthetic failed evaluations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dmcp.evaluator import ERROR_WEIGHTS, evaluate
from dmcp.manifest import Dynamism
from dmcp.spec import (
    ArgPredicate,
    Checkpoint,
    ComplexityProfile,
    OrderConstraint,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import Step, StepKind, StepStatus, Trace


def _spec(checkpoints: list[Checkpoint], ordering: list[OrderConstraint] | None = None) -> TaskSpec:
    return TaskSpec(
        source_trace_id=uuid.uuid4(),
        prompt="p",
        dynamism=Dynamism.live_read,
        servers_used=["github"],
        complexity=ComplexityProfile(
            trace_depth=1,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=checkpoints,
        ordering=ordering or [],
    )


def _te(cid: str, server: str, tool: str, arg_predicate: ArgPredicate | None = None) -> ToolEffectCheckpoint:
    return ToolEffectCheckpoint(
        checkpoint_id=cid,
        description=cid,
        equivalence_set=[ToolReference(server_id=server, tool_name=tool)],
        arg_predicate=arg_predicate,
    )


def _trace(calls):
    t = Trace(goal="g")
    now = datetime.now(UTC)
    for i, c in enumerate(calls):
        server, tool, status = c[0], c[1], c[2]
        args = c[3] if len(c) > 3 else None
        t.steps.append(
            Step.build(
                step_id=i,
                kind=StepKind.call_tool_agent,
                server_id=server,
                tool_name=tool,
                arguments=args,
                started_at=now,
                ended_at=now,
                status=status,
            )
        )
    return t


def _counts(ev):
    return ev.summary["error_taxonomy"]["counts"]


def test_e6_tool_blindness():
    ev = evaluate(_spec([_te("c0", "github", "search_issues")]), _trace([]))
    c = _counts(ev)
    assert c["E6"] == 1 and c["E4"] == 0 and c["E1"] == 0


def test_e4_server_confusion():
    ev = evaluate(
        _spec([_te("c0", "github", "search_issues")]),
        _trace([("gitlab", "search_issues", StepStatus.success)]),
    )
    assert _counts(ev)["E4"] == 1


def test_e7_argument_hallucination():
    spec = _spec([_te("c0", "github", "search_issues", ArgPredicate(must_include={"q": "bug"}))])
    ev = evaluate(spec, _trace([("github", "search_issues", StepStatus.success, {"q": "other"})]))
    c = _counts(ev)
    assert c["E7"] == 1 and c["E6"] == 0


def test_e3_incomplete_aggregation():
    cp = ValueProducedCheckpoint(
        checkpoint_id="v0", description="needs foo", predicate=ValuePredicate(contains_any=["foo"])
    )
    ev = evaluate(_spec([cp]), _trace([]))
    assert _counts(ev)["E3"] == 1


def test_e1_missing_prerequisite():
    spec = _spec(
        [_te("c0", "github", "prep"), _te("c1", "github", "main")],
        ordering=[OrderConstraint(before_id="c0", after_id="c1")],
    )
    # c0 (the prerequisite) is never called → E1
    ev = evaluate(spec, _trace([("github", "main", StepStatus.success)]))
    assert _counts(ev)["E1"] >= 1


def test_e5_order_violation_with_weighted_score():
    spec = _spec(
        [_te("c0", "github", "a"), _te("c1", "github", "b")],
        ordering=[OrderConstraint(before_id="c0", after_id="c1")],
    )
    # both satisfied but out of order (b called before a)
    ev = evaluate(
        spec,
        _trace([("github", "b", StepStatus.success), ("github", "a", StepStatus.success)]),
    )
    c = _counts(ev)
    assert c["E5"] == 1 and c["E1"] == 0 and c["E6"] == 0
    # weighted score reflects the E5 weight (0.4)
    assert abs(ev.summary["error_taxonomy"]["weighted_score"] - ERROR_WEIGHTS["E5"]) < 1e-9
