"""LIVE mode — wrap the real pipeline for collect / goal / explore / distill.

REPLAY (the default) is served from frozen fixtures by ``dmcp_adapter``. LIVE
drives the real pipeline against read-only MCP servers, as *proof* that the
studio shows the real system. Per the build plan's risk register, **scoring
stays on deterministic replay** (the graded path); LIVE covers stages 1–3.

Everything here is additive and wraps ``dmcp`` (no pipeline code changed). LIVE
makes real network + LLM calls, so it is never exercised by the test gate —
the deterministic plumbing (streaming wrapper, sandbox gate, trace cache) is
tested with fakes; a real run is the opt-in ``scripts/live_smoke.py``.

Scope of v0 (A3): live collect/goal/explore/distill with per-stage timeout and
graceful fallback to the REPLAY fixture. Out of scope: live candidate scoring
(stays replay), bring-your-own-server (A4).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from dmcp.distiller import distill as run_distill
from dmcp.explorer import explore as run_explore
from dmcp.explorer import stash_exploration_in_trace
from dmcp.goal_gen import generate_goals
from dmcp.llm import DEFAULT_MODEL, OpenRouterClient
from dmcp.manifest import Manifest
from dmcp.recorder import TraceRecorder
from dmcp.spec import TaskSpec
from dmcp.trace import StepKind, StepStatus, ToolSpec, Trace

from .dmcp_adapter import ensure_sandbox_safe
from .models import GoalOut, ServerCard

REPO_ROOT = Path(__file__).resolve().parents[2]
# Manifest that backs LIVE mode. Override with DMCP_STUDIO_MANIFEST.
MANIFEST_PATH = Path(os.environ.get("DMCP_STUDIO_MANIFEST", REPO_ROOT / "manifests" / "local.json"))
# Curated read-only servers shown in the studio (the public showcase set).
SHOWCASE_SERVER_IDS = ["yfinance", "arxiv", "wikipedia"]
EXPLORE_BUDGET = 12
STAGE_TIMEOUT_S = 90.0

# Last live trace(s), so /api/distill?mode=live can find what /api/explore made.
# In-process only — fine for a single-session booth demo.
_LIVE_TRACES: dict[str, Trace] = {}


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    return Manifest.load(MANIFEST_PATH)


def _gate(server_ids: list[str], manifest: Manifest) -> None:
    """Default-deny any state-changing server that isn't sandboxed, before we
    open a single connection (build plan §10, invariant #4)."""
    for sid in server_ids:
        e = manifest.by_id(sid)
        ensure_sandbox_safe(server_id=e.server_id, dynamism=e.dynamism.value, sandbox=e.sandbox)


def live_servers() -> list[ServerCard]:
    m = load_manifest()
    cards: list[ServerCard] = []
    for sid in SHOWCASE_SERVER_IDS:
        try:
            e = m.by_id(sid)
        except KeyError:
            continue
        cards.append(
            ServerCard(
                server_id=e.server_id,
                dynamism=e.dynamism.value,
                sandbox=e.sandbox,
                description=e.description or "",
                tools=[],  # tool surface is fetched lazily on explore (avoids opening every server)
            )
        )
    return cards


async def live_goal(server_ids: list[str]) -> GoalOut:
    m = load_manifest()
    ids = [s for s in server_ids if s in {e.server_id for e in m.servers}] or SHOWCASE_SERVER_IDS
    _gate(ids, m)
    llm = OpenRouterClient(model=DEFAULT_MODEL)
    goals = await asyncio.wait_for(
        generate_goals(
            manifest=m,
            server_ids=ids,
            llm=llm,
            single_per_server=1,
            cross_pairs=1,
            use_personas=True,
        ),
        timeout=STAGE_TIMEOUT_S,
    )
    if not goals.entries:
        raise RuntimeError("goal generation produced no goals")
    g = goals.entries[0]
    return GoalOut(goal=g.goal, persona=g.persona)


class StreamingRecorder:
    """Wrap a live ``TraceRecorder`` and push one event per agent tool call onto
    a queue, so the explore stage can stream call-by-call over SSE. Forwards the
    rest of the recorder surface unchanged (wrap, don't patch ``explore()``)."""

    def __init__(self, inner: TraceRecorder, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._inner = inner
        self._queue = queue
        self._idx = 0

    @property
    def trace(self) -> Trace:
        return self._inner.trace

    async def __aenter__(self) -> StreamingRecorder:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *a: Any) -> Any:
        return await self._inner.__aexit__(*a)

    async def list_tools(self, server_id: str) -> list[ToolSpec]:
        return await self._inner.list_tools(server_id)

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        res = await self._inner.call_tool(server_id, tool_name, arguments)
        self._idx += 1
        await self._queue.put(
            {
                "idx": self._idx,
                "server_id": server_id,
                "tool_name": tool_name,
                "arguments": arguments or {},
                "ok": not bool(res.get("isError")),
            }
        )
        return res


def cache_trace(trace: Trace) -> None:
    _LIVE_TRACES[str(trace.trace_id)] = trace


def get_cached_trace(trace_id: str | None) -> Trace:
    if trace_id and trace_id in _LIVE_TRACES:
        return _LIVE_TRACES[trace_id]
    if _LIVE_TRACES:  # fall back to the most recent
        return next(reversed(_LIVE_TRACES.values()))
    raise KeyError("no live trace recorded yet")


async def stream_explore(server_ids: list[str], goal: str, persona: str | None) -> AsyncIterator[dict]:
    """Async-iterate SSE events for a live exploration: one ``call`` per tool
    call, then a ``done`` with the trace id. Raises if the servers can't be
    reached / the run fails *before* completion, so the route can fall back."""
    m = load_manifest()
    _gate(server_ids, m)
    configs = m.configs(server_ids)
    llm = OpenRouterClient(model=DEFAULT_MODEL)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    inner = TraceRecorder(servers=configs, goal=goal)
    rec = StreamingRecorder(inner, queue)

    async def _run() -> Any:
        try:
            result = await run_explore(
                goal=goal, recorder=rec, llm=llm, persona=persona, budget=EXPLORE_BUDGET
            )
            stash_exploration_in_trace(result)
            return result
        finally:
            await queue.put(None)  # always signal end-of-stream

    task: asyncio.Task[Any] = asyncio.create_task(_run())
    try:
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=STAGE_TIMEOUT_S)
            if item is None:
                break
            yield {"event": "call", "data": item}
        result = await task  # re-raises if the exploration failed
    except BaseException:
        task.cancel()
        raise
    trace = result.trace
    cache_trace(trace)
    n = sum(1 for s in trace.steps if s.kind is StepKind.call_tool_agent)
    ok = sum(1 for s in trace.steps if s.kind is StepKind.call_tool_agent and s.status is StepStatus.success)
    yield {
        "event": "done",
        "data": {"trace_id": str(trace.trace_id), "n_calls": n, "success": ok == n and n > 0},
    }


async def live_distill(trace_id: str | None) -> TaskSpec:
    trace = get_cached_trace(trace_id)
    llm = OpenRouterClient(model=DEFAULT_MODEL)
    return await asyncio.wait_for(
        run_distill(trace, llm=llm, manifest=load_manifest()), timeout=STAGE_TIMEOUT_S
    )
