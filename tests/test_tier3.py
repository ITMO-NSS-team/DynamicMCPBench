"""E1.2: unit tests for the Tier-3 LLM simulator in TraceReplayRecorder."""

from __future__ import annotations

from dmcp.llm import ChatResponse
from dmcp.replay import TraceReplayRecorder
from dmcp.trace import Trace


class _FakeLLM:
    """Stand-in for OpenRouterClient — records calls, returns canned content."""

    model = "fake/sim"

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def chat(self, messages, **kwargs):  # noqa: ANN001 - mirrors OpenRouterClient.chat
        self.calls += 1
        assert kwargs.get("temperature") == 0.0  # Tier-3 must be deterministic-as-possible
        return ChatResponse(content=self._text, tool_calls=[], finish_reason="stop", usage=None)


async def test_tier3_simulates_on_miss_when_enabled():
    llm = _FakeLLM("SIMULATED OUTPUT")
    rec = TraceReplayRecorder(cache_traces=[Trace()], simulator_llm=llm)
    async with rec:
        res = await rec.call_tool("srv", "do_thing", {"x": 1})
    assert res["isError"] is False
    assert res.get("simulated") is True
    assert res.get("replay_tier") == 3
    assert "SIMULATED OUTPUT" in res["content"][0]["text"]
    assert llm.calls == 1
    # the step is recorded as a successful agent call
    assert rec.trace.steps[-1].status.value == "success"


async def test_miss_without_simulator_is_error():
    rec = TraceReplayRecorder(cache_traces=[Trace()])
    async with rec:
        res = await rec.call_tool("srv", "do_thing", {"x": 1})
    assert res["isError"] is True
    assert res.get("replay_cache_miss") is True
    assert res.get("simulated") is None
