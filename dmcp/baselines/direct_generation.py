"""Direct generate-then-verify TaskSpec generator (RQ2 baseline — NOT the headline).

This module implements the MCPEval-shape baseline for RQ2: feed an LLM the raw
tool surface of a server (no trace, no graph, no exploration), ask it to invent
a task that uses some of those tools, then **verify** the proposal mechanically
before emitting a `TaskSpec`. Verification rejects any proposal that references
a tool not in the surface or a top-level argument key the tool's input schema
doesn't declare.

Pipeline (each step deliberately *not* the headline):

  tool surfaces (manifest)
       │
       ▼
  LLM proposes:  prompt + [tool_name + args]+ + optional expected_substrings
       │
       ▼
  verifier: every tool exists, every must_include key is a real top-level
            parameter, prompt is non-empty (one retry on failure)
       │
       ▼
  TaskSpec: singleton `tool_effect` checkpoints per proposed tool (AGB-style
            GT-tool-list shape — the *point* of this comparison baseline)
            + optional `value_produced` checkpoint from expected_substrings.
            Marked `distiller_version="baseline-direct-generation-<v>"` and
            notes prefixed `[BASELINE:direct_generation]`.

Per `memory/feedback_agb_orthogonality.md`: this stays a labeled comparison
baseline, never the headline. We do NOT grade a final answer here either —
`value_produced` checks the *tool result*, not the candidate's reply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from dmcp.llm import OpenRouterClient
from dmcp.manifest import Dynamism, Manifest
from dmcp.spec import (
    SPEC_SCHEMA_VERSION,
    ArgPredicate,
    ComplexityProfile,
    OrderConstraint,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import ToolSpec

BASELINE_VERSION = "0.1.0"
DISTILLER_VERSION = f"baseline-direct-generation-{BASELINE_VERSION}"

DIRECT_SYSTEM = """You are designing a benchmark task from an MCP server's tool surface.

You will be shown one or more MCP servers with their tools (name, description,
input schema). Call `emit_direct_proposal` exactly once with:

  prompt:               a natural-language user request a real user might voice.
                        Strip explicit tool names. Do NOT invent concrete
                        external resources (file paths, ids, urls) that don't
                        appear in the tool schemas. When you'd otherwise need
                        to invent a resource, prefer discovery phrasings.

  tool_calls:           an ordered list of {server_id, tool_name, arguments}
                        that together accomplish the task. Use ONLY tools and
                        argument names that are declared in the provided
                        surface — anything else will be rejected by the
                        verifier and the proposal will be discarded.

  expected_substrings:  (optional) substrings that the tool RESULT text should
                        contain. Use this only when the prompt implies a
                        specific user-visible fact must come back. Empty is
                        fine.

  sequential:           true iff later tool calls genuinely depend on earlier
                        results; false if they can be issued in any order.

  notes:                anything ambiguous or any alternative interpretation.

This is a labeled RQ2 baseline (direct generate-then-verify). Stay faithful:
do not invent tools or arguments that aren't in the surface.
""".strip()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedToolCall:
    server_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class DirectProposal:
    """One LLM-proposed task before verification."""

    prompt: str
    tool_calls: list[ProposedToolCall]
    expected_substrings: list[str] = field(default_factory=list)
    sequential: bool = False
    notes: str = ""


class GenerationError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _surface_index(
    surfaces: dict[str, list[ToolSpec]],
) -> dict[tuple[str, str], ToolSpec]:
    out: dict[tuple[str, str], ToolSpec] = {}
    for sid, specs in surfaces.items():
        for s in specs:
            out[(sid, s.name)] = s
    return out


def _top_level_param_names(spec: ToolSpec) -> set[str]:
    schema = spec.input_schema or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return set()
    return {k for k in props if isinstance(k, str)}


def verify_proposal(
    proposal: DirectProposal,
    surfaces: dict[str, list[ToolSpec]],
) -> list[str]:
    """Mechanically check a proposal against the tool surface.

    Returns a list of human-readable errors; an empty list means the proposal
    is well-formed. Verification is the load-bearing half of the
    generate-then-verify shape: the LLM is free to be creative, but anything
    that doesn't fit the surface gets rejected.
    """
    errors: list[str] = []
    if not proposal.prompt.strip():
        errors.append("empty prompt")
    if not proposal.tool_calls:
        errors.append("no tool_calls proposed")
    index = _surface_index(surfaces)
    for i, call in enumerate(proposal.tool_calls):
        key = (call.server_id, call.tool_name)
        if key not in index:
            errors.append(f"tool_calls[{i}]: unknown tool {call.server_id}.{call.tool_name}")
            continue
        params = _top_level_param_names(index[key])
        # When the surface lacks a JSON Schema we can't verify argument names;
        # skip the per-arg check in that case (the proposal still survives,
        # but the resulting checkpoint will carry the arg predicate as-is).
        if not params:
            continue
        for arg_name in call.arguments:
            if arg_name not in params:
                errors.append(
                    f"tool_calls[{i}]: arg {arg_name!r} not in {call.server_id}.{call.tool_name} input_schema"
                )
    return errors


# ---------------------------------------------------------------------------
# LLM proposal
# ---------------------------------------------------------------------------


def _emit_direct_proposal_schema() -> dict[str, Any]:
    tool_call_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["server_id", "tool_name"],
        "properties": {
            "server_id": {"type": "string"},
            "tool_name": {"type": "string"},
            "arguments": {
                "type": "object",
                "additionalProperties": True,
                "description": "Top-level argument keys must exist in the tool's input_schema.",
            },
        },
    }
    return {
        "type": "function",
        "function": {
            "name": "emit_direct_proposal",
            "description": "Emit a direct-generated task proposal.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prompt", "tool_calls"],
                "properties": {
                    "prompt": {"type": "string"},
                    "tool_calls": {
                        "type": "array",
                        "minItems": 1,
                        "items": tool_call_schema,
                    },
                    "expected_substrings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "sequential": {"type": "boolean", "default": False},
                    "notes": {"type": "string"},
                },
            },
        },
    }


def _surface_view(surfaces: dict[str, list[ToolSpec]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid, specs in surfaces.items():
        out.append(
            {
                "server_id": sid,
                "tools": [
                    {
                        "name": s.name,
                        "description": (s.description or "")[:300],
                        "input_schema": s.input_schema or {},
                    }
                    for s in specs
                ],
            }
        )
    return out


def _parse_proposal(args: dict[str, Any]) -> DirectProposal:
    raw_calls = args.get("tool_calls") or []
    tool_calls: list[ProposedToolCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        tool_calls.append(
            ProposedToolCall(
                server_id=str(raw.get("server_id") or ""),
                tool_name=str(raw.get("tool_name") or ""),
                arguments=raw.get("arguments") or {},
            )
        )
    expected = args.get("expected_substrings") or []
    if not isinstance(expected, list):
        expected = []
    return DirectProposal(
        prompt=str(args.get("prompt") or "").strip(),
        tool_calls=tool_calls,
        expected_substrings=[str(s) for s in expected if isinstance(s, str)],
        sequential=bool(args.get("sequential", False)),
        notes=str(args.get("notes") or "").strip(),
    )


async def propose(
    surfaces: dict[str, list[ToolSpec]],
    *,
    llm: OpenRouterClient,
    extra_user_hint: str | None = None,
) -> DirectProposal:
    """Ask the LLM for one proposal — no verification yet."""
    view = _surface_view(surfaces)
    user_content = (
        "Compose one direct-generated benchmark task for these tools and call "
        "`emit_direct_proposal` exactly once.\n\n"
        f"```json\n{json.dumps(view, indent=2, default=str)}\n```"
    )
    if extra_user_hint:
        user_content += f"\n\nAdditional guidance: {extra_user_hint}"
    messages = [
        {"role": "system", "content": DIRECT_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    resp = await llm.chat(
        messages=messages,
        tools=[_emit_direct_proposal_schema()],
        tool_choice={"type": "function", "function": {"name": "emit_direct_proposal"}},
        temperature=0.0,
    )
    if not resp.tool_calls:
        raise GenerationError(f"LLM did not call emit_direct_proposal; content={resp.content!r}")
    return _parse_proposal(resp.tool_calls[0].arguments)


# ---------------------------------------------------------------------------
# TaskSpec emission
# ---------------------------------------------------------------------------


def _derive_dynamism(server_ids: list[str], manifest: Manifest | None) -> Dynamism:
    rank = {Dynamism.static: 0, Dynamism.live_read: 1, Dynamism.stateful_write: 2}
    if manifest is None:
        return Dynamism.live_read
    classes: list[Dynamism] = []
    for sid in server_ids:
        try:
            classes.append(manifest.by_id(sid).dynamism)
        except KeyError:
            continue
    if not classes:
        return Dynamism.live_read
    return max(classes, key=lambda d: rank[d])


def _derive_complexity(proposal: DirectProposal, manifest: Manifest | None) -> ComplexityProfile:
    server_ids = sorted({c.server_id for c in proposal.tool_calls})
    state_coupling = False
    if manifest is not None:
        for sid in server_ids:
            try:
                if manifest.by_id(sid).dynamism is Dynamism.stateful_write:
                    state_coupling = True
                    break
            except KeyError:
                continue
    return ComplexityProfile(
        trace_depth=len(proposal.tool_calls),
        distinct_servers=len(server_ids),
        cross_server=len(server_ids) > 1,
        runtime_branching=False,
        state_coupling=state_coupling,
        recovery_required=False,
    )


def to_taskspec(
    proposal: DirectProposal,
    *,
    manifest: Manifest | None = None,
) -> TaskSpec:
    """Build a baseline TaskSpec from a *verified* proposal.

    Singleton `equivalence_set`s are intentional — this baseline imitates the
    AGB-style GT-tool-list shape on purpose so RQ2 can quantify the gap to the
    forward path's path-agnostic equivalence sets.
    """
    server_ids = sorted({c.server_id for c in proposal.tool_calls})
    cps: list[ToolEffectCheckpoint | ValueProducedCheckpoint] = []
    for i, call in enumerate(proposal.tool_calls):
        arg_pred = ArgPredicate(must_include=dict(call.arguments)) if call.arguments else None
        cps.append(
            ToolEffectCheckpoint(
                checkpoint_id=f"cp-{i}",
                description=f"call {call.server_id}.{call.tool_name}",
                equivalence_set=[ToolReference(server_id=call.server_id, tool_name=call.tool_name)],
                arg_predicate=arg_pred,
                must_succeed=True,
            )
        )
    if proposal.expected_substrings:
        cps.append(
            ValueProducedCheckpoint(
                checkpoint_id=f"cp-{len(proposal.tool_calls)}",
                description="tool result must contain expected substrings",
                predicate=ValuePredicate(contains_all=list(proposal.expected_substrings)),
                scope="any_tool_result",
            )
        )

    ordering: list[OrderConstraint] = []
    if proposal.sequential and len(proposal.tool_calls) > 1:
        ordering = [
            OrderConstraint(before_id=f"cp-{i}", after_id=f"cp-{i + 1}")
            for i in range(len(proposal.tool_calls) - 1)
        ]

    note_tag = "[BASELINE:direct_generation]"
    notes = note_tag if not proposal.notes else f"{note_tag} {proposal.notes}"

    return TaskSpec(
        task_id=uuid4(),
        schema_version=SPEC_SCHEMA_VERSION,
        distiller_version=DISTILLER_VERSION,
        source_trace_id=uuid4(),  # no trace; synthetic id
        prompt=proposal.prompt,
        dynamism=_derive_dynamism(server_ids, manifest),
        servers_used=server_ids,
        complexity=_derive_complexity(proposal, manifest),
        checkpoints=list(cps),
        minefields=[],
        ordering=ordering,
        notes=notes,
    )


async def generate_direct(
    surfaces: dict[str, list[ToolSpec]],
    *,
    llm: OpenRouterClient,
    manifest: Manifest | None = None,
    max_attempts: int = 2,
) -> TaskSpec:
    """Generate-then-verify: propose, verify, retry once on verifier failure.

    The retry includes the verifier's error messages so the LLM can correct
    its proposal — this is the standard MCPEval-shape recovery loop. After
    `max_attempts` failed attempts we raise GenerationError so the caller can
    skip and continue (matches the rest of dmcp's "no half-baked specs" rule).
    """
    if not surfaces:
        raise GenerationError("no tool surfaces provided")
    last_errors: list[str] = []
    hint: str | None = None
    for attempt in range(max(1, max_attempts)):
        proposal = await propose(surfaces, llm=llm, extra_user_hint=hint)
        errors = verify_proposal(proposal, surfaces)
        if not errors:
            return to_taskspec(proposal, manifest=manifest)
        last_errors = errors
        hint = (
            "Your previous proposal failed verification:\n  - "
            + "\n  - ".join(errors)
            + "\nFix it: use only the tools and argument names declared in the surface."
        )
        if attempt + 1 >= max_attempts:
            break
    raise GenerationError(f"proposal failed verification after {max_attempts} attempt(s): {last_errors}")
