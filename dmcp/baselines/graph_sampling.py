"""Backward graph-sampling TaskSpec generator (RQ2 baseline — NOT the headline).

This module exists to make RQ2 measurable: compare DynamicMCPBench's headline
forward-exploration → trace → distill path against the closest prior-art
generator shape, which is AgentGraphBench-style.

Pipeline (clearly labeled baseline at every step):

  tool surfaces (manifest)
       │
       ▼
  ToolGraph: nodes = tools, edges = inferred typed I/O overlap (an output
       property name of `a` matches an input property name of `b`, with
       same-server adjacency as a fallback for sparse graphs)
       │
       ▼
  sample a connected subgraph of N tools using a `chain` or `hub` motif
       │
       ▼
  LLM back-instructs a natural-language user prompt that would exercise
       the sampled tools (tool-call schema, temperature=0)
       │
       ▼
  TaskSpec with one tool_effect checkpoint per sampled tool. The spec is
       `distiller_version="baseline-graph-sampling-<v>"` and its `notes`
       carry the `[BASELINE:graph_sampling motif=… seed=…]` marker so
       downstream reports cannot conflate it with forward-distilled specs.

Per `memory/feedback_agb_orthogonality.md`: this is allowed only as a
**clearly labeled comparison baseline**. We do NOT add the graph anywhere
on the headline path; we do NOT introduce a GT tool list as truth (the
emitted equivalence_sets are singletons by design — the *known* weakness
of this baseline, on purpose, so the comparison surfaces the gap).
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from dmcp.llm import OpenRouterClient
from dmcp.manifest import Dynamism, Manifest
from dmcp.spec import (
    SPEC_SCHEMA_VERSION,
    ComplexityProfile,
    OrderConstraint,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
)
from dmcp.trace import ToolSpec

BASELINE_VERSION = "0.1.0"
DISTILLER_VERSION = f"baseline-graph-sampling-{BASELINE_VERSION}"

VALID_MOTIFS = ("chain", "hub")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Verbs/stopwords that aren't useful as type-overlap signals when read from
# a tool name. Kept tight on purpose: removing too many drops real signal.
_NAME_STOPWORDS = frozenset(
    {
        "get",
        "list",
        "fetch",
        "read",
        "search",
        "find",
        "show",
        "describe",
        "set",
        "put",
        "post",
        "delete",
        "add",
        "remove",
        "update",
        "create",
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "by",
        "of",
        "to",
        "all",
        "tool",
        "tools",
    }
)

BASELINE_SYSTEM = """You are designing a natural-language user request for an MCP-agent benchmark task.

You will be shown a small set of MCP tools that were sampled together from a
tool-dependency graph (one of `chain` — sequential I/O overlap — or `hub` — a
central tool with related neighbors). Call `emit_baseline_prompt` exactly once
with:

  prompt:  a single fuzzy user request that a real user might voice, which can
           be satisfied by using ALL of the listed tools at least once. Strip
           explicit tool names from the user-facing text; refer to capabilities
           in natural language. Do NOT invent concrete external resources
           (file paths, ids, urls) that aren't visible in the tool schemas.
           When you'd otherwise need to invent a resource, prefer discovery
           phrasings ("what does it expose", "describe the schema").

  notes:   any caveats, ambiguity, or alternative interpretation you noticed.

This is a labeled RQ2 baseline (graph-sampling + back-instruction). Stay
faithful: do not propose a task the tools cannot together accomplish.
""".strip()


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def _camel_split(s: str) -> list[str]:
    return _CAMEL_SPLIT.sub(" ", s).split()


def _name_tokens(name: str) -> set[str]:
    """Token set derived from a tool name (snake_case + CamelCase aware).

    Filtered for tokens of length >= 3 that aren't generic CRUD verbs or
    common stopwords — those would create spurious universal edges.
    """
    parts: list[str] = []
    for chunk in _camel_split(name):
        parts.extend(_TOKEN_RE.findall(chunk.lower()))
    return {t for t in parts if len(t) >= 3 and t not in _NAME_STOPWORDS}


def _schema_property_names(schema: dict[str, Any] | None) -> set[str]:
    """Top-level `properties` keys from a JSON Schema, lowercased + tokenized.

    JSON Schema property keys are returned as-is *and* split on snake/camel so
    a tool with `input_schema.properties.userId` connects to a tool whose name
    is `get_user_id`. Keys shorter than 3 chars are dropped.
    """
    out: set[str] = set()
    if not isinstance(schema, dict):
        return out
    props = schema.get("properties")
    if not isinstance(props, dict):
        return out
    for key in props:
        if not isinstance(key, str):
            continue
        key_l = key.lower()
        if len(key_l) >= 3 and key_l not in _NAME_STOPWORDS:
            out.add(key_l)
        for tok in _camel_split(key):
            for sub in _TOKEN_RE.findall(tok.lower()):
                if len(sub) >= 3 and sub not in _NAME_STOPWORDS:
                    out.add(sub)
    return out


@dataclass(frozen=True)
class ToolNode:
    """One node in the (baseline-only) tool-dependency graph."""

    server_id: str
    tool_name: str
    description: str
    input_props: frozenset[str]
    output_props: frozenset[str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.server_id, self.tool_name)


@dataclass
class ToolGraph:
    """Undirected tool-dependency graph (baseline-only).

    Edge `a — b` exists iff any output-side token of either tool matches an
    input-side token of the other. As a fallback for sparse graphs (e.g.
    schemas without `properties`), nodes on the same server are connected.

    The graph is deliberately built ONLY here — the rest of dmcp does not
    consume it, so the orthogonality rule (no graph on the headline path) is
    preserved.
    """

    nodes: dict[tuple[str, str], ToolNode] = field(default_factory=dict)
    adj: dict[tuple[str, str], set[tuple[str, str]]] = field(default_factory=dict)

    @classmethod
    def from_tool_surfaces(
        cls,
        surfaces: dict[str, list[ToolSpec]],
        *,
        same_server_fallback: bool = True,
    ) -> ToolGraph:
        nodes: dict[tuple[str, str], ToolNode] = {}
        for server_id, specs in surfaces.items():
            for spec in specs:
                in_props = _schema_property_names(spec.input_schema)
                # Output-side tokens: schema if present, otherwise the tool
                # name as a synthetic "what this tool produces" hint. This is
                # the baseline's load-bearing simplification — real MCP
                # servers rarely declare output_schema.
                out_props = _schema_property_names(spec.output_schema)
                if not out_props:
                    out_props = _name_tokens(spec.name)
                key = (server_id, spec.name)
                if key in nodes:
                    continue
                nodes[key] = ToolNode(
                    server_id=server_id,
                    tool_name=spec.name,
                    description=(spec.description or "")[:1000],
                    input_props=frozenset(in_props),
                    output_props=frozenset(out_props),
                )
        adj: dict[tuple[str, str], set[tuple[str, str]]] = {k: set() for k in nodes}
        keys = sorted(nodes.keys())
        for i, a in enumerate(keys):
            na = nodes[a]
            for b in keys[i + 1 :]:
                nb = nodes[b]
                # Directed signal in either direction → undirected edge.
                overlap = (na.output_props & nb.input_props) | (nb.output_props & na.input_props)
                connected = bool(overlap)
                if not connected and same_server_fallback and na.server_id == nb.server_id:
                    connected = True
                if connected:
                    adj[a].add(b)
                    adj[b].add(a)
        return cls(nodes=nodes, adj=adj)

    def __len__(self) -> int:
        return len(self.nodes)

    def degree(self, key: tuple[str, str]) -> int:
        return len(self.adj.get(key, ()))


# ---------------------------------------------------------------------------
# Subgraph sampling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subgraph:
    """A connected subgraph sampled from a ToolGraph as a baseline task seed."""

    nodes: tuple[tuple[str, str], ...]
    edges: tuple[tuple[tuple[str, str], tuple[str, str]], ...]
    motif: str
    seed: int


class SamplingError(ValueError):
    pass


def _seeded_choice(rng: random.Random, items: list[Any]) -> Any:
    if not items:
        raise IndexError("cannot choose from empty list")
    return items[rng.randrange(len(items))]


def _sample_chain(graph: ToolGraph, size: int, rng: random.Random) -> list[tuple[str, str]]:
    """Grow a simple path: start from a random node, walk to an unseen neighbor
    each step until `size` is reached or we run out of unseen neighbors. If
    stuck before `size` we backtrack to the last node with unseen neighbors.
    """
    keys = sorted(graph.nodes.keys())
    start = _seeded_choice(rng, keys)
    path: list[tuple[str, str]] = [start]
    seen: set[tuple[str, str]] = {start}
    while len(path) < size:
        last = path[-1]
        unseen = sorted(n for n in graph.adj.get(last, ()) if n not in seen)
        if unseen:
            nxt = _seeded_choice(rng, unseen)
            path.append(nxt)
            seen.add(nxt)
            continue
        if len(path) == 1:
            break
        path.pop()  # backtrack
    return path


def _sample_hub(graph: ToolGraph, size: int, rng: random.Random) -> list[tuple[str, str]]:
    """Pick a high-degree hub and its top neighbors."""
    keys = sorted(graph.nodes.keys())
    if not keys:
        return []
    max_deg = max(graph.degree(k) for k in keys)
    hubs = [k for k in keys if graph.degree(k) == max_deg]
    hub = _seeded_choice(rng, hubs)
    nbrs = sorted(graph.adj.get(hub, ()))
    rng.shuffle(nbrs)
    chosen = [hub, *nbrs[: size - 1]]
    # If hub had too few neighbors, top up from the rest of the graph
    # (deterministic order, then shuffled by seed) — keeps `size` honored
    # even on sparse graphs.
    if len(chosen) < size:
        rest = [k for k in keys if k not in chosen]
        rng.shuffle(rest)
        chosen.extend(rest[: size - len(chosen)])
    return chosen


def sample_subgraph(
    graph: ToolGraph,
    *,
    size: int,
    motif: str = "chain",
    seed: int = 0,
) -> Subgraph:
    """Sample a `size`-node connected subgraph using the requested motif.

    Returns a `Subgraph` carrying the sampled nodes (in motif-natural order:
    sequential for `chain`, hub-first for `hub`) and the edges induced by the
    graph between them. Deterministic in `seed`.
    """
    if motif not in VALID_MOTIFS:
        raise SamplingError(f"unknown motif {motif!r}; valid: {VALID_MOTIFS}")
    if size <= 0:
        raise SamplingError("size must be positive")
    if not graph.nodes:
        raise SamplingError("graph is empty")
    target = min(size, len(graph.nodes))
    rng = random.Random(seed)
    if motif == "chain":
        nodes = _sample_chain(graph, target, rng)
    else:
        nodes = _sample_hub(graph, target, rng)
    induced: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if b in graph.adj.get(a, ()):
                induced.append((a, b))
    return Subgraph(
        nodes=tuple(nodes),
        edges=tuple(induced),
        motif=motif,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# LLM back-instruction
# ---------------------------------------------------------------------------


def _emit_baseline_prompt_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_baseline_prompt",
            "description": "Emit a natural-language user prompt for the sampled tools.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prompt"],
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Fuzzy NL user request that exercises all sampled tools.",
                    },
                    "notes": {"type": "string"},
                },
            },
        },
    }


def _subgraph_view(subgraph: Subgraph, graph: ToolGraph) -> dict[str, Any]:
    nodes_view = [
        {
            "server_id": graph.nodes[k].server_id,
            "tool_name": graph.nodes[k].tool_name,
            "description": graph.nodes[k].description,
            "input_props": sorted(graph.nodes[k].input_props),
            "output_props": sorted(graph.nodes[k].output_props),
        }
        for k in subgraph.nodes
    ]
    edges_view = [{"a": f"{a[0]}.{a[1]}", "b": f"{b[0]}.{b[1]}"} for a, b in subgraph.edges]
    return {
        "motif": subgraph.motif,
        "nodes": nodes_view,
        "edges": edges_view,
    }


def _derive_complexity(subgraph: Subgraph, manifest: Manifest | None) -> ComplexityProfile:
    server_ids = sorted({s for s, _ in subgraph.nodes})
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
        trace_depth=len(subgraph.nodes),
        distinct_servers=len(server_ids),
        cross_server=len(server_ids) > 1,
        runtime_branching=False,
        state_coupling=state_coupling,
        recovery_required=False,
    )


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


def _build_checkpoints(subgraph: Subgraph) -> list[ToolEffectCheckpoint]:
    """One singleton-equivalence-set tool_effect per sampled tool.

    Singletons (not real equivalence sets) are the **point** of this baseline:
    AGB-style ground truth is a tool list — that's the comparison shape. The
    forward path emits multi-tool equivalence_sets when the trace warrants it;
    the gap between the two is what RQ2 measures.
    """
    cps: list[ToolEffectCheckpoint] = []
    for i, (sid, tname) in enumerate(subgraph.nodes):
        cps.append(
            ToolEffectCheckpoint(
                checkpoint_id=f"cp-{i}",
                description=f"call {sid}.{tname}",
                equivalence_set=[ToolReference(server_id=sid, tool_name=tname)],
                arg_predicate=None,
                must_succeed=True,
            )
        )
    return cps


def _build_ordering(subgraph: Subgraph, checkpoints: list[ToolEffectCheckpoint]) -> list[OrderConstraint]:
    """Sequential ordering only for `chain` motifs; hub motifs are parallel."""
    if subgraph.motif != "chain":
        return []
    return [
        OrderConstraint(before_id=checkpoints[i].checkpoint_id, after_id=checkpoints[i + 1].checkpoint_id)
        for i in range(len(checkpoints) - 1)
    ]


async def back_instruct(
    subgraph: Subgraph,
    graph: ToolGraph,
    *,
    llm: OpenRouterClient,
    manifest: Manifest | None = None,
) -> TaskSpec:
    """LLM-back-instruct a TaskSpec from a sampled subgraph.

    The LLM only chooses the user-facing `prompt` and any caveat `notes`. The
    checkpoint structure is derived from the subgraph itself, so this baseline
    cannot smuggle in a forward-style "discover an equivalence_set" signal.
    """
    view = _subgraph_view(subgraph, graph)
    messages = [
        {"role": "system", "content": BASELINE_SYSTEM},
        {
            "role": "user",
            "content": (
                "Compose the user request for these tools and call "
                "`emit_baseline_prompt` exactly once.\n\n"
                f"```json\n{json.dumps(view, indent=2, default=str)}\n```"
            ),
        },
    ]
    resp = await llm.chat(
        messages=messages,
        tools=[_emit_baseline_prompt_schema()],
        tool_choice={"type": "function", "function": {"name": "emit_baseline_prompt"}},
        temperature=0.0,
    )
    if not resp.tool_calls:
        raise SamplingError(f"LLM did not call emit_baseline_prompt; content={resp.content!r}")
    args = resp.tool_calls[0].arguments
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise SamplingError("LLM returned an empty prompt")
    llm_notes = str(args.get("notes") or "").strip()

    checkpoints = _build_checkpoints(subgraph)
    ordering = _build_ordering(subgraph, checkpoints)
    server_ids = sorted({s for s, _ in subgraph.nodes})
    note_tag = f"[BASELINE:graph_sampling motif={subgraph.motif} seed={subgraph.seed}]"
    notes = note_tag if not llm_notes else f"{note_tag} {llm_notes}"

    return TaskSpec(
        task_id=uuid4(),
        schema_version=SPEC_SCHEMA_VERSION,
        distiller_version=DISTILLER_VERSION,
        source_trace_id=uuid4(),  # baseline has no source trace; synthetic id
        prompt=prompt,
        dynamism=_derive_dynamism(server_ids, manifest),
        servers_used=server_ids,
        complexity=_derive_complexity(subgraph, manifest),
        checkpoints=list(checkpoints),
        minefields=[],
        ordering=ordering,
        notes=notes,
    )
