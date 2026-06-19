"""The one integration point between the studio and the ``dmcp`` pipeline.

Every route's real work flows through here (build plan §2: *wrap, don't
rewrite*). In REPLAY the adapter loads a frozen fixture and runs the **real**
deterministic ``evaluate()`` on it — so the scorer the demo shows is the
pipeline's, not a mock. LIVE branches are stubbed for A1 and land in A3.

Scope of v0 (A1): REPLAY for all six stages + the sandbox default-deny gate.
Out of scope: LIVE pipeline calls, Tier-2 judge, pool/distractor editing.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

from dmcp.evaluator import evaluate
from dmcp.spec import TaskSpec, ToolEffectCheckpoint
from dmcp.trace import StepKind, StepStatus, Trace

from .models import (
    CandidateCard,
    CheckpointVerdict,
    GoalOut,
    Leaderboard,
    LeaderboardRow,
    Mode,
    ScoreDone,
    ServerCard,
)
from .replay_store import load_leaderboard, load_showcase


class SandboxViolation(RuntimeError):
    """Raised when the adapter would invoke a tool on a non-sandboxed
    state-changing server. Default-deny (build plan §10, invariant #4)."""


def ensure_sandbox_safe(*, server_id: str, dynamism: str, sandbox: bool) -> None:
    """Gate every would-be tool invocation. Only ``stateful_write`` servers need
    a sandbox; ``static`` / ``live_read`` are always safe to read."""
    if dynamism == "stateful_write" and not sandbox:
        raise SandboxViolation(
            f"refusing to invoke tools on {server_id!r}: stateful_write server is not "
            "flagged sandboxed (default-deny)"
        )


def _live_unsupported(stage: str) -> Any:
    raise NotImplementedError(f"LIVE mode for {stage} lands in A3; use mode=replay")


# ---------------------------------------------------------------------------
# Stage 1 — collect
# ---------------------------------------------------------------------------


def list_servers(mode: Mode = "replay") -> list[ServerCard]:
    if mode == "live":
        _live_unsupported("collect")
    return [ServerCard(**s) for s in load_showcase().servers]


# ---------------------------------------------------------------------------
# Stage 2 — goal + explore
# ---------------------------------------------------------------------------


def generate_goal(mode: Mode = "replay", server_ids: list[str] | None = None) -> GoalOut:
    if mode == "live":
        _live_unsupported("goal")
    return GoalOut(**load_showcase().goal)


def explore_calls(mode: Mode = "replay") -> tuple[list[dict[str, Any]], str]:
    """Return (call events, trace_id) for the reference exploration.

    One event per agent-issued tool call (invariant #7: filter on
    ``call_tool_agent``). The backend streams these over SSE.
    """
    if mode == "live":
        _live_unsupported("explore")
    ref = load_showcase().reference_trace
    calls: list[dict[str, Any]] = []
    for s in ref.steps:
        if s.kind is not StepKind.call_tool_agent:
            continue
        calls.append(
            {
                "idx": len(calls) + 1,
                "server_id": s.server_id,
                "tool_name": s.tool_name,
                "arguments": s.arguments or {},
                "ok": s.status is StepStatus.success,
            }
        )
    return calls, str(ref.trace_id)


# ---------------------------------------------------------------------------
# Stage 3 — distill
# ---------------------------------------------------------------------------


def distill(mode: Mode = "replay", trace_id: str | None = None) -> TaskSpec:
    if mode == "live":
        _live_unsupported("distill")
    return load_showcase().task_spec


# ---------------------------------------------------------------------------
# Stage 4 — score
# ---------------------------------------------------------------------------


def candidates(mode: Mode = "replay") -> list[CandidateCard]:
    if mode == "live":
        _live_unsupported("score")
    fx = load_showcase()
    return [CandidateCard(name=name, note=c["note"]) for name, c in fx.candidates.items()]


def _apply_equiv_overrides(spec: TaskSpec, enabled: set[str] | None) -> TaskSpec:
    """Return a spec copy with each tool_effect's equivalence set filtered to the
    ``enabled`` tool names. Powers the editable-equivalence re-score (Tier-1 only).
    A checkpoint keeps at least one member so it can't become unsatisfiable by UI."""
    if not enabled:
        return spec
    s = copy.deepcopy(spec)
    for cp in s.checkpoints:
        if isinstance(cp, ToolEffectCheckpoint) and len(cp.equivalence_set) > 1:
            kept = [r for r in cp.equivalence_set if r.tool_name in enabled]
            if kept:
                cp.equivalence_set = kept
    return s


def candidate_calls(mode: Mode, candidate: str) -> list[dict[str, Any]]:
    fx = load_showcase()
    ctrace: Trace = fx.candidates[candidate]["trace"]
    calls: list[dict[str, Any]] = []
    for s in ctrace.steps:
        if s.kind is not StepKind.call_tool_agent:
            continue
        calls.append(
            {
                "idx": len(calls) + 1,
                "server_id": s.server_id,
                "tool_name": s.tool_name,
                "arguments": s.arguments or {},
                "ok": s.status is StepStatus.success,
            }
        )
    return calls


def score(
    mode: Mode,
    task_id: str | None,
    candidate: str,
    equiv_overrides: set[str] | None = None,
) -> ScoreDone:
    """Run the REAL deterministic evaluator on the frozen candidate trace.

    ``effect_pass`` comes from ``dmcp.evaluator.evaluate``. ``answer_pass`` is the
    studio-side demo foil (the canned answer-match verdict), never from the
    pipeline.
    """
    if mode == "live":
        _live_unsupported("score")
    fx = load_showcase()
    if candidate not in fx.candidates:
        raise KeyError(candidate)
    cand = fx.candidates[candidate]
    ctrace: Trace = cand["trace"]
    spec = _apply_equiv_overrides(fx.task_spec, equiv_overrides)

    ev = evaluate(spec, ctrace, candidate_model=candidate, evaluation_mode="replay")

    verdicts = [
        CheckpointVerdict(
            n=i + 1,
            checkpoint_id=cr.checkpoint_id,
            kind=cr.kind,
            met=cr.passed,
            reason=cr.reason,
        )
        for i, cr in enumerate(ev.checkpoint_results)
    ]
    final_answer = (ctrace.seed_metadata.get("exploration") or {}).get("final_message") or ""
    return ScoreDone(
        effect_pass=ev.passed,
        answer_pass=bool(cand["answer_looks_right"]),  # demo foil, not a benchmark verdict
        final_answer=final_answer,
        met_count=sum(1 for v in verdicts if v.met),
        required=len(verdicts),
        checkpoints=verdicts,
    )


# ---------------------------------------------------------------------------
# Leaderboard peek
# ---------------------------------------------------------------------------


def leaderboard(mode: Mode = "replay") -> Leaderboard:
    raw = load_leaderboard()
    return Leaderboard(
        placeholder=bool(raw.get("_placeholder")),
        note=raw.get("_note"),
        rows=[LeaderboardRow(**r) for r in raw["rows"]],
    )


def equivalence_tools(spec: TaskSpec) -> dict[str, list[str]]:
    """checkpoint_id -> tool names, for tool_effect checkpoints with >1 member
    (the editable equivalence sets the UI exposes)."""
    out: dict[str, list[str]] = {}
    for cp in spec.checkpoints:
        if isinstance(cp, ToolEffectCheckpoint) and len(cp.equivalence_set) > 1:
            out[cp.checkpoint_id] = [r.tool_name for r in cp.equivalence_set]
    return out


def iter_with_index(items: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield from items
