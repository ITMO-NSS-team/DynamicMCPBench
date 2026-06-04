"""E8.5 / B5: IAE (Incomplete Aggregation Error) surfaced in EvaluationResult.summary.

IAE counts failed `ValueProducedCheckpoint` evaluations — the rev.1 §5.1 "the
candidate touched the right tools but never surfaced the demanded value" case.
The denominator is the count of value_produced checkpoints in the spec, so
specs with no value checkpoints report rate=None (honest "undefined") rather
than a fake zero.
"""

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
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import Step, StepKind, StepStatus, Trace


def _value_cp(checkpoint_id: str, must_contain: str) -> ValueProducedCheckpoint:
    return ValueProducedCheckpoint(
        checkpoint_id=checkpoint_id,
        description="value checkpoint",
        predicate=ValuePredicate(contains_all=[must_contain]),
        scope="any_tool_result",
    )


def _tool_cp(checkpoint_id: str) -> ToolEffectCheckpoint:
    return ToolEffectCheckpoint(
        checkpoint_id=checkpoint_id,
        description="effect checkpoint",
        equivalence_set=[ToolReference(server_id="s", tool_name="t")],
    )


def _spec(checkpoints: list) -> TaskSpec:
    return TaskSpec(
        source_trace_id=uuid.uuid4(),
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


def _trace_with_text(text: str) -> Trace:
    """Trace whose tool result content is `text`; satisfies value predicates that include `text`."""
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id="s",
            tool_name="t",
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
            result={"content": [{"type": "text", "text": text}]},
        )
    )
    return tr


# ---------------------------------------------------------------------------
# Surface shape — summary.iae sits next to summary.sae
# ---------------------------------------------------------------------------


def test_iae_block_present_in_summary_alongside_sae():
    ev = evaluate(_spec([_tool_cp("c0")]), _trace_with_text("anything"))
    assert "iae" in ev.summary
    assert "sae" in ev.summary
    iae = ev.summary["iae"]
    assert set(iae) == {"total", "opportunities", "rate", "events"}


def test_iae_opportunities_count_value_produced_checkpoints_only():
    """The denominator is value_produced count — ToolEffect cps are E1/E4/E6/E7 territory, not E3."""
    spec = _spec([_tool_cp("t0"), _tool_cp("t1"), _value_cp("v0", "x"), _value_cp("v1", "y")])
    ev = evaluate(spec, _trace_with_text("x y"))  # both value cps satisfied
    assert ev.summary["iae"]["opportunities"] == 2
    assert ev.summary["iae"]["total"] == 0
    assert ev.summary["iae"]["rate"] == 0.0


# ---------------------------------------------------------------------------
# rate semantics — None when no opportunities; not a fake zero
# ---------------------------------------------------------------------------


def test_iae_rate_is_none_when_spec_has_no_value_produced_checkpoints():
    """A spec with only ToolEffectCheckpoints has zero IAE *opportunities*.
    Rate must be None (honest undefined) so downstream aggregators don't
    inflate the "perfect IAE" cohort with specs that can't have one."""
    ev = evaluate(_spec([_tool_cp("c0")]), _trace_with_text("anything"))
    iae = ev.summary["iae"]
    assert iae["opportunities"] == 0
    assert iae["total"] == 0
    assert iae["rate"] is None


def test_iae_rate_zero_when_all_value_produced_satisfied():
    ev = evaluate(_spec([_value_cp("v0", "found"), _value_cp("v1", "found")]), _trace_with_text("found"))
    iae = ev.summary["iae"]
    assert iae["opportunities"] == 2
    assert iae["total"] == 0
    assert iae["rate"] == 0.0


# ---------------------------------------------------------------------------
# Event detection — failed value cps are the IAE events
# ---------------------------------------------------------------------------


def test_iae_total_counts_failed_value_produced_checkpoints():
    """Two value cps, only one satisfied → IAE total = 1."""
    spec = _spec([_value_cp("v0", "hit"), _value_cp("v1", "miss")])
    ev = evaluate(spec, _trace_with_text("only-hit-here"))
    iae = ev.summary["iae"]
    assert iae["opportunities"] == 2
    assert iae["total"] == 1
    assert iae["rate"] == 0.5
    assert [e["checkpoint_id"] for e in iae["events"]] == ["v1"]


def test_iae_records_the_evaluator_reason_for_each_event():
    spec = _spec([_value_cp("v0", "absent")])
    ev = evaluate(spec, _trace_with_text("present"))
    iae = ev.summary["iae"]
    assert iae["total"] == 1
    assert "predicate did not match" in iae["events"][0]["reason"]


def test_iae_ignores_failed_tool_effect_checkpoints():
    """An E4/E6/E7 failure on a ToolEffectCheckpoint is NOT an IAE event.
    E3 (IAE) is exclusively about ValueProducedCheckpoints."""
    # ToolEffect that won't match (wrong tool), value cp that DOES match.
    spec = _spec([_tool_cp("t_unmatched"), _value_cp("v_ok", "hit")])
    # Trace has a different tool so t_unmatched fails; result text contains "hit"
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id="s",
            tool_name="other",  # not in equivalence_set
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
            result={"content": [{"type": "text", "text": "hit"}]},
        )
    )
    ev = evaluate(spec, tr)
    # ToolEffect c0 failed but it's not an IAE event:
    assert any(not cr.passed and cr.checkpoint_id == "t_unmatched" for cr in ev.checkpoint_results)
    assert ev.summary["iae"]["total"] == 0
    assert ev.summary["iae"]["events"] == []


# ---------------------------------------------------------------------------
# Cross-check against the existing E3 counter in error_taxonomy
# ---------------------------------------------------------------------------


def test_iae_total_matches_error_taxonomy_E3_count():
    """IAE total is exactly the E3 ('incomplete_aggregation') count in the
    existing error_taxonomy block — same definition, just surfaced explicitly.
    A future refactor that splits them apart would fail this anchor."""
    spec = _spec([_value_cp("v0", "x"), _value_cp("v1", "y"), _value_cp("v2", "z")])
    ev = evaluate(spec, _trace_with_text("y only"))  # v1 satisfied; v0 and v2 fail
    e3 = ev.summary["error_taxonomy"]["counts"]["E3"]
    iae_total = ev.summary["iae"]["total"]
    assert iae_total == e3 == 2
