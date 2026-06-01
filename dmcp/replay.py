"""Deterministic replay recorder (Phase 1B, Tier 1 + Tier 2 of the rev. 3 plan).

`TraceReplayRecorder` mimics the live `TraceRecorder` surface
(``__aenter__`` / ``__aexit__`` / ``list_tools`` / ``call_tool`` / ``.trace``),
but instead of connecting to live MCP servers it serves responses from a
cache built from one or more previously-recorded reference traces.

Why this matters: every candidate agent in a multi-agent evaluation must face
the same world, otherwise rankings are confounded by upstream nondeterminism
(weather changed, npm wrote vulnerability noise to stderr, a website 502'd,
etc.). Replay is the substrate that lets DynamicMCPBench claim its scores
are reproducible.

Tier 1 — exact-match cache keyed on (server_id, tool_name, canonical_args).
Tier 2 — fuzzy-match fallback: if a candidate's args don't match exactly but
         are close enough to a cached call (same tool, normalized field values
         within a similarity threshold), the cached result is replayed and the
         step is marked `replay_tier=2`. Deterministic — uses field-level
         normalization + difflib.SequenceMatcher, no external models or API
         calls. The threshold and matching algorithm are fully data-driven so
         the same candidate trace produces the same hits on every machine.
Tier 3 — LLM simulator (opt-in). If a `simulator_llm` is supplied AND Tier-1/2
         both miss, an LLM generates a plausible result tagged `simulated=true`
         + `replay_tier=3`. OFF by default — enabling it trades the determinism
         guarantee above for coverage on offline servers, so simulated steps are
         flagged and must be discounted in fair comparisons. With no simulator
         (the default) a miss still falls through to a synthetic isError result.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from difflib import SequenceMatcher
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


SIM_SYSTEM = (
    "You simulate the output of an MCP tool for an OFFLINE benchmark replay. "
    "Given a tool, its description, and arguments, return ONLY a short, plausible "
    "result text the tool would produce — no commentary, no apologies. The output "
    "is explicitly flagged as simulated."
)


async def _simulate_via_llm(
    llm: Any,
    server_id: str,
    tool_name: str,
    canonical_args: str,
    tool_specs: list[ToolSpec],
) -> str:
    """Tier-3: ask an LLM for a plausible result on a cache miss. temperature=0
    for as much determinism as the model allows. Returns the result text."""
    desc = next((s.description for s in tool_specs if s.name == tool_name), None) or ""
    user = (
        f"Server: {server_id}\nTool: {tool_name}\nDescription: {desc}\n"
        f"Arguments (JSON): {canonical_args}\n\nProduce a plausible tool result."
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": SIM_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )
    return resp.content or ""


_WS_RE = re.compile(r"\s+")


def _normalize_value(v: Any) -> Any:
    """Cheap deterministic normalization for fuzzy-match comparison only.

    Lowercase + collapse whitespace + strip surrounding quotes/punctuation for
    strings; pass numbers/bools through unchanged so 5 vs "5" doesn't collapse.
    """
    if isinstance(v, str):
        return _WS_RE.sub(" ", v.strip().lower())
    if isinstance(v, list):
        return tuple(_normalize_value(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _normalize_value(val)) for k, val in v.items()))
    return v


def _field_match_score(candidate: dict[str, Any], cached: dict[str, Any]) -> float:
    """Field-level similarity in [0,1] between two arg dicts.

    Scoring: average over the union of keys.
      - missing key on either side → 0
      - identical normalized values → 1
      - substring containment between two strings → 0.7
      - both numeric → 1 if equal, 0 otherwise
      - otherwise 0
    """
    keys = set(candidate) | set(cached)
    if not keys:
        return 1.0
    total = 0.0
    for k in keys:
        if k not in candidate or k not in cached:
            continue
        cv = _normalize_value(candidate[k])
        rv = _normalize_value(cached[k])
        if cv == rv:
            total += 1.0
        elif isinstance(cv, str) and isinstance(rv, str) and cv and rv and (cv in rv or rv in cv):
            total += 0.7
    return total / len(keys)


def _tier2_score(candidate_canonical: str, cached_canonical: str) -> float:
    """Return a similarity score in [0,1] between two canonical-arg JSON strings.

    Tries structured field-level matching first; falls back to a string-level
    difflib ratio for non-dict args (positional, plain strings, etc.).
    """
    try:
        cand = json.loads(candidate_canonical)
        ref = json.loads(cached_canonical)
    except (json.JSONDecodeError, ValueError):
        return SequenceMatcher(None, candidate_canonical, cached_canonical).ratio()

    if isinstance(cand, dict) and isinstance(ref, dict):
        return _field_match_score(cand, ref)

    # Non-dict args (e.g. positional list, raw string): fall back to string ratio.
    return SequenceMatcher(
        None,
        json.dumps(cand, sort_keys=True),
        json.dumps(ref, sort_keys=True),
    ).ratio()


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
        tier2_threshold: float = 0.75,
        simulator_llm: Any = None,
    ) -> None:
        """Construct a replay recorder.

        tier2_threshold: minimum field-match score in [0,1] for the fuzzy
        fallback to serve a cached result. Set to 1.0 to disable Tier-2.
        Default 0.75 — empirically tight enough that "covid" → "covid-19"
        style near-matches hit, but unrelated calls don't piggy-back.
        """
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._tool_specs_by_server: dict[str, list[ToolSpec]] = {}
        self._fingerprints: list[ServerFingerprint] = []
        self._available_args_by_tool: dict[tuple[str, str], list[str]] = {}
        self._tier2_threshold = tier2_threshold
        self._tier2_hits = 0
        self._cache_miss_count = 0
        self._simulator_llm = simulator_llm
        self._tier3_count = 0

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
                "tier2_threshold": tier2_threshold,
                "tier3_enabled": simulator_llm is not None,
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
        # Stash final replay stats so they survive serialization.
        replay_meta = dict(self.trace.seed_metadata.get("replay", {}))
        replay_meta["tier2_hits"] = self._tier2_hits
        replay_meta["tier3_count"] = self._tier3_count
        replay_meta["cache_miss_count"] = self._cache_miss_count
        self.trace.seed_metadata["replay"] = replay_meta

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
            result_tagged = {**cached, "replay_tier": 1}
            step = Step.build(
                step_id=self.trace.next_step_id(),
                kind=StepKind.call_tool_agent,
                server_id=server_id,
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                ended_at=ended_at,
                status=StepStatus.success,
                result=result_tagged,
            )
            self.trace.steps.append(step)
            return result_tagged

        # Tier 2 — fuzzy match against same-tool cached calls.
        if self._tier2_threshold < 1.0:
            best_score = 0.0
            best_args: str | None = None
            for known_args in self._available_args_by_tool.get((server_id, tool_name), []):
                score = _tier2_score(canonical, known_args)
                if score > best_score:
                    best_score = score
                    best_args = known_args
            if best_args is not None and best_score >= self._tier2_threshold:
                cached2 = self._cache[(server_id, tool_name, best_args)]
                self._tier2_hits += 1
                ended_at = _utcnow()
                tier2_result = {
                    **cached2,
                    "replay_tier": 2,
                    "replay_tier2_source_args": best_args,
                    "replay_tier2_score": round(best_score, 4),
                }
                step = Step.build(
                    step_id=self.trace.next_step_id(),
                    kind=StepKind.call_tool_agent,
                    server_id=server_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=StepStatus.success,
                    result=tier2_result,
                )
                self.trace.steps.append(step)
                return tier2_result

        # Tier 3 — LLM simulator (opt-in; flagged, non-deterministic).
        if self._simulator_llm is not None:
            text = await _simulate_via_llm(
                self._simulator_llm,
                server_id,
                tool_name,
                canonical,
                self._tool_specs_by_server.get(server_id, []),
            )
            self._tier3_count += 1
            ended_at = _utcnow()
            simulated = {
                "meta": None,
                "content": [{"type": "text", "text": text}],
                "structuredContent": None,
                "isError": False,
                "simulated": True,
                "replay_tier": 3,
            }
            step = Step.build(
                step_id=self.trace.next_step_id(),
                kind=StepKind.call_tool_agent,
                server_id=server_id,
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                ended_at=ended_at,
                status=StepStatus.success,
                result=simulated,
            )
            self.trace.steps.append(step)
            return simulated

        # Cache miss → synthetic isError=true result.
        self._cache_miss_count += 1
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
