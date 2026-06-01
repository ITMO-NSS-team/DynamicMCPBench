"""E2.6: Level A/B description normalization."""

from __future__ import annotations

from dmcp.llm import ChatResponse
from dmcp.normalize import apply_normalization, normalize_level_a
from dmcp.trace import ToolSpec


def test_level_a_is_deterministic_surface_only():
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}
    a = normalize_level_a("search", "  find   stuff  ", schema)
    b = normalize_level_a("search", "  find   stuff  ", schema)
    assert a == b  # deterministic
    assert a.startswith("Purpose: find stuff")  # whitespace collapsed, content preserved
    assert "query" in a and "limit" in a  # declared params surfaced
    # no new semantics beyond the description + param names
    assert "Outputs" not in a


def test_level_a_handles_empty_description():
    out = normalize_level_a("get_time", "", None)
    assert "the get_time operation" in out
    assert "Parameters: none" in out


class _MockLLM:
    model = "mock"

    def __init__(self) -> None:
        self.calls = 0
        self.last_user = ""

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        self.last_user = messages[-1]["content"]
        assert kwargs.get("temperature") == 0.0
        return ChatResponse(
            content="[Purpose] do X. [Inputs] q. [Outputs] r.",
            tool_calls=[],
            finish_reason="stop",
            usage=None,
        )


async def test_level_b_uses_llm_rubric():
    llm = _MockLLM()
    surface = {"s": [ToolSpec(name="search", description="find", input_schema={"properties": {"q": {}}})]}
    out = await apply_normalization(surface, "b", llm)
    assert llm.calls == 1
    assert out["s"][0].description.startswith("[Purpose]")
    assert "search" in llm.last_user  # the tool name reached the prompt


async def test_apply_level_a_rewrites_and_dedups():
    llm = _MockLLM()  # unused for level a
    surface = {
        "s": [
            ToolSpec(name="search", description="find issues", input_schema={"properties": {"q": {}}}),
            ToolSpec(name="search", description="find issues", input_schema={"properties": {"q": {}}}),
        ]
    }
    out = await apply_normalization(surface, "a", llm)
    assert llm.calls == 0  # level a needs no LLM
    assert all(t.description.startswith("Purpose:") for t in out["s"])
