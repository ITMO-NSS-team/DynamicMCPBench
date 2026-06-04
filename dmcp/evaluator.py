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
    repeat_index: int = 0  # which repeat produced this run (pass^k); 0 when --repeat 1
    had_sae: bool = False  # set once SAE detection lands (E2.4); gates pass^k_no_SAE
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
        if matcher.contains is not None and (not isinstance(value, str) or matcher.contains not in value):
            return False
        if matcher.regex is not None and (not isinstance(value, str) or not re.search(matcher.regex, value)):
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


def _eval_tool_effect(cp: ToolEffectCheckpoint, agent_calls: list[Step]) -> CheckpointResult:
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
            reason=(f"matched step #{step.step_id} {step.server_id}.{step.tool_name}"),
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
            failures.append(f"ordering {oc.before_id} (step #{b}) → {oc.after_id} (step #{a}): out of order")
    return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Top-level evaluate
# ---------------------------------------------------------------------------


ERROR_WEIGHTS: dict[str, float] = {
    "E1": 1.0,  # missing prerequisite
    "E2": 0.8,  # wrong branch (not auto-classified in v0)
    "E3": 0.6,  # incomplete aggregation
    "E4": 1.0,  # server confusion (SAE)
    "E5": 0.4,  # order violation
    "E6": 1.0,  # tool blindness
    "E7": 0.7,  # argument hallucination
}
ERROR_NAMES: dict[str, str] = {
    "E1": "missing_prerequisite",
    "E2": "wrong_branch",
    "E3": "incomplete_aggregation",
    "E4": "server_confusion",
    "E5": "order_violation",
    "E6": "tool_blindness",
    "E7": "argument_hallucination",
}


def _classify_errors(
    spec: TaskSpec,
    agent_calls: list[Step],
    checkpoint_results: list[CheckpointResult],
    ordering_ok: bool,
) -> dict[str, Any]:
    """Classify a failed evaluation into the 7-type error taxonomy (PDF §5.2).

    Per failed tool_effect checkpoint: E4 if its tool was called on a wrong
    server (SAE); else E7 if an acceptable (server,tool) was attempted but did
    not satisfy (bad args / errored); else E1 if the checkpoint is a prerequisite
    (a `before_id` in the ordering); else E6 (tool never reached for). Failed
    value_produced → E3. A broken partial order → E5. E2 (wrong branch) is not
    auto-classified in v0 (needs plan-branch annotations) and stays 0.
    """
    counts: dict[str, int] = dict.fromkeys(ERROR_WEIGHTS, 0)
    prereqs = {oc.before_id for oc in spec.ordering}
    cp_by_id = {cp.checkpoint_id: cp for cp in spec.checkpoints}
    success_calls = [s for s in agent_calls if s.status is StepStatus.success and s.tool_name]
    for cr in checkpoint_results:
        if cr.passed:
            continue
        cp = cp_by_id.get(cr.checkpoint_id)
        if isinstance(cp, ToolEffectCheckpoint):
            acceptable = {(r.server_id, r.tool_name) for r in cp.equivalence_set}
            names = {r.tool_name for r in cp.equivalence_set}
            sae = any(
                s.tool_name in names and (s.server_id, s.tool_name) not in acceptable for s in success_calls
            )
            attempted = any((s.server_id, s.tool_name) in acceptable for s in agent_calls if s.tool_name)
            if sae:
                counts["E4"] += 1
            elif attempted:
                counts["E7"] += 1
            elif cr.checkpoint_id in prereqs:
                counts["E1"] += 1
            else:
                counts["E6"] += 1
        elif isinstance(cp, ValueProducedCheckpoint):
            counts["E3"] += 1
    if not ordering_ok:
        counts["E5"] += 1
    weighted = sum(counts[c] * ERROR_WEIGHTS[c] for c in counts)
    return {
        "counts": counts,
        "weights": ERROR_WEIGHTS,
        "names": ERROR_NAMES,
        "weighted_score": round(weighted, 3),
    }


def _shares_tag(server: str, others: set[str], server_tags: dict[str, list[str]] | None) -> bool:
    if not server_tags:
        return False
    tags = set(server_tags.get(server, []))
    return bool(tags) and any(tags & set(server_tags.get(o, [])) for o in others)


def _detect_sae(
    spec: TaskSpec,
    agent_calls: list[Step],
    server_tags: dict[str, list[str]] | None,
) -> dict[str, Any]:
    """Server Attribution Error: a successful call of a required tool-NAME on a
    server that is NOT acceptable for it (right tool type, wrong server).

    Subtypes: `expected` if the wrong server shares a domain tag with a correct
    server (a GitHub/GitLab-style alternative), else `random` (more serious — an
    unrelated server). `conditional_rate` = SAE / (SAE + correct-type calls): of
    the calls that hit the right tool type, the fraction on the wrong server.
    Only meaningful when distractor servers are offered (Target/Full pool).
    """
    name_to_servers: dict[str, set[str]] = {}
    for cp in spec.checkpoints:
        if isinstance(cp, ToolEffectCheckpoint):
            for r in cp.equivalence_set:
                name_to_servers.setdefault(r.tool_name, set()).add(r.server_id)

    events: list[dict[str, Any]] = []
    correct_type_calls = 0
    for s in agent_calls:
        if s.status is not StepStatus.success or s.tool_name is None:
            continue
        correct_servers = name_to_servers.get(s.tool_name)
        if not correct_servers:
            continue
        if s.server_id in correct_servers:
            correct_type_calls += 1
            continue
        subtype = "expected" if _shares_tag(s.server_id, correct_servers, server_tags) else "random"
        events.append(
            {
                "tool_name": s.tool_name,
                "called_server": s.server_id,
                "correct_servers": sorted(correct_servers),
                "subtype": subtype,
            }
        )
    total = len(events)
    expected = sum(1 for e in events if e["subtype"] == "expected")
    denom = total + correct_type_calls
    return {
        "total": total,
        "expected": expected,
        "random": total - expected,
        "correct_type_calls": correct_type_calls,
        "conditional_rate": round(total / denom, 4) if denom else 0.0,
        "events": events,
    }


def _detect_iae(
    spec: TaskSpec,
    checkpoint_results: list[CheckpointResult],
) -> dict[str, Any]:
    """Incomplete Aggregation Error rollup (E8.5 / rev.1 §5.1).

    IAE counts failed `ValueProducedCheckpoint`s — the rev.1 PDF's incomplete
    aggregation case (the candidate touched the right tools but didn't surface
    the final value the spec demands). The denominator is the count of
    value_produced checkpoints in the spec (the *opportunities* for incomplete
    aggregation); `rate` is None when the spec has no such checkpoints so
    aggregators see honest "undefined" instead of an artificial zero.
    """
    cp_by_id = {cp.checkpoint_id: cp for cp in spec.checkpoints}
    opportunities = sum(1 for cp in spec.checkpoints if isinstance(cp, ValueProducedCheckpoint))
    events: list[dict[str, Any]] = []
    for cr in checkpoint_results:
        if cr.passed:
            continue
        cp = cp_by_id.get(cr.checkpoint_id)
        if isinstance(cp, ValueProducedCheckpoint):
            events.append({"checkpoint_id": cr.checkpoint_id, "reason": cr.reason})
    total = len(events)
    return {
        "total": total,
        "opportunities": opportunities,
        "rate": round(total / opportunities, 4) if opportunities else None,
        "events": events,
    }


def evaluate(
    spec: TaskSpec,
    candidate: Trace,
    *,
    candidate_model: str | None = None,
    evaluation_mode: str | None = None,
    server_tags: dict[str, list[str]] | None = None,
) -> EvaluationResult:
    agent_calls = [s for s in candidate.steps if s.kind is StepKind.call_tool_agent]
    sae = _detect_sae(spec, agent_calls, server_tags)
    checkpoint_results = [_eval_checkpoint(cp, agent_calls, candidate) for cp in spec.checkpoints]
    minefield_results = [_eval_minefield(mf, agent_calls) for mf in spec.minefields]
    ordering_ok, ordering_failures = _eval_ordering(spec.ordering, checkpoint_results)
    errors = _classify_errors(spec, agent_calls, checkpoint_results, ordering_ok)
    iae = _detect_iae(spec, checkpoint_results)

    all_checkpoints_pass = all(cr.passed for cr in checkpoint_results)
    no_minefield_hit = not any(mr.hit for mr in minefield_results)
    passed = all_checkpoints_pass and no_minefield_hit and ordering_ok

    summary = {
        "checkpoints_total": len(checkpoint_results),
        "checkpoints_passed": sum(1 for cr in checkpoint_results if cr.passed),
        "minefields_total": len(minefield_results),
        "minefields_hit": sum(1 for mr in minefield_results if mr.hit),
        "agent_call_count": len(agent_calls),
        "agent_call_success_count": sum(1 for s in agent_calls if s.status is StepStatus.success),
        "sae": sae,
        "iae": iae,
        "error_taxonomy": errors,
    }
    cost = candidate.seed_metadata.get("cost")
    if isinstance(cost, dict) and cost:
        summary["cost"] = cost

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
        had_sae=sae["total"] > 0,
    )
