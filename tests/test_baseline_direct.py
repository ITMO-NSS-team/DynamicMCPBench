"""E4.2: direct generate-then-verify baseline generator.

Covers the verifier (accept good, reject unknown tool / unknown arg / empty
prompt), the mock-LLM proposal round-trip, the retry-with-error-hint loop,
and the TaskSpec marker that keeps this baseline distinguishable from
forward-distilled specs.
"""

from __future__ import annotations

import json

import pytest

from dmcp.baselines.direct_generation import (
    BASELINE_VERSION,
    DISTILLER_VERSION,
    DirectProposal,
    GenerationError,
    ProposedToolCall,
    generate_direct,
    to_taskspec,
    verify_proposal,
)
from dmcp.llm import ChatResponse, ToolCall
from dmcp.manifest import Dynamism, Manifest, ServerEntry
from dmcp.spec import ToolEffectCheckpoint, ValueProducedCheckpoint
from dmcp.trace import ToolSpec, TransportKind


def _spec(
    name: str,
    params: list[str] | None = None,
    desc: str = "",
) -> ToolSpec:
    input_schema = (
        {"type": "object", "properties": {p: {"type": "string"} for p in params}}
        if params is not None
        else None
    )
    return ToolSpec(name=name, description=desc, input_schema=input_schema)


_SURFACE = {
    "s": [
        _spec("list_rows", params=["table"]),
        _spec("get_row", params=["table", "id"]),
    ],
    "t": [
        _spec("describe_table", params=["table"]),
    ],
}


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def test_verify_accepts_well_formed_proposal():
    p = DirectProposal(
        prompt="list everything in users",
        tool_calls=[
            ProposedToolCall("s", "list_rows", {"table": "users"}),
            ProposedToolCall("s", "get_row", {"table": "users", "id": "1"}),
        ],
    )
    assert verify_proposal(p, _SURFACE) == []


def test_verify_rejects_empty_prompt():
    p = DirectProposal(
        prompt="   ",
        tool_calls=[ProposedToolCall("s", "list_rows", {"table": "users"})],
    )
    assert any("empty prompt" in e for e in verify_proposal(p, _SURFACE))


def test_verify_rejects_no_tool_calls():
    p = DirectProposal(prompt="do something", tool_calls=[])
    assert any("no tool_calls" in e for e in verify_proposal(p, _SURFACE))


def test_verify_rejects_unknown_tool():
    p = DirectProposal(
        prompt="do something",
        tool_calls=[ProposedToolCall("s", "does_not_exist", {})],
    )
    errs = verify_proposal(p, _SURFACE)
    assert any("unknown tool" in e for e in errs)


def test_verify_rejects_unknown_arg():
    p = DirectProposal(
        prompt="do something",
        tool_calls=[ProposedToolCall("s", "list_rows", {"banana": "yes"})],
    )
    errs = verify_proposal(p, _SURFACE)
    assert any("'banana'" in e for e in errs)


def test_verify_skips_arg_check_when_input_schema_missing():
    # No input_schema → can't tell what's a valid arg name; should not error.
    surface = {"x": [ToolSpec(name="opaque", description="", input_schema=None)]}
    p = DirectProposal(
        prompt="do something",
        tool_calls=[ProposedToolCall("x", "opaque", {"anything": "ok"})],
    )
    assert verify_proposal(p, surface) == []


# ---------------------------------------------------------------------------
# TaskSpec emission shape
# ---------------------------------------------------------------------------


def _manifest_with(server_ids: list[str], dynamism: Dynamism = Dynamism.live_read) -> Manifest:
    entries = []
    for sid in server_ids:
        kw = (
            {"command": "echo"}
            if dynamism is not Dynamism.stateful_write
            else {
                "command": "echo",
            }
        )
        entries.append(
            ServerEntry(
                server_id=sid,
                transport=TransportKind.stdio,
                dynamism=dynamism,
                sandbox=dynamism is Dynamism.stateful_write,
                **kw,
            )
        )
    return Manifest(servers=entries)


def test_to_taskspec_marks_baseline_and_emits_singleton_equivalence():
    p = DirectProposal(
        prompt="get me row 1",
        tool_calls=[
            ProposedToolCall("s", "list_rows", {"table": "users"}),
            ProposedToolCall("s", "get_row", {"table": "users", "id": "1"}),
        ],
        expected_substrings=["users"],
        sequential=True,
        notes="straightforward two-step",
    )
    manifest = _manifest_with(["s"])
    spec = to_taskspec(p, manifest=manifest)
    assert spec.distiller_version == DISTILLER_VERSION
    assert spec.distiller_version.startswith("baseline-")
    assert spec.notes is not None
    assert spec.notes.startswith("[BASELINE:direct_generation]")
    assert spec.dynamism is Dynamism.live_read
    assert spec.servers_used == ["s"]

    # 2 tool_effect + 1 value_produced (from expected_substrings)
    assert len(spec.checkpoints) == 3
    tool_cps = [c for c in spec.checkpoints if isinstance(c, ToolEffectCheckpoint)]
    val_cps = [c for c in spec.checkpoints if isinstance(c, ValueProducedCheckpoint)]
    assert len(tool_cps) == 2
    assert len(val_cps) == 1
    # AGB-shape singleton equivalence_set on every tool_effect (the gap RQ2 is built to measure)
    for cp in tool_cps:
        assert len(cp.equivalence_set) == 1
        assert cp.arg_predicate is not None
    # Sequential proposal → ordering chain between consecutive tool_effects only
    assert len(spec.ordering) == 1
    assert spec.ordering[0].before_id == "cp-0"
    assert spec.ordering[0].after_id == "cp-1"


def test_to_taskspec_omits_ordering_when_not_sequential():
    p = DirectProposal(
        prompt="describe two things",
        tool_calls=[
            ProposedToolCall("s", "list_rows", {"table": "u"}),
            ProposedToolCall("t", "describe_table", {"table": "u"}),
        ],
        sequential=False,
    )
    spec = to_taskspec(p, manifest=_manifest_with(["s", "t"]))
    assert spec.ordering == []
    assert spec.complexity.cross_server is True


def test_to_taskspec_propagates_stateful_write_dynamism():
    p = DirectProposal(
        prompt="write a row",
        tool_calls=[ProposedToolCall("db", "write", {"row": "x"})],
    )
    manifest = _manifest_with(["db"], dynamism=Dynamism.stateful_write)
    spec = to_taskspec(p, manifest=manifest)
    assert spec.dynamism is Dynamism.stateful_write
    assert spec.complexity.state_coupling is True


# ---------------------------------------------------------------------------
# generate_direct: mock-LLM end-to-end + retry loop
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Plays back a fixed sequence of `emit_direct_proposal` payloads."""

    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)
        self.calls = 0
        self.last_messages: list | None = None

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.last_messages = messages
        if not self._payloads:
            raise AssertionError("LLM called more times than scripted")
        payload = self._payloads.pop(0)
        self.calls += 1
        return ChatResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=str(self.calls),
                    server_id="",
                    tool_name="emit_direct_proposal",
                    arguments=payload,
                )
            ],
            finish_reason="stop",
            usage=None,
        )


async def test_generate_direct_emits_baseline_taskspec_on_first_try():
    llm = _ScriptedLLM(
        [
            {
                "prompt": "list everything in users",
                "tool_calls": [{"server_id": "s", "tool_name": "list_rows", "arguments": {"table": "users"}}],
                "sequential": False,
            }
        ]
    )
    spec = await generate_direct(_SURFACE, llm=llm, manifest=_manifest_with(["s", "t"]))
    assert spec.distiller_version == DISTILLER_VERSION
    assert spec.prompt == "list everything in users"
    assert llm.calls == 1
    # The system prompt + surface JSON must reach the model
    blob = json.dumps(llm.last_messages)
    assert "list_rows" in blob


async def test_generate_direct_retries_with_verifier_hint_then_succeeds():
    bad = {
        "prompt": "this asks for a nonexistent tool",
        "tool_calls": [{"server_id": "s", "tool_name": "does_not_exist", "arguments": {}}],
    }
    good = {
        "prompt": "list everything in users",
        "tool_calls": [{"server_id": "s", "tool_name": "list_rows", "arguments": {"table": "users"}}],
    }
    llm = _ScriptedLLM([bad, good])
    spec = await generate_direct(_SURFACE, llm=llm, manifest=_manifest_with(["s", "t"]))
    assert spec.prompt == "list everything in users"
    assert llm.calls == 2
    # The second-attempt prompt MUST surface the verifier error so the LLM can recover
    blob = json.dumps(llm.last_messages)
    assert "verification" in blob
    assert "unknown tool" in blob


async def test_generate_direct_raises_when_max_attempts_exhausted():
    bad = {
        "prompt": "still wrong",
        "tool_calls": [{"server_id": "s", "tool_name": "does_not_exist", "arguments": {}}],
    }
    llm = _ScriptedLLM([bad, bad])
    with pytest.raises(GenerationError):
        await generate_direct(_SURFACE, llm=llm, manifest=_manifest_with(["s", "t"]), max_attempts=2)


async def test_generate_direct_rejects_empty_surfaces():
    with pytest.raises(GenerationError):
        await generate_direct({}, llm=_ScriptedLLM([]))


def test_version_marker_is_explicitly_baseline():
    # Same orthogonality guard as the graph baseline: report aggregators must
    # be able to filter direct-gen specs out of the headline tally.
    assert DISTILLER_VERSION.startswith("baseline-")
    assert BASELINE_VERSION in DISTILLER_VERSION
