"""E1.4: tests for the persona library, selection, diversity metric, and that
personas flow into the goal-gen prompt."""

from __future__ import annotations

import json

from dmcp.llm import ChatResponse, ToolCall
from dmcp.personas import PERSONAS, diversity_score, select_personas


def test_persona_library_wellformed():
    assert len(PERSONAS) >= 5
    for p in PERSONAS:
        assert {"id", "label", "intent"} <= set(p)
        assert p["id"] and p["label"] and p["intent"]
    assert len({p["id"] for p in PERSONAS}) == len(PERSONAS)  # ids unique


def test_select_personas_deterministic_and_sized():
    assert select_personas(0) == []
    a = select_personas(3, seed=7)
    b = select_personas(3, seed=7)
    assert a == b  # deterministic
    assert len(a) == 3
    # cycles when n exceeds the library
    assert len(select_personas(len(PERSONAS) + 2, seed=1)) == len(PERSONAS) + 2
    # different seed generally reorders
    assert select_personas(len(PERSONAS), seed=1) != select_personas(len(PERSONAS), seed=2)


def test_diversity_score_bounds():
    assert diversity_score(["a b c", "a b c"]) == 0.0  # identical → 0
    assert diversity_score(["a b c", "d e f"]) == 1.0  # disjoint → 1
    assert diversity_score(["only one"]) == 0.0  # needs >= 2
    mixed = diversity_score(["check the time in tokyo", "summarize the wikipedia article"])
    assert 0.0 < mixed <= 1.0


class _MockLLM:
    def __init__(self) -> None:
        self.last_messages = None

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.last_messages = messages
        return ChatResponse(
            content=None,
            tool_calls=[ToolCall(id="1", server_id="", tool_name="emit_goals", arguments={"goals": []})],
            finish_reason="stop",
            usage=None,
        )


async def test_personas_injected_into_prompt():
    from dmcp.goal_gen import _ask_for_goals

    llm = _MockLLM()
    personas = [{"id": "x", "label": "Test Persona", "intent": "do something specific"}]
    await _ask_for_goals(llm, [{"server_id": "s", "tools": []}], 1, "single server 's'", personas=personas)
    blob = json.dumps(llm.last_messages)
    assert "Test Persona" in blob
    assert "do something specific" in blob


async def test_no_personas_no_injection():
    from dmcp.goal_gen import _ask_for_goals

    llm = _MockLLM()
    await _ask_for_goals(llm, [{"server_id": "s", "tools": []}], 1, "single server 's'", personas=None)
    blob = json.dumps(llm.last_messages)
    assert "Adopt a DISTINCT user persona" not in blob
