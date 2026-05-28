"""Tier-1 deterministic trace evaluator (Phase 4 of the rev. 3 plan).

Given a TaskSpec and a candidate Trace, decide whether the trace satisfies
the spec. This tier is fully deterministic — no LLM judgment — and is
intended to catch the bulk of pass/fail decisions cheaply. Tier-2 (LLM
effect-equivalence judgment) and Tier-3 (capability profile rollups) sit on
top of these results in later iterations.

Critical philosophy: we never score the final answer string for correctness.
A `value_produced` checkpoint can match text — but the strings are *evidence*
the LLM-distilled spec asks for, not a free-form "is the answer right" check.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dmcp.spec import (
    ArgPredicate,
    Checkpoint,
    Minefield,
    OrderConstraint,
    StateConditionCheckpoint,
    TaskSpec,
    ToolEffectCheckpoint,
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import Step, StepKind, StepStatus, Trace

EVALUATOR_VERSION = "0.1.0"


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class CheckpointResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str
    kind: str
    passed: bool
    reason: str
    matched_step_id: int | None = None
    # tier=1 deterministic, tier=2 LLM-judged effect-equivalence.
    tier: int = 1


class MinefieldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minefield_id: str
    hit: bool
    reason: str
    tripped_step_id: int | None = None


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "0.1.0"
    evaluator_version: str = EVALUATOR_VERSION
    task_id: UUID
    candidate_trace_id: UUID
    candidate_model: str | None = None
    evaluation_mode: str | None = None  # "live" | "replay"
    passed: bool
    checkpoint_results: list[CheckpointResult]
    minefield_results: list[MinefieldResult]
    ordering_ok: bool
    ordering_failures: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_utcnow)

    def to_jsonl(self) -> str:
        return self.model_dump_json(exclude_none=False)


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------


def _arg_predicate_matches(predicate: ArgPredicate | None, args: dict[str, Any] | None) -> bool:
    if predicate is None or (not predicate.must_include and not predicate.must_match):
        return True
    if args is None:
        return False
    for key, expected in predicate.must_include.items():
        if key not in args or args[key] != expected:
            return False
    for key, matcher in predicate.must_match.items():
        if key not in args:
            return False
        value = args[key]
        if matcher.equals is not None and value != matcher.equals:
            return False
        if matcher.starts_with is not None and (
            not isinstance(value, str) or not value.startswith(matcher.starts_with)
        ):
            return False
        if matcher.contains is not None and (
            not isinstance(value, str) or matcher.contains not in value
        ):
            return False
        if matcher.regex is not None and (
            not isinstance(value, str) or not re.search(matcher.regex, value)
        ):
            return False
    return True


def _value_predicate_matches(predicate: ValuePredicate, text: str) -> bool:
    if not (predicate.contains_all or predicate.contains_any or predicate.regex):
        return False
    if predicate.contains_all and not all(n in text for n in predicate.contains_all):
        return False
    if predicate.contains_any and not any(n in text for n in predicate.contains_any):
        return False
    if predicate.regex and not re.search(predicate.regex, text):
        return False
    return True


def _render_step_result(step: Step) -> str:
    if step.result is None:
        return ""
    parts: list[str] = []
    for c in step.result.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    if parts:
        return "\n".join(parts)
    return json.dumps(step.result, default=str)


def _final_assistant_message(trace: Trace) -> str:
    exp = trace.seed_metadata.get("exploration") or {}
    return exp.get("final_message") or ""


# ---------------------------------------------------------------------------
# Per-checkpoint evaluation
# ---------------------------------------------------------------------------


def _eval_tool_effect(
    cp: ToolEffectCheckpoint, agent_calls: list[Step]
) -> CheckpointResult:
    eq = {(r.server_id, r.tool_name) for r in cp.equivalence_set}
    for step in agent_calls:
        if step.tool_name is None:
            continue
        if (step.server_id, step.tool_name) not in eq:
            continue
        if cp.must_succeed and step.status is not StepStatus.success:
            continue
        if not _arg_predicate_matches(cp.arg_predicate, step.arguments):
            continue
        return CheckpointResult(
            checkpoint_id=cp.checkpoint_id,
            kind=cp.kind.value,
            passed=True,
            reason=(
                f"matched step #{step.step_id} {step.server_id}.{step.tool_name}"
            ),
            matched_step_id=step.step_id,
        )
    eq_render = ", ".join(f"{s}.{t}" for s, t in eq)
    return CheckpointResult(
        checkpoint_id=cp.checkpoint_id,
        kind=cp.kind.value,
        passed=False,
        reason=f"no successful call matched equivalence_set={{{eq_render}}} with required args",
    )


def _eval_value_produced(
    cp: ValueProducedCheckpoint, agent_calls: list[Step], trace: Trace
) -> CheckpointResult:
    if cp.scope == "final_assistant_message":
        text = _final_assistant_message(trace)
        if not text:
            return CheckpointResult(
                checkpoint_id=cp.checkpoint_id,
                kind=cp.kind.value,
                passed=False,
                reason="no final_assistant_message stashed in trace.seed_metadata.exploration",
            )
        if _value_predicate_matches(cp.predicate, text):
            return CheckpointResult(
                checkpoint_id=cp.checkpoint_id,
                kind=cp.kind.value,
                passed=True,
                reason="predicate matched final_assistant_message",
            )
        return CheckpointResult(
            checkpoint_id=cp.checkpoint_id,
            kind=cp.kind.value,
            passed=False,
            reason="predicate did not match final_assistant_message",
        )

    # any_tool_result
    for step in agent_calls:
        if step.status is not StepStatus.success:
            continue
        text = _render_step_result(step)
        if not text:
            continue
        if _value_predicate_matches(cp.predicate, text):
            return CheckpointResult(
                checkpoint_id=cp.checkpoint_id,
                kind=cp.kind.value,
                passed=True,
                reason=f"predicate matched step #{step.step_id} result",
                matched_step_id=step.step_id,
            )
    return CheckpointResult(
        checkpoint_id=cp.checkpoint_id,
        kind=cp.kind.value,
        passed=False,
        reason="predicate did not match any tool result",
    )


def _eval_state_condition(cp: StateConditionCheckpoint) -> CheckpointResult:
    return CheckpointResult(
        checkpoint_id=cp.checkpoint_id,
        kind=cp.kind.value,
        passed=False,
        reason="state_condition checkpoints are not implemented in tier-1 evaluator (Phase 4 work)",
    )


def _eval_checkpoint(cp: Checkpoint, agent_calls: list[Step], trace: Trace) -> CheckpointResult:
    if isinstance(cp, ToolEffectCheckpoint):
        return _eval_tool_effect(cp, agent_calls)
    if isinstance(cp, ValueProducedCheckpoint):
        return _eval_value_produced(cp, agent_calls, trace)
    if isinstance(cp, StateConditionCheckpoint):
        return _eval_state_condition(cp)
    raise TypeError(f"unknown checkpoint type: {type(cp).__name__}")


# ---------------------------------------------------------------------------
# Minefield evaluation
# ---------------------------------------------------------------------------


def _eval_minefield(mf: Minefield, agent_calls: list[Step]) -> MinefieldResult:
    if mf.forbidden_tool is None:
        return MinefieldResult(
            minefield_id=mf.minefield_id,
            hit=False,
            reason="minefield has no forbidden_tool — trivially not tripped",
        )
    target = (mf.forbidden_tool.server_id, mf.forbidden_tool.tool_name)
    for step in agent_calls:
        if step.tool_name is None:
            continue
        if (step.server_id, step.tool_name) != target:
            continue
        if not _arg_predicate_matches(mf.forbidden_arg_predicate, step.arguments):
            continue
        return MinefieldResult(
            minefield_id=mf.minefield_id,
            hit=True,
            reason=f"tripped by step #{step.step_id} {step.server_id}.{step.tool_name}",
            tripped_step_id=step.step_id,
        )
    return MinefieldResult(
        minefield_id=mf.minefield_id,
        hit=False,
        reason="no candidate call matched forbidden_tool + forbidden_arg_predicate",
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def _eval_ordering(
    ordering: list[OrderConstraint],
    checkpoint_results: list[CheckpointResult],
) -> tuple[bool, list[str]]:
    pos_by_id: dict[str, int] = {}
    for cr in checkpoint_results:
        if cr.matched_step_id is not None:
            pos_by_id[cr.checkpoint_id] = cr.matched_step_id
    failures: list[str] = []
    for oc in ordering:
        b = pos_by_id.get(oc.before_id)
        a = pos_by_id.get(oc.after_id)
        if b is None or a is None:
            failures.append(
                f"ordering {oc.before_id} → {oc.after_id}: one or both checkpoints "
                "not satisfied with a concrete step (cannot verify order)"
            )
            continue
        if not (b < a):
            failures.append(
                f"ordering {oc.before_id} (step #{b}) → {oc.after_id} (step #{a}): "
                "out of order"
            )
    return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Top-level evaluate
# ---------------------------------------------------------------------------


def evaluate(
    spec: TaskSpec,
    candidate: Trace,
    *,
    candidate_model: str | None = None,
    evaluation_mode: str | None = None,
) -> EvaluationResult:
    agent_calls = [
        s for s in candidate.steps if s.kind is StepKind.call_tool_agent
    ]
    checkpoint_results = [
        _eval_checkpoint(cp, agent_calls, candidate) for cp in spec.checkpoints
    ]
    minefield_results = [_eval_minefield(mf, agent_calls) for mf in spec.minefields]
    ordering_ok, ordering_failures = _eval_ordering(spec.ordering, checkpoint_results)

    all_checkpoints_pass = all(cr.passed for cr in checkpoint_results)
    no_minefield_hit = not any(mr.hit for mr in minefield_results)
    passed = all_checkpoints_pass and no_minefield_hit and ordering_ok

    summary = {
        "checkpoints_total": len(checkpoint_results),
        "checkpoints_passed": sum(1 for cr in checkpoint_results if cr.passed),
        "minefields_total": len(minefield_results),
        "minefields_hit": sum(1 for mr in minefield_results if mr.hit),
        "agent_call_count": len(agent_calls),
        "agent_call_success_count": sum(
            1 for s in agent_calls if s.status is StepStatus.success
        ),
    }

    return EvaluationResult(
        task_id=spec.task_id,
        candidate_trace_id=candidate.trace_id,
        candidate_model=candidate_model,
        evaluation_mode=evaluation_mode,
        passed=passed,
        checkpoint_results=checkpoint_results,
        minefield_results=minefield_results,
        ordering_ok=ordering_ok,
        ordering_failures=ordering_failures,
        summary=summary,
    )
