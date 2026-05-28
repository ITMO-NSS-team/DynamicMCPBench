"""Deterministic replay recorder (Phase 1B, Tier 1 of the rev. 3 plan).

`TraceReplayRecorder` mimics the live `TraceRecorder` surface
(``__aenter__`` / ``__aexit__`` / ``list_tools`` / ``call_tool`` / ``.trace``),
but instead of connecting to live MCP servers it serves responses from a
cache built from one or more previously-recorded reference traces.

Why this matters: every candidate agent in a multi-agent evaluation must face
the same world, otherwise rankings are confounded by upstream nondeterminism
(weather changed, npm wrote vulnerability noise to stderr, a website 502'd,
etc.). Replay is the substrate that lets DynamicMCPBench claim its scores
are reproducible.

v0 scope (Tier 1 only):
  - Exact-match cache keyed on (server_id, tool_name, canonical_args).
  - On cache miss: returns a synthetic error result. The candidate sees a
    real tool error and may try different arguments. This is the simplest
    correctness-preserving fallback — semantic-cache (Tier 2) and an LLM
    simulator (Tier 3) come later.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dmcp import __version__
from dmcp.trace import (
    ServerFingerprint,
    Step,
    StepError,
    StepKind,
    StepStatus,
    ToolSpec,
    Trace,
    canonicalize_args,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


CACHE_MISS_MESSAGE = (
    "Tool call has no cached result in this evaluation environment. "
    "Try different arguments or a different tool — the world has not changed."
)


class TraceReplayRecorder:
    """Same surface as `TraceRecorder`, backed by cached reference trace(s).

    Cache keys are tuples (server_id, tool_name, canonical_args). When the
    candidate calls a tool with arguments that appeared in a reference trace,
    the cached result is replayed verbatim. Otherwise a synthetic isError=true
    result is returned and recorded with `replay_cache_miss=true` on the step.
    """

    def __init__(
        self,
        cache_traces: Iterable[Trace],
        *,
        goal: str | None = None,
        seed_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._tool_specs_by_server: dict[str, list[ToolSpec]] = {}
        self._fingerprints: list[ServerFingerprint] = []
        self._available_args_by_tool: dict[tuple[str, str], list[str]] = {}

        seen_servers: set[str] = set()
        for ref in cache_traces:
            for step in ref.steps:
                if step.kind is not StepKind.call_tool_agent:
                    continue
                if step.tool_name is None:
                    continue
                if step.status is not StepStatus.success:
                    # Cache only successful calls — replaying an error wouldn't
                    # help downstream agents and would lock-in past failures.
                    continue
                key = (step.server_id, step.tool_name, step.arguments_canonical or "{}")
                if key not in self._cache and step.result is not None:
                    self._cache[key] = step.result
                    self._available_args_by_tool.setdefault(
                        (step.server_id, step.tool_name), []
                    ).append(step.arguments_canonical or "{}")
            # Pick up tool surface + server fingerprints from the first
            # reference that exposes each server.
            for sid, specs in ref.tool_specs.items():
                if sid not in self._tool_specs_by_server:
                    self._tool_specs_by_server[sid] = list(specs)
            for fp in ref.servers:
                if fp.server_id not in seen_servers:
                    self._fingerprints.append(fp)
                    seen_servers.add(fp.server_id)

        meta = {
            "replay": {
                "cache_size": len(self._cache),
                "tool_specs_servers": sorted(self._tool_specs_by_server.keys()),
                "tier": 1,
            }
        }
        if seed_metadata:
            meta.update(seed_metadata)

        self.trace = Trace(
            recorder_version=f"{__version__}+replay",
            goal=goal,
            seed_metadata=meta,
        )

    async def __aenter__(self) -> TraceReplayRecorder:
        for fp in self._fingerprints:
            self.trace.servers.append(fp)
        for sid, specs in self._tool_specs_by_server.items():
            self.trace.tool_specs[sid] = list(specs)
        self.trace.started_at = _utcnow()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.trace.ended_at = _utcnow()

    async def list_tools(self, server_id: str) -> list[ToolSpec]:
        specs = self._tool_specs_by_server.get(server_id, [])
        started_at = _utcnow()
        ended_at = _utcnow()
        self.trace.steps.append(
            Step.build(
                step_id=self.trace.next_step_id(),
                kind=StepKind.list_tools,
                server_id=server_id,
                started_at=started_at,
                ended_at=ended_at,
                status=StepStatus.success,
                result={"tools": [s.model_dump(mode="json") for s in specs]},
            )
        )
        return list(specs)

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        canonical = canonicalize_args(arguments)
        key = (server_id, tool_name, canonical)
        started_at = _utcnow()

        cached = self._cache.get(key)
        if cached is not None:
            ended_at = _utcnow()
            step = Step.build(
                step_id=self.trace.next_step_id(),
                kind=StepKind.call_tool_agent,
                server_id=server_id,
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                ended_at=ended_at,
                status=StepStatus.success,
                result=cached,
            )
            self.trace.steps.append(step)
            return cached

        # Cache miss → synthetic isError=true result.
        hint_lines = self._available_args_by_tool.get((server_id, tool_name), [])
        hint = ""
        if hint_lines:
            preview = "\n".join(f"  - {h}" for h in hint_lines[:5])
            hint = (
                f"\nKnown working argument shapes for {server_id}.{tool_name}:\n{preview}"
            )
        synthetic = {
            "meta": None,
            "content": [{"type": "text", "text": CACHE_MISS_MESSAGE + hint}],
            "structuredContent": None,
            "isError": True,
            "replay_cache_miss": True,
        }
        ended_at = _utcnow()
        step = Step.build(
            step_id=self.trace.next_step_id(),
            kind=StepKind.call_tool_agent,
            server_id=server_id,
            tool_name=tool_name,
            arguments=arguments,
            started_at=started_at,
            ended_at=ended_at,
            status=StepStatus.error,
            result=synthetic,
            error=StepError(
                code="ReplayCacheMiss",
                message=CACHE_MISS_MESSAGE,
                raw={"cache_key": list(key)},
            ),
        )
        self.trace.steps.append(step)
        return synthetic

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(self.trace.to_jsonl())
            f.write("\n")
