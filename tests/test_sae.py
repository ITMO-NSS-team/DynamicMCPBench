"""E2.4: Server Attribution Error detection + expected/random + conditional rate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dmcp.evaluator import evaluate
from dmcp.manifest import Dynamism
from dmcp.spec import (
    ComplexityProfile,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
)
from dmcp.trace import Step, StepKind, StepStatus, Trace


def _spec() -> TaskSpec:
    return TaskSpec(
        source_trace_id=uuid.uuid4(),
        prompt="search the issues",
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
        checkpoints=[
            ToolEffectCheckpoint(
                checkpoint_id="c0",
                description="search issues",
                equivalence_set=[ToolReference(server_id="github", tool_name="search_issues")],
            )
        ],
    )


def _trace(calls: list[tuple[str, str, StepStatus]]) -> Trace:
    t = Trace(goal="g")
    now = datetime.now(UTC)
    for i, (server, tool, status) in enumerate(calls):
        t.steps.append(
            Step.build(
                step_id=i,
                kind=StepKind.call_tool_agent,
                server_id=server,
                tool_name=tool,
                started_at=now,
                ended_at=now,
                status=status,
            )
        )
    return t


def test_sae_detected_on_wrong_server():
    ev = evaluate(_spec(), _trace([("gitlab", "search_issues", StepStatus.success)]))
    assert ev.had_sae is True
    assert ev.summary["sae"]["total"] == 1
    assert ev.summary["sae"]["conditional_rate"] == 1.0


def test_sae_expected_vs_random_by_tags():
    spec, tr = _spec(), _trace([("gitlab", "search_issues", StepStatus.success)])
    exp = evaluate(spec, tr, server_tags={"github": ["vcs"], "gitlab": ["vcs"]})
    assert exp.summary["sae"]["expected"] == 1
    assert exp.summary["sae"]["random"] == 0
    rand = evaluate(spec, tr, server_tags={"github": ["vcs"], "gitlab": ["chat"]})
    assert rand.summary["sae"]["random"] == 1
    assert rand.summary["sae"]["expected"] == 0


def test_no_sae_when_correct_server():
    ev = evaluate(_spec(), _trace([("github", "search_issues", StepStatus.success)]))
    assert ev.had_sae is False
    assert ev.summary["sae"]["total"] == 0
    assert ev.summary["sae"]["correct_type_calls"] == 1


def test_conditional_rate_mixed():
    ev = evaluate(
        _spec(),
        _trace(
            [
                ("github", "search_issues", StepStatus.success),
                ("gitlab", "search_issues", StepStatus.success),
            ]
        ),
    )
    assert ev.summary["sae"]["total"] == 1
    assert ev.summary["sae"]["correct_type_calls"] == 1
    assert ev.summary["sae"]["conditional_rate"] == 0.5
