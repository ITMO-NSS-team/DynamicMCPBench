"""Candidate-agent tool-exposure architectures (E8.2 / B2 / G6.3).

Three ways to present the same underlying tool surface to the candidate agent.
Each takes a `tool_surface: dict[server_id, list[ToolSpec]]` plus a prompt and
returns a *filtered or restructured* surface. They are pure functions over the
surface — they don't run the agent — and they are composed *after* the eval
pool is built so they stack cleanly with `--pool` and `--desc-level`.

Architectures
-------------
- **flat**  identity passthrough. The baseline; current `dmcp eval` behavior.
- **rag**   RAG-MCP: embed the prompt + each tool's `"name: description"` once,
            keep the top-`k` tools by cosine similarity. Surface is a single
            grab-bag (tools may span multiple servers).
- **hier**  hierarchical: a router LLM picks one server group (here just one
            server) from a short summary of available servers; only that
            server's tools are exposed.

Scope of v0: no caching of router decisions across specs (each eval run is
independent); no learned routers; no multi-hop hierarchy (group→server→tool is
collapsed to server→tools because our manifests don't carry group annotations
yet). Architecture choice is opaque to the evaluator — the trace records which
tools were offered, the architecture name rides in seed_metadata so reports can
stratify by it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from dmcp.embeddings import cosine
from dmcp.trace import ToolSpec

ARCHITECTURES: tuple[str, ...] = ("flat", "rag", "hier")
DEFAULT_RAG_K = 8


class _EmbedFn(Protocol):
    """Async embedder: input texts → vectors. Matches OpenRouterClient.embed."""

    async def __call__(self, texts: list[str]) -> list[list[float]]: ...


# Router signature: (prompt, [(server_id, server_summary)]) -> chosen server_id.
RouteFn = Callable[[str, list[tuple[str, str]]], Awaitable[str]]


def flat_surface(tool_surface: dict[str, list[ToolSpec]]) -> dict[str, list[ToolSpec]]:
    """Identity. Kept as a named function so callers can dispatch by name."""
    return {sid: list(specs) for sid, specs in tool_surface.items()}


async def rag_surface(
    tool_surface: dict[str, list[ToolSpec]],
    prompt: str,
    *,
    embed_fn: _EmbedFn,
    k: int = DEFAULT_RAG_K,
) -> dict[str, list[ToolSpec]]:
    """Top-`k` tools by cosine(prompt, "name: description"). Stable on ties.

    Embeds the prompt and every tool in one batched call. Returns a surface
    grouped by the original `server_id`. If `k` ≥ total tools, the input
    surface is returned unchanged (no LLM call needed).
    """
    flat: list[tuple[str, ToolSpec]] = [(sid, t) for sid, specs in tool_surface.items() for t in specs]
    if not flat:
        return {}
    total = len(flat)
    if k >= total:
        return flat_surface(tool_surface)

    tool_texts = [f"{t.name}: {(t.description or '').strip()}".strip() for _, t in flat]
    vecs = await embed_fn([prompt, *tool_texts])
    if not vecs:
        return flat_surface(tool_surface)
    pv = vecs[0]
    tool_vecs = vecs[1:]
    ranked = sorted(
        range(total),
        key=lambda i: (-cosine(pv, tool_vecs[i]), i),  # cosine desc; index asc breaks ties
    )
    keep = set(ranked[:k])
    out: dict[str, list[ToolSpec]] = {}
    for idx, (sid, t) in enumerate(flat):
        if idx in keep:
            out.setdefault(sid, []).append(t)
    return out


def _server_summary(server_id: str, specs: list[ToolSpec], *, max_tools: int = 8) -> str:
    """One-line summary the router LLM reads. Truncates tool list for prompt budget."""
    head = [t.name for t in specs[:max_tools]]
    tail = f" (+{len(specs) - max_tools} more)" if len(specs) > max_tools else ""
    return f"{server_id}: {len(specs)} tools — {', '.join(head)}{tail}"


async def hier_surface(
    tool_surface: dict[str, list[ToolSpec]],
    prompt: str,
    *,
    route_fn: RouteFn,
) -> dict[str, list[ToolSpec]]:
    """Router LLM picks one server; only that server's tools are exposed.

    Returns the empty surface only when the input is empty. If the router
    returns an unknown id, falls back to the first available server (so the
    candidate never sees an empty toolbox by router accident).
    """
    if not tool_surface:
        return {}
    items = list(tool_surface.items())
    summaries = [(sid, _server_summary(sid, specs)) for sid, specs in items]
    chosen = await route_fn(prompt, summaries)
    if chosen not in tool_surface:
        chosen = items[0][0]
    return {chosen: list(tool_surface[chosen])}


def make_openrouter_route_fn(llm) -> RouteFn:
    """Build a router that asks an OpenRouterClient to pick exactly one server.

    The router prompt is deliberately minimal: server summaries + the user goal.
    Cost rolls up into the candidate model's UsageAccumulator (E8.1).
    """
    sys_prompt = (
        "You are a tool-routing assistant. Given a user goal and a list of MCP "
        "servers (each with a short tool summary), pick the single server best "
        'suited to satisfy the goal. Respond with JSON {"server_id": "<id>"}.'
    )

    async def _route(prompt: str, summaries: list[tuple[str, str]]) -> str:
        listing = "\n".join(f"- {s}" for _, s in summaries)
        msg = f"Goal: {prompt}\n\nServers:\n{listing}\n\nPick one server_id."
        resp = await llm.chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": msg},
            ],
            tools=None,
            temperature=0.0,
        )
        content = (resp.content or "").strip()
        try:
            data = json.loads(content)
            sid = data.get("server_id")
            if isinstance(sid, str):
                return sid
        except json.JSONDecodeError:
            pass
        # Fallback: scan content for the first server_id we recognize.
        for sid, _ in summaries:
            if sid in content:
                return sid
        return summaries[0][0]

    return _route


async def apply_architecture(
    name: str,
    tool_surface: dict[str, list[ToolSpec]],
    prompt: str,
    *,
    embed_fn: _EmbedFn | None = None,
    route_fn: RouteFn | None = None,
    rag_k: int = DEFAULT_RAG_K,
) -> dict[str, list[ToolSpec]]:
    """Dispatch on architecture name. Tests inject fake embed_fn/route_fn.

    `flat` ignores both injected fns; `rag` requires `embed_fn`; `hier`
    requires `route_fn`. Unknown name raises — typo'd flags fail loudly.
    """
    if name == "flat":
        return flat_surface(tool_surface)
    if name == "rag":
        if embed_fn is None:
            raise ValueError("architecture=rag requires embed_fn")
        return await rag_surface(tool_surface, prompt, embed_fn=embed_fn, k=rag_k)
    if name == "hier":
        if route_fn is None:
            raise ValueError("architecture=hier requires route_fn")
        return await hier_surface(tool_surface, prompt, route_fn=route_fn)
    raise ValueError(f"unknown architecture: {name!r} (expected one of {ARCHITECTURES})")
