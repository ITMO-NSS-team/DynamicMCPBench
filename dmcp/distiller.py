"""Trace distiller (Phase 2B of the rev. 3 plan).

Reads a Trace and emits a TaskSpec. Deterministic features (trace depth,
runtime branching, recovery) are extracted by code; the fuzzy prompt and the
checkpoints/minefields are proposed by an LLM constrained to a tool-call
schema.

The distiller is deliberately conservative: it refuses to emit a TaskSpec for
traces with no successful tool calls, and it always echoes the LLM's
ambiguity notes into TaskSpec.notes so reviewers can see what the model was
unsure about.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from dmcp.llm import OpenRouterClient
from dmcp.manifest import Dynamism, Manifest
from dmcp.spec import (
    ArgPredicate,
    ArgValueMatch,
    Checkpoint,
    ComplexityProfile,
    Minefield,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import StepKind, StepStatus, Trace

DISTILLER_VERSION = "0.1.0"

DISTILLER_SYSTEM = """You are compiling an MCP tool-use trace into a benchmark task specification.

You will be shown:
  - the original exploration goal
  - the successful tool calls the explorer made, in order, with arguments and result previews
  - a list of available tools per server

Your job is to call the `emit_task_spec` tool exactly once, with:

  - prompt: a fuzzy natural-language user request for this task. Strip explicit
    tool names, but DO PRESERVE concrete context the agent needs to act on:
    repo paths, file names, URLs, specific identifiers from the goal. A task
    that mentions "the git sandbox repository" without saying *where* is
    unsolvable by a candidate that wasn't there at exploration time.

  - checkpoints: at least one. Each must be one of:
      {"kind": "tool_effect", ...}        — a tool from a given equivalence
        set must have been called successfully, optionally matching args.
        Use this when "the agent had to do this lookup/action."
      {"kind": "value_produced", ...}     — a tool result (or the final
        assistant message) must contain certain substrings.
        Use this for the user-visible facts the answer depends on.

  - For arg_predicate on tool_effect checkpoints, you have TWO matching modes:
      * must_include: EXACT EQUALITY. {"timezone": "UTC"} matches only when
        the call's timezone argument equals exactly "UTC".
      * must_match:   richer per-key matchers. Use this for partial matches:
          {"branch_name": {"starts_with": "snapshot-"}}
          {"path": {"contains": "/tmp/"}}
          {"id": {"regex": "^user_[0-9]+$"}}
        Pick must_match whenever the value in the trace is a variable
        derivative (timestamp-encoded name, generated id) — NOT must_include
        with a partial value, because that won't ever match exactly.

  - minefields: things the agent must NOT do (e.g., call a destructive tool).
    Often empty for read-only tasks.

  - notes: anything ambiguous or any alternative valid path you noticed.

Be tight: do not invent checkpoints the trace does not justify. Path-agnostic
matters — when two tools would equally satisfy a checkpoint, list them both
in equivalence_set.
""".strip()


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _successful_agent_calls(trace: Trace) -> list:
    return [s for s in trace.steps if s.kind is StepKind.call_tool_agent and s.status is StepStatus.success]


def _had_recovery(trace: Trace) -> bool:
    """At least one failed agent call followed by a success."""
    seen_failure = False
    for s in trace.steps:
        if s.kind is not StepKind.call_tool_agent:
            continue
        if s.status is StepStatus.success and seen_failure:
            return True
        if s.status is StepStatus.error:
            seen_failure = True
    return False


_DIGIT_WINDOW = 6


def _digits_only(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def _runtime_branching(trace: Trace) -> bool:
    """Heuristic: does a later call's argument come from an earlier result?

    Catches two patterns:
      1) raw substring: the later arg appears verbatim in an earlier result.
         Works for names, paths, ids carried through unchanged.
      2) digit-window reuse: any 6+ contiguous-digit window from the later
         arg's digit-only projection appears in an earlier result's digit-only
         projection. Catches reformatted timestamps —
         '2026-05-28T13:17:05' → 'snapshot-20260528-131705' — where the raw
         substring check fails because punctuation was dropped.

    6-digit threshold avoids false positives from common years (4 digits).
    """
    prior_blobs: list[str] = []
    prior_digit_blobs: list[str] = []
    for s in trace.steps:
        if s.kind is not StepKind.call_tool_agent:
            continue
        if s.arguments:
            for v in s.arguments.values():
                if not isinstance(v, str) or len(v) < 3:
                    continue
                if any(v in blob for blob in prior_blobs):
                    return True
                d = _digits_only(v)
                if len(d) >= _DIGIT_WINDOW and prior_digit_blobs:
                    for i in range(len(d) - _DIGIT_WINDOW + 1):
                        window = d[i : i + _DIGIT_WINDOW]
                        if any(window in pd for pd in prior_digit_blobs):
                            return True
        if s.status is StepStatus.success and s.result is not None:
            blob = json.dumps(s.result, default=str)
            prior_blobs.append(blob)
            prior_digit_blobs.append(_digits_only(blob))
    return False


def _trace_view_for_llm(trace: Trace, max_chars_per_result: int = 1200) -> dict[str, Any]:
    """Compact, LLM-friendly summary of a trace."""
    successful = _successful_agent_calls(trace)
    steps_view: list[dict[str, Any]] = []
    for s in successful:
        result_preview: str
        if s.result is None:
            result_preview = "(no result)"
        else:
            parts: list[str] = []
            for c in s.result.get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
            rendered = "\n".join(parts) if parts else json.dumps(s.result, default=str)
            result_preview = rendered[:max_chars_per_result]
        steps_view.append(
            {
                "server_id": s.server_id,
                "tool_name": s.tool_name,
                "arguments": s.arguments,
                "result_preview": result_preview,
            }
        )
    tools_view = {
        sid: [{"name": t.name, "description": t.description} for t in specs]
        for sid, specs in trace.tool_specs.items()
    }
    return {
        "goal": trace.goal,
        "available_tools_by_server": tools_view,
        "successful_steps_in_order": steps_view,
        "final_assistant_message": ((trace.seed_metadata.get("exploration") or {}).get("final_message")),
    }


# ---------------------------------------------------------------------------
# LLM tool schema
# ---------------------------------------------------------------------------


def _emit_task_spec_tool_schema() -> dict[str, Any]:
    """OpenAI tool schema that constrains the LLM to a valid partial TaskSpec.

    We do not let the LLM fill task_id, source_trace_id, dynamism, complexity,
    servers_used — those are derived deterministically by the distiller.
    """
    tool_ref = {
        "type": "object",
        "additionalProperties": False,
        "required": ["server_id", "tool_name"],
        "properties": {
            "server_id": {"type": "string"},
            "tool_name": {"type": "string"},
        },
    }
    arg_value_match = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "equals": {},
            "starts_with": {"type": "string"},
            "contains": {"type": "string"},
            "regex": {"type": "string"},
        },
    }
    arg_predicate = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "must_include": {
                "type": "object",
                "additionalProperties": True,
                "description": "Exact-equality constraints on top-level args.",
            },
            "must_match": {
                "type": "object",
                "additionalProperties": arg_value_match,
                "description": (
                    "Per-key richer matchers (starts_with / contains / regex). "
                    "Use this for variable-derivative values like generated names."
                ),
            },
        },
    }
    value_predicate = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "contains_any": {"type": "array", "items": {"type": "string"}},
            "contains_all": {"type": "array", "items": {"type": "string"}},
            "regex": {"type": "string"},
        },
    }
    tool_effect = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "checkpoint_id", "description", "equivalence_set"],
        "properties": {
            "kind": {"const": "tool_effect"},
            "checkpoint_id": {"type": "string"},
            "description": {"type": "string"},
            "equivalence_set": {"type": "array", "items": tool_ref, "minItems": 1},
            "arg_predicate": arg_predicate,
            "must_succeed": {"type": "boolean", "default": True},
        },
    }
    value_produced = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "checkpoint_id", "description", "predicate"],
        "properties": {
            "kind": {"const": "value_produced"},
            "checkpoint_id": {"type": "string"},
            "description": {"type": "string"},
            "predicate": value_predicate,
            "scope": {"enum": ["any_tool_result", "final_assistant_message"]},
        },
    }
    minefield = {
        "type": "object",
        "additionalProperties": False,
        "required": ["minefield_id", "description"],
        "properties": {
            "minefield_id": {"type": "string"},
            "description": {"type": "string"},
            "forbidden_tool": tool_ref,
            "forbidden_arg_predicate": arg_predicate,
        },
    }
    return {
        "type": "function",
        "function": {
            "name": "emit_task_spec",
            "description": "Emit the distilled task spec for the given trace.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prompt", "checkpoints"],
                "properties": {
                    "prompt": {"type": "string", "description": "Fuzzy NL user request."},
                    "checkpoints": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"oneOf": [tool_effect, value_produced]},
                    },
                    "minefields": {"type": "array", "items": minefield, "default": []},
                    "notes": {"type": "string"},
                },
            },
        },
    }


def _parse_arg_predicate(raw: dict[str, Any] | None) -> ArgPredicate | None:
    if not raw:
        return None
    must_match_raw = raw.get("must_match") or {}
    must_match = {k: ArgValueMatch(**v) for k, v in must_match_raw.items()}
    return ArgPredicate(
        must_include=raw.get("must_include") or {},
        must_match=must_match,
    )


def _parse_checkpoint(raw: dict[str, Any]) -> Checkpoint:
    kind = raw.get("kind")
    if kind == "tool_effect":
        return ToolEffectCheckpoint(
            checkpoint_id=raw["checkpoint_id"],
            description=raw["description"],
            equivalence_set=[ToolReference(**t) for t in raw["equivalence_set"]],
            arg_predicate=_parse_arg_predicate(raw.get("arg_predicate")),
            must_succeed=raw.get("must_succeed", True),
        )
    if kind == "value_produced":
        return ValueProducedCheckpoint(
            checkpoint_id=raw["checkpoint_id"],
            description=raw["description"],
            predicate=ValuePredicate(**raw["predicate"]),
            scope=raw.get("scope", "any_tool_result"),
        )
    raise ValueError(f"unknown checkpoint kind: {kind}")


def _parse_minefield(raw: dict[str, Any]) -> Minefield:
    return Minefield(
        minefield_id=raw["minefield_id"],
        description=raw["description"],
        forbidden_tool=(ToolReference(**raw["forbidden_tool"]) if raw.get("forbidden_tool") else None),
        forbidden_arg_predicate=_parse_arg_predicate(raw.get("forbidden_arg_predicate")),
    )


# ---------------------------------------------------------------------------
# Distiller
# ---------------------------------------------------------------------------


class DistillationError(Exception):
    pass


def derive_dynamism(server_ids: list[str], manifest: Manifest | None) -> Dynamism:
    """Task dynamism = max over involved servers' dynamism."""
    rank = {Dynamism.static: 0, Dynamism.live_read: 1, Dynamism.stateful_write: 2}
    if manifest is None:
        return Dynamism.live_read
    classes = [manifest.by_id(sid).dynamism for sid in server_ids if _safe_has(manifest, sid)]
    if not classes:
        return Dynamism.live_read
    return max(classes, key=lambda d: rank[d])


def _safe_has(manifest: Manifest, sid: str) -> bool:
    try:
        manifest.by_id(sid)
        return True
    except KeyError:
        return False


async def distill(
    trace: Trace,
    *,
    llm: OpenRouterClient,
    manifest: Manifest | None = None,
) -> TaskSpec:
    successful = _successful_agent_calls(trace)
    if not successful:
        raise DistillationError("trace has no successful agent tool calls")

    server_ids = sorted({s.server_id for s in successful})
    complexity = ComplexityProfile(
        trace_depth=len(successful),
        distinct_servers=len(server_ids),
        cross_server=len(server_ids) > 1,
        runtime_branching=_runtime_branching(trace),
        state_coupling=(
            manifest is not None
            and any(
                manifest.by_id(sid).dynamism is Dynamism.stateful_write
                for sid in server_ids
                if _safe_has(manifest, sid)
            )
        ),
        recovery_required=_had_recovery(trace),
    )
    dynamism = derive_dynamism(server_ids, manifest)

    view = _trace_view_for_llm(trace)
    messages = [
        {"role": "system", "content": DISTILLER_SYSTEM},
        {
            "role": "user",
            "content": (
                "Distill this trace into a TaskSpec. Call `emit_task_spec` exactly once.\n\n"
                f"```json\n{json.dumps(view, indent=2, default=str)}\n```"
            ),
        },
    ]
    tools = [_emit_task_spec_tool_schema()]
    resp = await llm.chat(
        messages=messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "emit_task_spec"}},
        temperature=0.0,
    )
    if not resp.tool_calls:
        raise DistillationError(f"LLM did not call emit_task_spec; content={resp.content!r}")
    args = resp.tool_calls[0].arguments

    try:
        checkpoints = [_parse_checkpoint(c) for c in args["checkpoints"]]
        minefields = [_parse_minefield(m) for m in args.get("minefields") or []]
    except (KeyError, ValueError) as e:
        raise DistillationError(f"could not parse LLM output: {e}") from e

    return TaskSpec(
        task_id=uuid4(),
        distiller_version=DISTILLER_VERSION,
        source_trace_id=trace.trace_id,
        prompt=args["prompt"],
        dynamism=dynamism,
        servers_used=server_ids,
        complexity=complexity,
        checkpoints=checkpoints,
        minefields=minefields,
        notes=args.get("notes"),
    )
