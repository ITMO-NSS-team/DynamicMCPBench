"""Refresh / decay protocol (Phase 4B of the rev. 3 plan).

For each TaskSpec, take its source reference trace, re-execute the successful
tool calls against the LIVE servers in the manifest, and classify each call:

  identical  — live result text equals the reference's, byte-for-byte.
  drifted    — live result text differs but the call still succeeded.
                Expected for live_read servers (weather, prices, time).
                A drift on a static server is a real schema/behavior change.
  schema_drift — the call failed and discovery shows why: the tool is gone, or
                its input schema no longer admits the reference arguments.
  state_decay — the call failed, discovery is intact and the schema still
                admits the call, but the server says the record it needs is
                gone. The cached checkpoint may no longer be achievable.
  unresolved — the call failed and we cannot say whose fault that is: a
                transient error that outlived its retries, or a server we could
                not even reach for discovery. Excluded from the decay rates and
                left for the next refresh window to decide.
  skipped    — server is stateful_write and not opted in. Re-running a write
                tool would either fail (duplicate side effect) or pollute
                state, neither of which is a useful drift signal.
  quarantined — the task's own environment failed preflight (a fixture file,
                sandbox relation, credential or write target is missing), so no
                live call was made. Nothing is claimed about the server.
  broken     — the pre-0.4.0 umbrella label for any failed call. Never emitted
                now; retained so reports written by older runs still load and
                still count as an attributable failure.

Transient failures (timeouts, dropped connections, 429, recoverable 5xx — see
`dmcp.attribution`) are retried with exponential backoff, whether they were
raised or returned as `isError`; a non-transient error is not retried, because
retrying it only delays the same answer. Attribution then runs off the one
`list_tools` call we make on a server that failed. Per-server drift rate across
many refresh runs is exposed via `per_server_decay`, which `dmcp.report` renders
as the paper's decay table.

Before any of that, `dmcp.preflight` confirms the preconditions the reference
trace assumes. A spec whose environment is broken would otherwise be scored as
a decayed server and then, once readmitted, as a failure of every agent that
attempts it; quarantining keeps our own missing fixtures out of both numbers.
Quarantined reports are excluded from the decay aggregates entirely.

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

from dmcp.attribution import attribute_failure, is_transient_error, is_transient_text
from dmcp.manifest import Dynamism, Manifest
from dmcp.preflight import (
    PreflightResult,
    check_requirements,
    derive_requirements,
    discover_tables,
)
from dmcp.recorder import TraceRecorder
from dmcp.trace import StepKind, StepStatus, Trace

# 0.3.0 adds the `quarantined` classification, the preflight block on
# RefreshReport, and the quarantine counts in the decay aggregates.
# 0.4.0 splits `broken` into schema_drift / state_decay / unresolved, retries
# transient `isError` bodies as well as transient exceptions, and keeps
# unresolved calls out of the decay rates.
REFRESH_VERSION = "0.4.0"

# Classifications that count as a live, attributable call outcome. `broken` is
# the pre-0.4.0 umbrella label, kept so older reports still aggregate.
ATTRIBUTABLE_FAILURES = ("broken", "schema_drift", "state_decay")
LIVE_CLASSIFICATIONS = ("identical", "drifted", *ATTRIBUTABLE_FAILURES)
ALL_CLASSIFICATIONS = (*LIVE_CLASSIFICATIONS, "unresolved", "skipped", "quarantined")

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
    # identical | drifted | schema_drift | state_decay | unresolved | skipped |
    # quarantined  (plus `broken`, only in reports written before 0.4.0)
    classification: str
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
    schema_version: str = "0.3.0"
    refresh_version: str = REFRESH_VERSION
    task_id: UUID
    source_trace_id: UUID
    refreshed_at: datetime = Field(default_factory=_utcnow)
    call_outcomes: list[CallRefreshOutcome]
    counts: dict[str, int]
    spec_likely_stale: bool
    # Set when preflight found an unmet precondition: the task was not
    # re-executed, so this report is evidence about our environment, not about
    # the server. `decay_summary` and `per_server_decay` skip these.
    quarantined: bool = False
    preflight: PreflightResult | None = None

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
) -> tuple[dict[str, Any] | None, Exception | None, int, bool]:
    """Call a tool, retrying with exponential backoff while the failure is transient.

    Returns (result, last_exception, retries_consumed, transient). A transient
    failure is one `dmcp.attribution` recognises as retryable — a timeout, a
    dropped connection, 429, a recoverable 5xx — whether it was raised or
    returned as an `isError` body; both are retried, because a server that wraps
    HTTP reports its rate limit the second way. Anything else is returned on the
    first attempt: retrying a schema error only delays the same answer.

    `transient` is True when the *final* failure was still a transient one, i.e.
    the retries were exhausted rather than the verdict being real. The caller
    carries that case to the next refresh window instead of calling it decay.
    """
    last_exc: Exception | None = None
    last_result: dict[str, Any] | None = None
    attempts = max(0, transient_retries) + 1
    for i in range(attempts):
        try:
            result = await recorder.call_tool(server_id, tool_name, arguments)
        except Exception as e:
            last_exc, last_result = e, None
            if not is_transient_error(e):
                return None, e, i, False
        else:
            last_exc, last_result = None, result
            transient_body = bool(result.get("isError")) and is_transient_text(_result_text(result))
            if not transient_body:
                return result, None, i, False
        if i + 1 >= attempts:
            break
        await sleep(initial_backoff_s * (2**i))
    return last_result, last_exc, max(0, attempts - 1), True


async def refresh_one(
    *,
    reference: Trace,
    task_id: UUID,
    manifest: Manifest,
    refresh_stateful: bool = False,
    sample_chars: int = 240,
    transient_retries: int = DEFAULT_TRANSIENT_RETRIES,
    initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S,
    preflight: bool = True,
    table_inventory: dict[str, set[str]] | None = None,
    recorder: Any = None,
    sleep: Any = asyncio.sleep,
) -> RefreshReport:
    """Re-execute one reference trace's successful tool calls against live.

    Preflight runs first (disable with `preflight=False`). If it finds an unmet
    precondition the task is quarantined: no live call is made, every reference
    call is recorded as `quarantined`, and the report is excluded from the decay
    aggregates rather than counted as a broken server.
    """
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

    # One discovery call per server that actually failed, memoised: attribution
    # needs the live tool list, and a healthy sweep should not pay for it.
    tool_listings: dict[str, tuple[list[Any] | None, str]] = {}

    async def _live_tools(rec: Any, sid: str) -> tuple[list[Any] | None, str]:
        if sid not in tool_listings:
            try:
                tool_listings[sid] = (list(await rec.list_tools(sid)), "")
            except Exception as e:
                tool_listings[sid] = (None, f"{type(e).__name__}: {e}")
        return tool_listings[sid]

    async def _drive(rec: Any) -> None:
        for s in calls_to_run:
            if s.server_id in skipped_servers:
                continue
            live_result, exc, retries, transient = await _call_with_backoff(
                rec,
                s.server_id,
                s.tool_name or "",
                s.arguments or {},
                transient_retries=transient_retries,
                initial_backoff_s=initial_backoff_s,
                sleep=sleep,
            )
            ref_text = _result_text(s.result)
            failed = exc is not None or (live_result is not None and bool(live_result.get("isError")))
            if failed:
                live_text = _result_text(live_result) if live_result is not None else ""
                error_text = f"{type(exc).__name__}: {exc}" if exc is not None else live_text
                suffix = f" (after {retries} retr{'y' if retries == 1 else 'ies'})" if retries else ""
                if transient:
                    # Retries ran out on a retryable error. Deciding decay here
                    # would let a bad afternoon on the network look like a dead
                    # server; the next window gets to decide instead.
                    classification = "unresolved"
                    reason = f"transient failure survived its retries{suffix}, deferred: {error_text}"
                else:
                    live_tools, discovery_error = await _live_tools(rec, s.server_id)
                    classification, reason = attribute_failure(
                        tool_name=s.tool_name or "",
                        arguments=s.arguments or {},
                        error_text=error_text,
                        live_tools=live_tools,
                        discovery_error=discovery_error,
                    )
                    reason = f"{reason}{suffix}"
                outcomes.append(
                    CallRefreshOutcome(
                        reference_step_id=s.step_id,
                        server_id=s.server_id,
                        tool_name=s.tool_name or "",
                        arguments_canonical=s.arguments_canonical or "{}",
                        classification=classification,
                        reason=reason,
                        reference_text_len=len(ref_text),
                        live_text_len=len(live_text),
                        reference_text_sample=ref_text[:sample_chars],
                        live_text_sample=live_text[:sample_chars] or None,
                        retry_count=retries,
                    )
                )
                continue

            assert live_result is not None
            live_text = _result_text(live_result)
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

    requirements = derive_requirements(reference, manifest) if preflight else []
    preflight_result: PreflightResult | None = None

    async def _preflight_then_drive(rec: Any) -> None:
        nonlocal preflight_result
        if requirements:
            inventory = table_inventory
            if inventory is None and any(r.kind == "table" for r in requirements):
                inventory = await discover_tables(rec, servers_for_run)
            preflight_result = check_requirements(requirements, table_inventory=inventory)
            if not preflight_result.ok:
                return  # quarantine: touch nothing live
        await _drive(rec)

    if servers_for_run:
        if recorder is not None:
            await _preflight_then_drive(recorder)
        else:
            configs = manifest.configs(servers_for_run)
            async with TraceRecorder(servers=configs, goal=f"refresh:{task_id}") as rec:
                await _preflight_then_drive(rec)
    elif requirements:
        # Every server was skipped, so there is no session to probe with; the
        # local checks still decide whether this task's environment is intact.
        preflight_result = check_requirements(requirements, table_inventory=table_inventory)

    quarantined = preflight_result is not None and not preflight_result.ok
    if quarantined:
        assert preflight_result is not None
        reason = preflight_result.summary()
        # Replace everything, including the pre-recorded `skipped` outcomes: this
        # spec contributed no evidence about any server it touches.
        outcomes = [
            CallRefreshOutcome(
                reference_step_id=s.step_id,
                server_id=s.server_id,
                tool_name=s.tool_name or "",
                arguments_canonical=s.arguments_canonical or "{}",
                classification="quarantined",
                reason=reason,
            )
            for s in calls_to_run
        ]

    counts = {c: sum(1 for o in outcomes if o.classification == c) for c in ALL_CLASSIFICATIONS}
    counts["total"] = len(outcomes)
    # Heuristic: a spec is likely stale if any reference call failed in a way we
    # could pin on the server (vs just drifting — drift is expected on live_read
    # servers). An unresolved call does not make a spec stale: we could not tell
    # whose failure it was, and a quarantined spec never ran at all.
    spec_likely_stale = any(counts[c] > 0 for c in ATTRIBUTABLE_FAILURES)

    return RefreshReport(
        task_id=task_id,
        source_trace_id=reference.trace_id,
        call_outcomes=outcomes,
        counts=counts,
        spec_likely_stale=spec_likely_stale,
        quarantined=quarantined,
        preflight=preflight_result,
    )


def decay_summary(reports: Iterable[RefreshReport]) -> dict[str, Any]:
    """Aggregate one or more RefreshReports into a decay summary dict.

    Quarantined reports are counted, then excluded from every decay figure:
    they measured our environment, not the substrate, and folding them in would
    inflate exactly the number the refresh protocol exists to report honestly.
    """
    reports = list(reports)
    quarantined = sum(1 for r in reports if r.quarantined)
    n = stale = 0
    call_outcomes = dict.fromkeys(("total", *ALL_CLASSIFICATIONS), 0)
    for r in reports:
        if r.quarantined:
            continue
        n += 1
        for key in call_outcomes:
            call_outcomes[key] += r.counts.get(key, 0)
        if r.spec_likely_stale:
            stale += 1
    return {
        "specs_refreshed": n,
        "specs_quarantined": quarantined,
        "specs_stale": stale,
        "stale_rate": (stale / n) if n else 0.0,
        "call_outcomes": call_outcomes,
        "per_server": per_server_decay(reports),
    }


def per_server_decay(reports: Iterable[RefreshReport]) -> dict[str, dict[str, Any]]:
    """Per-server drift rate aggregated across one or more refresh runs.

    `refreshes` counts the distinct RefreshReports that touched the server
    (one per spec-refresh). `total` includes every outcome; the rates are taken
    over `live` only, which is how the decay table should be read:

        live = identical + drifted + schema_drift + state_decay (+ legacy broken)
        drift_rate = drifted / live,  broken_rate = attributable failures / live

    Skipped, quarantined and **unresolved** calls are outside `live`. Unresolved
    is the E9.12 addition: a failure we could not pin on the server (a transient
    error that outlived its retries, or a server we could not reach for
    discovery) is reported as its own count rather than folded into decay.

    Quarantined reports are skipped entirely: a task blocked by its own missing
    fixtures made no live call, so it is not evidence for or against any server.
    """
    by_server: dict[str, dict[str, Any]] = {}
    for r in reports:
        if r.quarantined:
            continue
        seen: set[str] = set()
        for o in r.call_outcomes:
            bucket = by_server.setdefault(
                o.server_id,
                {
                    "refreshes": 0,
                    "total": 0,
                    **dict.fromkeys(ALL_CLASSIFICATIONS, 0),
                    "retries": 0,
                    "first_seen": r.refreshed_at,
                    "last_seen": r.refreshed_at,
                },
            )
            if o.server_id not in seen:
                bucket["refreshes"] += 1
                seen.add(o.server_id)
            bucket["total"] += 1
            # An unknown label from a future version must not vanish silently.
            bucket[o.classification] = bucket.get(o.classification, 0) + 1
            bucket["retries"] += o.retry_count
            if r.refreshed_at < bucket["first_seen"]:
                bucket["first_seen"] = r.refreshed_at
            if r.refreshed_at > bucket["last_seen"]:
                bucket["last_seen"] = r.refreshed_at
    for b in by_server.values():
        failed = sum(b[c] for c in ATTRIBUTABLE_FAILURES)
        live = b["identical"] + b["drifted"] + failed
        b["live_calls"] = live
        b["failed_calls"] = failed
        b["drift_rate"] = (b["drifted"] / live) if live else 0.0
        b["broken_rate"] = (failed / live) if live else 0.0
        b["identical_rate"] = (b["identical"] / live) if live else 0.0
        b["schema_drift_rate"] = (b["schema_drift"] / live) if live else 0.0
        b["state_decay_rate"] = (b["state_decay"] / live) if live else 0.0
        # Out of `live` by construction, so report it against everything we
        # attempted: it is a measure of our own visibility, not of the server.
        attempted = live + b["unresolved"]
        b["unresolved_rate"] = (b["unresolved"] / attempted) if attempted else 0.0
    return by_server
