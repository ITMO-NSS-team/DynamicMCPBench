"""E4.1: backward graph-sampling baseline generator.

Covers graph construction from JSON-Schema property overlap, deterministic
seeded subgraph sampling (chain + hub motifs), and a mock-LLM round-trip
that exercises `back_instruct` → valid TaskSpec with the baseline marker.
"""

from __future__ import annotations

import json

import pytest

from dmcp.baselines.graph_sampling import (
    BASELINE_VERSION,
    DISTILLER_VERSION,
    SamplingError,
    ToolGraph,
    back_instruct,
    sample_subgraph,
)
from dmcp.llm import ChatResponse, ToolCall
from dmcp.manifest import Dynamism, Manifest, ServerEntry
from dmcp.spec import ToolEffectCheckpoint
from dmcp.trace import ToolSpec, TransportKind


def _spec(
    name: str,
    input_props: list[str] | None = None,
    output_props: list[str] | None = None,
    desc: str = "",
) -> ToolSpec:
    input_schema = (
        {
            "type": "object",
            "properties": {p: {"type": "string"} for p in input_props},
        }
        if input_props is not None
        else None
    )
    output_schema = (
        {
            "type": "object",
            "properties": {p: {"type": "string"} for p in output_props},
        }
        if output_props is not None
        else None
    )
    return ToolSpec(
        name=name,
        description=desc,
        input_schema=input_schema,
        output_schema=output_schema,
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def test_graph_edge_from_schema_overlap():
    """An output property of A that matches an input property of B → edge A–B."""
    surfaces = {
        "users": [
            _spec("get_user", input_props=["query"], output_props=["user_id", "name"]),
            _spec("delete_user", input_props=["user_id"], output_props=["ok"]),
        ],
        "orders": [
            _spec("list_orders", input_props=["user_id"], output_props=["order_id"]),
            _spec("get_order", input_props=["order_id"], output_props=["item", "price"]),
        ],
    }
    graph = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    assert len(graph) == 4
    # get_user --user_id--> delete_user, list_orders (cross-server)
    assert ("orders", "list_orders") in graph.adj[("users", "get_user")]
    assert ("users", "delete_user") in graph.adj[("users", "get_user")]
    # list_orders --order_id--> get_order
    assert ("orders", "get_order") in graph.adj[("orders", "list_orders")]
    # get_user has no `order_id`, so no direct edge to get_order
    assert ("orders", "get_order") not in graph.adj[("users", "get_user")]


def test_graph_synthesizes_output_props_from_name_when_schema_missing():
    """No output_schema → use name tokens as the output-side signal."""
    surfaces = {
        "s": [
            _spec("get_branch", input_props=[], output_props=None),
            _spec("checkout", input_props=["branch"], output_props=None),
        ],
    }
    graph = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    # "branch" is in get_branch's name-derived output AND checkout's input → edge
    assert ("s", "checkout") in graph.adj[("s", "get_branch")]


def test_graph_drops_stopword_only_overlap():
    """CRUD verbs alone must not link unrelated tools."""
    surfaces = {
        "a": [_spec("get_thing", input_props=[], output_props=None)],
        "b": [_spec("list_widget", input_props=["get"], output_props=None)],
    }
    graph = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    # "get" is a stopword on both sides → no edge
    assert ("b", "list_widget") not in graph.adj.get(("a", "get_thing"), set())


def test_same_server_fallback_links_disconnected_siblings():
    surfaces = {
        "iso": [
            _spec("alpha", input_props=[], output_props=None),
            _spec("beta", input_props=[], output_props=None),
        ],
    }
    g_no = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    g_yes = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=True)
    assert ("iso", "beta") not in g_no.adj[("iso", "alpha")]
    assert ("iso", "beta") in g_yes.adj[("iso", "alpha")]


# ---------------------------------------------------------------------------
# Subgraph sampling
# ---------------------------------------------------------------------------


def _chain_surfaces() -> dict[str, list[ToolSpec]]:
    """A → B → C → D linear chain via shared property names."""
    return {
        "s": [
            _spec("first", input_props=[], output_props=["alpha"]),
            _spec("second", input_props=["alpha"], output_props=["beta"]),
            _spec("third", input_props=["beta"], output_props=["gamma"]),
            _spec("fourth", input_props=["gamma"], output_props=["delta"]),
        ],
    }


def test_sample_chain_deterministic_and_connected():
    graph = ToolGraph.from_tool_surfaces(_chain_surfaces(), same_server_fallback=False)
    sg_a = sample_subgraph(graph, size=3, motif="chain", seed=42)
    sg_b = sample_subgraph(graph, size=3, motif="chain", seed=42)
    assert sg_a.nodes == sg_b.nodes
    assert sg_a.motif == "chain"
    assert len(sg_a.nodes) == 3
    # Every consecutive pair in the chain walk must be a real edge
    for a, b in zip(sg_a.nodes, sg_a.nodes[1:], strict=False):
        assert b in graph.adj[a], f"{a} not adjacent to {b}"


def test_sample_chain_size_caps_at_graph_size():
    graph = ToolGraph.from_tool_surfaces(_chain_surfaces(), same_server_fallback=False)
    sg = sample_subgraph(graph, size=99, motif="chain", seed=1)
    assert 1 <= len(sg.nodes) <= 4


def test_sample_hub_centers_on_high_degree_node():
    """The 'center' tool is in every other tool's input → highest degree."""
    surfaces = {
        "g": [
            _spec("center", input_props=[], output_props=["pivot"]),
            _spec("leaf_a", input_props=["pivot"], output_props=[]),
            _spec("leaf_b", input_props=["pivot"], output_props=[]),
            _spec("leaf_c", input_props=["pivot"], output_props=[]),
        ],
    }
    graph = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    sg = sample_subgraph(graph, size=3, motif="hub", seed=7)
    assert ("g", "center") in sg.nodes
    assert len(sg.nodes) == 3


def test_unknown_motif_rejected():
    graph = ToolGraph.from_tool_surfaces(_chain_surfaces())
    with pytest.raises(SamplingError):
        sample_subgraph(graph, size=2, motif="loop", seed=0)


def test_empty_graph_rejected():
    graph = ToolGraph.from_tool_surfaces({})
    with pytest.raises(SamplingError):
        sample_subgraph(graph, size=2, motif="chain", seed=0)


# ---------------------------------------------------------------------------
# Back-instruction round-trip with mocked LLM
# ---------------------------------------------------------------------------


class _MockLLM:
    """Returns a fixed `emit_baseline_prompt` tool call so the test stays offline."""

    def __init__(self, prompt: str = "Walk the chain", notes: str = "ambig: none") -> None:
        self._prompt = prompt
        self._notes = notes
        self.last_messages: list | None = None

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.last_messages = messages
        return ChatResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="1",
                    server_id="",
                    tool_name="emit_baseline_prompt",
                    arguments={"prompt": self._prompt, "notes": self._notes},
                )
            ],
            finish_reason="stop",
            usage=None,
        )


def _manifest_with(server_ids: list[str], dynamism: Dynamism = Dynamism.live_read) -> Manifest:
    return Manifest(
        servers=[
            ServerEntry(
                server_id=sid,
                transport=TransportKind.stdio,
                dynamism=dynamism,
                command="echo",
            )
            for sid in server_ids
        ]
    )


async def test_back_instruct_emits_valid_baseline_taskspec():
    graph = ToolGraph.from_tool_surfaces(_chain_surfaces(), same_server_fallback=False)
    subgraph = sample_subgraph(graph, size=3, motif="chain", seed=42)
    manifest = _manifest_with(["s"], dynamism=Dynamism.live_read)
    llm = _MockLLM(prompt="Run through the chain", notes="alt path possible")

    spec = await back_instruct(subgraph, graph, llm=llm, manifest=manifest)

    assert spec.prompt == "Run through the chain"
    assert spec.distiller_version == DISTILLER_VERSION
    assert spec.distiller_version.startswith("baseline-")
    assert spec.dynamism is Dynamism.live_read
    assert spec.servers_used == ["s"]
    assert len(spec.checkpoints) == 3
    for cp in spec.checkpoints:
        assert isinstance(cp, ToolEffectCheckpoint)
        # Baseline shape: singleton equivalence_set (AGB-style GT tool list)
        assert len(cp.equivalence_set) == 1
    # Chain motif → sequential ordering between consecutive checkpoints
    assert len(spec.ordering) == 2
    # `[BASELINE:...]` marker MUST be present in notes (orthogonality guard)
    assert spec.notes is not None
    assert spec.notes.startswith("[BASELINE:graph_sampling motif=chain seed=42]")
    # No reference trace exists, but the field still validates
    assert spec.source_trace_id is not None

    # The subgraph view the LLM saw must include the sampled tools' names
    blob = json.dumps(llm.last_messages)
    assert "second" in blob
    assert "motif" in blob


async def test_back_instruct_hub_motif_has_no_ordering():
    surfaces = {
        "g": [
            _spec("center", input_props=[], output_props=["pivot"]),
            _spec("leaf_a", input_props=["pivot"], output_props=[]),
            _spec("leaf_b", input_props=["pivot"], output_props=[]),
        ],
    }
    graph = ToolGraph.from_tool_surfaces(surfaces, same_server_fallback=False)
    subgraph = sample_subgraph(graph, size=3, motif="hub", seed=3)
    llm = _MockLLM(prompt="Use the hub")

    spec = await back_instruct(subgraph, graph, llm=llm, manifest=_manifest_with(["g"]))

    assert spec.ordering == []
    assert spec.notes is not None
    assert "motif=hub" in spec.notes


async def test_back_instruct_propagates_stateful_write_dynamism():
    surfaces = {"db": [_spec("write_row", input_props=["row"], output_props=["ok"])]}
    graph = ToolGraph.from_tool_surfaces(surfaces)
    subgraph = sample_subgraph(graph, size=1, motif="chain", seed=1)
    manifest = Manifest(
        servers=[
            ServerEntry(
                server_id="db",
                transport=TransportKind.stdio,
                dynamism=Dynamism.stateful_write,
                sandbox=True,
                command="echo",
            )
        ]
    )
    spec = await back_instruct(subgraph, graph, llm=_MockLLM(prompt="x"), manifest=manifest)
    assert spec.dynamism is Dynamism.stateful_write
    assert spec.complexity.state_coupling is True


async def test_back_instruct_rejects_empty_prompt():
    graph = ToolGraph.from_tool_surfaces(_chain_surfaces())
    subgraph = sample_subgraph(graph, size=2, motif="chain", seed=0)
    llm = _MockLLM(prompt="   ")
    with pytest.raises(SamplingError):
        await back_instruct(subgraph, graph, llm=llm)


def test_version_marker_is_explicitly_baseline():
    # Regression guard for the orthogonality contract: the version string MUST
    # start with `baseline-` so report aggregators can filter it out of the
    # headline tally without per-call knowledge.
    assert DISTILLER_VERSION.startswith("baseline-")
    assert BASELINE_VERSION in DISTILLER_VERSION
