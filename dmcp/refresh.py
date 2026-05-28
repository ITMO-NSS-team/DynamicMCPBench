"""Refresh / decay protocol (Phase 4B of the rev. 3 plan).

For each TaskSpec, take its source reference trace, re-execute the successful
tool calls against the LIVE servers in the manifest, and classify each call:

  identical  — live result text equals the reference's, byte-for-byte.
  drifted    — live result text differs but the call still succeeded.
                Expected for live_read servers (weather, prices, time).
                A drift on a static server is a real schema/behavior change.
  broken     — live call failed (tool error, schema mismatch, server gone).
                The cached checkpoint for this call may no longer be
                achievable; the spec is a candidate for retirement.
  skipped    — server is stateful_write and not opted in. Re-running a write
                tool would either fail (duplicate side effect) or pollute
                state, neither of which is a useful drift signal.

The output is a `RefreshReport` per spec plus an aggregate decay summary.
Concrete answer to AGB's static-cache staleness: we measure decay rather
than freeze the world.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dmcp.manifest import Dynamism, Manifest
from dmcp.recorder import TraceRecorder
from dmcp.trace import StepKind, StepStatus, Trace

REFRESH_VERSION = "0.1.0"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _result_text(result: dict[str, Any] | None) -> str:
    """Pull the LLM-visible text out of an MCP CallToolResult."""
    if result is None:
        return ""
    parts: list[str] = []
    for c in result.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts) if parts else json.dumps(result, default=str)


class CallRefreshOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_step_id: int
    server_id: str
    tool_name: str
    arguments_canonical: str
    classification: str  # identical | drifted | broken | skipped
    reason: str
    reference_text_len: int = 0
    live_text_len: int = 0
    reference_text_sample: str | None = None
    live_text_sample: str | None = None


class RefreshReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "0.1.0"
    refresh_version: str = REFRESH_VERSION
    task_id: UUID
    source_trace_id: UUID
    refreshed_at: datetime = Field(default_factory=_utcnow)
    call_outcomes: list[CallRefreshOutcome]
    counts: dict[str, int]
    spec_likely_stale: bool

    def to_jsonl(self) -> str:
        return self.model_dump_json(exclude_none=False)


async def refresh_one(
    *,
    reference: Trace,
    task_id: UUID,
    manifest: Manifest,
    refresh_stateful: bool = False,
    sample_chars: int = 240,
) -> RefreshReport:
    """Re-execute one reference trace's successful tool calls against live."""
    calls_to_run = [
        s
        for s in reference.steps
        if s.kind is StepKind.call_tool_agent
        and s.status is StepStatus.success
        and s.tool_name is not None
    ]
    # Group by server so we open one session per server.
    server_ids = sorted({s.server_id for s in calls_to_run})
    outcomes: list[CallRefreshOutcome] = []

    servers_for_run: list[str] = []
    skipped_servers: set[str] = set()
    for sid in server_ids:
        try:
            entry = manifest.by_id(sid)
        except KeyError:
            skipped_servers.add(sid)
            continue
        if entry.dynamism is Dynamism.stateful_write and not refresh_stateful:
            skipped_servers.add(sid)
            continue
        servers_for_run.append(sid)

    # Pre-record skipped calls
    for s in calls_to_run:
        if s.server_id in skipped_servers:
            outcomes.append(
                CallRefreshOutcome(
                    reference_step_id=s.step_id,
                    server_id=s.server_id,
                    tool_name=s.tool_name or "",
                    arguments_canonical=s.arguments_canonical or "{}",
                    classification="skipped",
                    reason=(
                        f"server {s.server_id} is stateful_write "
                        "(pass --refresh-stateful to override)"
                    ),
                )
            )

    if servers_for_run:
        configs = manifest.configs(servers_for_run)
        async with TraceRecorder(servers=configs, goal=f"refresh:{task_id}") as recorder:
            for s in calls_to_run:
                if s.server_id in skipped_servers:
                    continue
                try:
                    live_result = await recorder.call_tool(
                        s.server_id, s.tool_name or "", s.arguments or {}
                    )
                except Exception as e:
                    outcomes.append(
                        CallRefreshOutcome(
                            reference_step_id=s.step_id,
                            server_id=s.server_id,
                            tool_name=s.tool_name or "",
                            arguments_canonical=s.arguments_canonical or "{}",
                            classification="broken",
                            reason=f"live call raised {type(e).__name__}: {e}",
                        )
                    )
                    continue

                live_text = _result_text(live_result)
                ref_text = _result_text(s.result)
                is_error = bool(live_result.get("isError"))
                if is_error:
                    outcomes.append(
                        CallRefreshOutcome(
                            reference_step_id=s.step_id,
                            server_id=s.server_id,
                            tool_name=s.tool_name or "",
                            arguments_canonical=s.arguments_canonical or "{}",
                            classification="broken",
                            reason="live call returned isError=true",
                            reference_text_len=len(ref_text),
                            live_text_len=len(live_text),
                            reference_text_sample=ref_text[:sample_chars],
                            live_text_sample=live_text[:sample_chars],
                        )
                    )
                    continue

                classification = "identical" if live_text == ref_text else "drifted"
                outcomes.append(
                    CallRefreshOutcome(
                        reference_step_id=s.step_id,
                        server_id=s.server_id,
                        tool_name=s.tool_name or "",
                        arguments_canonical=s.arguments_canonical or "{}",
                        classification=classification,
                        reason=(
                            "byte-equal"
                            if classification == "identical"
                            else (
                                f"text differs (ref={len(ref_text)}ch, live={len(live_text)}ch)"
                            )
                        ),
                        reference_text_len=len(ref_text),
                        live_text_len=len(live_text),
                        reference_text_sample=(
                            ref_text[:sample_chars] if classification == "drifted" else None
                        ),
                        live_text_sample=(
                            live_text[:sample_chars] if classification == "drifted" else None
                        ),
                    )
                )

    counts = {
        "identical": sum(1 for o in outcomes if o.classification == "identical"),
        "drifted": sum(1 for o in outcomes if o.classification == "drifted"),
        "broken": sum(1 for o in outcomes if o.classification == "broken"),
        "skipped": sum(1 for o in outcomes if o.classification == "skipped"),
        "total": len(outcomes),
    }
    # Heuristic: a spec is likely stale if any reference call breaks (vs just
    # drifts — drift is expected on live_read servers).
    spec_likely_stale = counts["broken"] > 0

    return RefreshReport(
        task_id=task_id,
        source_trace_id=reference.trace_id,
        call_outcomes=outcomes,
        counts=counts,
        spec_likely_stale=spec_likely_stale,
    )


def decay_summary(reports: Iterable[RefreshReport]) -> dict[str, Any]:
    """Aggregate one or more RefreshReports into a decay summary dict."""
    n = total_calls = identical = drifted = broken = skipped = stale = 0
    for r in reports:
        n += 1
        c = r.counts
        total_calls += c["total"]
        identical += c["identical"]
        drifted += c["drifted"]
        broken += c["broken"]
        skipped += c["skipped"]
        if r.spec_likely_stale:
            stale += 1
    return {
        "specs_refreshed": n,
        "specs_stale": stale,
        "stale_rate": (stale / n) if n else 0.0,
        "call_outcomes": {
            "total": total_calls,
            "identical": identical,
            "drifted": drifted,
            "broken": broken,
            "skipped": skipped,
        },
    }
