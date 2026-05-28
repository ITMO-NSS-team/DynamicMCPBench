"""Tier-2 LLM judge: effect-equivalence for failed tool_effect checkpoints.

When the deterministic Tier-1 scorer rejects a `tool_effect` checkpoint
because the candidate used a different tool or different argument shape, we
sometimes still want to credit the candidate if it achieved the same
*effect* through a different path. That's what this module decides.

Critically: the judge is asked about effect equivalence ONLY. It does not
see the spec's prompt as something to grade, it does not score the final
answer, and it does not get to add or remove other checkpoints. Its single
authority is to flip one specific failed tool_effect checkpoint to passed
when the candidate trace clearly achieves the equivalent effect.

Anti-bias practices from the rev. 3 plan Phase 4 Tier 2 (partial v0):
  - binary judgment (equivalent: yes/no), not a numeric score
  - bidirectional framing: judge is reminded that "no, not equivalent" is the
    safe default
  - tight output schema enforced via tool calling
  - the judge is told what the failing checkpoint actually requires, and is
    shown only the candidate's successful tool calls (so it can't fabricate)

Out of scope for v0: cross-family ensemble judging, prompt shuffling,
self-enhancement bias mitigation, calibration to a human-annotated set —
those land when we have a real gold set.
"""

from __future__ import annotations

import json
from typing import Any

from dmcp.evaluator import CheckpointResult
from dmcp.llm import OpenRouterClient
from dmcp.spec import ToolEffectCheckpoint
from dmcp.trace import StepStatus, Trace

JUDGE_VERSION = "0.1.0"

JUDGE_SYSTEM = """You are an effect-equivalence judge for an agent benchmark.

You will be shown:
  - one *failed* tool_effect checkpoint that the candidate did not satisfy
    by the deterministic rule
  - the candidate's full list of successful tool calls (server, tool, args,
    short result preview)

Your job is to decide ONE binary question:

  Did the candidate achieve the same *effect* the checkpoint requires,
  via any path (different tool, different arguments, different sequence)?

Decision rules:
  - The default answer is NO. Only say YES when the candidate trace clearly
    contains evidence that the required effect was produced.
  - "Equivalent effect" means: an external observer of the world would not
    be able to tell whether the candidate took the reference path or an
    alternative path — the same fact was retrieved, the same record was
    created, the same state was mutated.
  - The candidate's final natural-language summary is NOT evidence on its
    own. You need to see a corresponding tool call.
  - For checkpoints whose arg_predicate names a specific value (e.g. a
    repo_path, a timezone), be strict: a different value usually means a
    different effect.

Call the `emit_equivalence_judgment` tool exactly once with your decision.
""".strip()


def _candidate_calls_view(trace: Trace, max_chars_per_result: int = 600) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in trace.steps:
        if s.tool_name is None or s.status is not StepStatus.success:
            continue
        result_preview = ""
        if s.result is not None:
            parts: list[str] = []
            for c in s.result.get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
            rendered = "\n".join(parts) if parts else json.dumps(s.result, default=str)
            result_preview = rendered[:max_chars_per_result]
        out.append(
            {
                "step_id": s.step_id,
                "server_id": s.server_id,
                "tool_name": s.tool_name,
                "arguments": s.arguments,
                "result_preview": result_preview,
            }
        )
    return out


def _judge_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_equivalence_judgment",
            "description": "Emit the binary equivalence decision for one failed checkpoint.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["equivalent", "reason"],
                "properties": {
                    "equivalent": {
                        "type": "boolean",
                        "description": (
                            "True ONLY if a tool call in the candidate trace clearly "
                            "produced the required effect."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "One short sentence citing the step_id that produced the "
                            "effect, or naming what was missing."
                        ),
                    },
                    "candidate_step_id": {
                        "type": ["integer", "null"],
                        "description": (
                            "Step id of the candidate call that produced the effect, "
                            "if equivalent=true."
                        ),
                    },
                },
            },
        },
    }


async def judge_tool_effect(
    cp: ToolEffectCheckpoint,
    tier1_result: CheckpointResult,
    candidate: Trace,
    *,
    llm: OpenRouterClient,
) -> CheckpointResult:
    """Re-decide a single failed tool_effect checkpoint via LLM judgment.

    If the judge says equivalent=True, returns an updated CheckpointResult
    with passed=True and tier=2. Otherwise returns the input tier1_result
    unchanged.
    """
    if tier1_result.passed:
        return tier1_result

    eq_set = [{"server_id": r.server_id, "tool_name": r.tool_name} for r in cp.equivalence_set]
    arg_pred: dict[str, Any] = {}
    if cp.arg_predicate is not None:
        if cp.arg_predicate.must_include:
            arg_pred["must_include"] = cp.arg_predicate.must_include
        if cp.arg_predicate.must_match:
            arg_pred["must_match"] = {
                k: v.model_dump(exclude_none=True) for k, v in cp.arg_predicate.must_match.items()
            }

    failed_checkpoint_view = {
        "checkpoint_id": cp.checkpoint_id,
        "description": cp.description,
        "equivalence_set_strict": eq_set,
        "arg_predicate_strict": arg_pred or None,
        "tier1_reason": tier1_result.reason,
    }
    candidate_view = _candidate_calls_view(candidate)

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                "Judge whether the candidate achieved the equivalent effect "
                "for this failed checkpoint. Call `emit_equivalence_judgment` once.\n\n"
                "Failed checkpoint:\n"
                f"```json\n{json.dumps(failed_checkpoint_view, indent=2, default=str)}\n```\n\n"
                "Candidate's successful tool calls:\n"
                f"```json\n{json.dumps(candidate_view, indent=2, default=str)}\n```"
            ),
        },
    ]
    try:
        resp = await llm.chat(
            messages=messages,
            tools=[_judge_tool_schema()],
            tool_choice={"type": "function", "function": {"name": "emit_equivalence_judgment"}},
            temperature=0.0,
        )
    except Exception as e:
        return CheckpointResult(
            checkpoint_id=tier1_result.checkpoint_id,
            kind=tier1_result.kind,
            passed=tier1_result.passed,
            reason=f"{tier1_result.reason} | tier-2 unavailable ({type(e).__name__})",
            matched_step_id=tier1_result.matched_step_id,
            tier=tier1_result.tier,
        )

    if not resp.tool_calls:
        return tier1_result

    args = resp.tool_calls[0].arguments
    equivalent = bool(args.get("equivalent"))
    reason = str(args.get("reason") or "")
    candidate_step_id = args.get("candidate_step_id")
    if isinstance(candidate_step_id, str):
        try:
            candidate_step_id = int(candidate_step_id)
        except ValueError:
            candidate_step_id = None

    if not equivalent:
        return CheckpointResult(
            checkpoint_id=tier1_result.checkpoint_id,
            kind=tier1_result.kind,
            passed=False,
            reason=f"tier-2 NO: {reason} (tier-1: {tier1_result.reason})",
            matched_step_id=tier1_result.matched_step_id,
            tier=2,
        )

    return CheckpointResult(
        checkpoint_id=tier1_result.checkpoint_id,
        kind=tier1_result.kind,
        passed=True,
        reason=f"tier-2 YES: {reason}",
        matched_step_id=candidate_step_id if isinstance(candidate_step_id, int) else None,
        tier=2,
    )


async def upgrade_with_judge(
    spec_checkpoints: list,
    candidate: Trace,
    tier1_results: list[CheckpointResult],
    *,
    llm: OpenRouterClient,
) -> list[CheckpointResult]:
    """Run the judge on each failed tool_effect result; pass the rest through.

    Other failed kinds (value_produced, state_condition) are NOT re-judged in
    v0 — value_produced is already a permissive substring check and we don't
    yet have a story for adjudicating it without sliding into "grade the
    final answer."
    """
    upgraded: list[CheckpointResult] = []
    cp_by_id = {c.checkpoint_id: c for c in spec_checkpoints}
    for r in tier1_results:
        if r.passed or r.kind != "tool_effect":
            upgraded.append(r)
            continue
        cp = cp_by_id.get(r.checkpoint_id)
        if not isinstance(cp, ToolEffectCheckpoint):
            upgraded.append(r)
            continue
        upgraded.append(await judge_tool_effect(cp, r, candidate, llm=llm))
    return upgraded
