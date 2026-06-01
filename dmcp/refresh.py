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

Live calls are retried with exponential backoff before being classified as
broken (transient network flakes shouldn't pollute the decay signal). Per-
server drift rate across many refresh runs is exposed via `per_server_decay`,
which `dmcp.report` renders as the paper's decay table.

The output is a `RefreshReport` per spec plus an aggregate decay summary.
Concrete answer to AGB's static-cache staleness: we measure decay rather
than freeze the world.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dmcp.manifest import Dynamism, Manifest
from dmcp.recorder import TraceRecorder
from dmcp.trace import StepKind, StepStatus, Trace

REFRESH_VERSION = "0.2.0"

DEFAULT_TRANSIENT_RETRIES = 2
DEFAULT_INITIAL_BACKOFF_S = 0.5


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
    # Number of retries actually consumed before this outcome was recorded
    # (0 means the first attempt produced this result). Surfaces transient
    # flakiness in the decay table even when retries eventually succeed.
    retry_count: int = 0


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


async def _call_with_backoff(
    recorder: TraceRecorder | Any,
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    transient_retries: int,
    initial_backoff_s: float,
    sleep: Any = asyncio.sleep,
) -> tuple[dict[str, Any] | None, Exception | None, int]:
    """Call a tool with exponential-backoff retry on exceptions.

    Returns (result, last_exception, retries_consumed). When the call eventually
    succeeds the exception is None; when it never does, `result` is None and
    `last_exception` holds the final error. Retries fire only on raised
    exceptions (treated as transient flakes); a tool that returns isError=true
    is a real server response and is not retried.
    """
    last_exc: Exception | None = None
    attempts = max(0, transient_retries) + 1
    for i in range(attempts):
        try:
            result = await recorder.call_tool(server_id, tool_name, arguments)
            return result, None, i
        except Exception as e:  # transient network/process flake → back off
            last_exc = e
            if i + 1 >= attempts:
                break
            await sleep(initial_backoff_s * (2**i))
    return None, last_exc, max(0, attempts - 1)


async def refresh_one(
    *,
    reference: Trace,
    task_id: UUID,
    manifest: Manifest,
    refresh_stateful: bool = False,
    sample_chars: int = 240,
    transient_retries: int = DEFAULT_TRANSIENT_RETRIES,
    initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S,
    recorder: Any = None,
    sleep: Any = asyncio.sleep,
) -> RefreshReport:
    """Re-execute one reference trace's successful tool calls against live."""
    calls_to_run = [
        s
        for s in reference.steps
        if s.kind is StepKind.call_tool_agent and s.status is StepStatus.success and s.tool_name is not None
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
                    reason=(f"server {s.server_id} is stateful_write (pass --refresh-stateful to override)"),
                )
            )

    async def _drive(rec: Any) -> None:
        for s in calls_to_run:
            if s.server_id in skipped_servers:
                continue
            live_result, exc, retries = await _call_with_backoff(
                rec,
                s.server_id,
                s.tool_name or "",
                s.arguments or {},
                transient_retries=transient_retries,
                initial_backoff_s=initial_backoff_s,
                sleep=sleep,
            )
            if exc is not None:
                outcomes.append(
                    CallRefreshOutcome(
                        reference_step_id=s.step_id,
                        server_id=s.server_id,
                        tool_name=s.tool_name or "",
                        arguments_canonical=s.arguments_canonical or "{}",
                        classification="broken",
                        reason=(
                            f"live call raised {type(exc).__name__}: {exc} "
                            f"(after {retries} retr{'y' if retries == 1 else 'ies'})"
                            if retries
                            else f"live call raised {type(exc).__name__}: {exc}"
                        ),
                        retry_count=retries,
                    )
                )
                continue

            assert live_result is not None
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
                        retry_count=retries,
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
                        else (f"text differs (ref={len(ref_text)}ch, live={len(live_text)}ch)")
                    ),
                    reference_text_len=len(ref_text),
                    live_text_len=len(live_text),
                    reference_text_sample=(ref_text[:sample_chars] if classification == "drifted" else None),
                    live_text_sample=(live_text[:sample_chars] if classification == "drifted" else None),
                    retry_count=retries,
                )
            )

    if servers_for_run:
        if recorder is not None:
            await _drive(recorder)
        else:
            configs = manifest.configs(servers_for_run)
            async with TraceRecorder(servers=configs, goal=f"refresh:{task_id}") as rec:
                await _drive(rec)

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
    reports = list(reports)
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
        "per_server": per_server_decay(reports),
    }


def per_server_decay(reports: Iterable[RefreshReport]) -> dict[str, dict[str, Any]]:
    """Per-server drift rate aggregated across one or more refresh runs.

    `refreshes` counts the distinct RefreshReports that touched the server
    (one per spec-refresh). `total` includes skipped; the rates exclude it,
    matching how the decay table should be read: drift_rate = drifted / live
    where live = identical + drifted + broken.
    """
    by_server: dict[str, dict[str, Any]] = {}
    for r in reports:
        seen: set[str] = set()
        for o in r.call_outcomes:
            bucket = by_server.setdefault(
                o.server_id,
                {
                    "refreshes": 0,
                    "total": 0,
                    "identical": 0,
                    "drifted": 0,
                    "broken": 0,
                    "skipped": 0,
                    "retries": 0,
                    "first_seen": r.refreshed_at,
                    "last_seen": r.refreshed_at,
                },
            )
            if o.server_id not in seen:
                bucket["refreshes"] += 1
                seen.add(o.server_id)
            bucket["total"] += 1
            bucket[o.classification] += 1
            bucket["retries"] += o.retry_count
            if r.refreshed_at < bucket["first_seen"]:
                bucket["first_seen"] = r.refreshed_at
            if r.refreshed_at > bucket["last_seen"]:
                bucket["last_seen"] = r.refreshed_at
    for b in by_server.values():
        live = b["identical"] + b["drifted"] + b["broken"]
        b["live_calls"] = live
        b["drift_rate"] = (b["drifted"] / live) if live else 0.0
        b["broken_rate"] = (b["broken"] / live) if live else 0.0
        b["identical_rate"] = (b["identical"] / live) if live else 0.0
    return by_server
