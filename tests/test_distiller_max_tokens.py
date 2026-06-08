"""E8.7: distiller passes a large max_tokens to the chat call.

Pins the regression we hit during the first E8.7 corpus run: kimi-k2p6 (a
reasoning model) burned the default 4096-token budget on visible CoT before
emitting the structured `emit_task_spec` tool_call, so two of three shards
distilled 0/97 specs. The fix is the explicit DISTILLER_MAX_TOKENS constant;
this test ensures a future "cleanup" PR can't silently drop it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from dmcp.distiller import DISTILLER_MAX_TOKENS, DistillationError, distill
from dmcp.llm import ChatResponse, ToolCall
from dmcp.trace import Step, StepKind, StepStatus, ToolSpec, Trace


def test_distiller_max_tokens_is_large_enough_for_reasoning_models():
    """4096 is too tight for reasoning models; 16k gives moderate CoT + spec headroom."""
    assert DISTILLER_MAX_TOKENS >= 16_384


class _StubLLM:
    """Records the kwargs handed to chat() and returns a minimal valid spec."""

    def __init__(self) -> None:
        self.model = "stub/distiller"
        self.last_kwargs: dict[str, Any] = {}

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.last_kwargs = kwargs
        args = {
            "prompt": "do the thing",
            "checkpoints": [
                {
                    "kind": "tool_effect",
                    "checkpoint_id": "cp0",
                    "description": "lookup",
                    "equivalence_set": [{"server_id": "fs", "tool_name": "read_file"}],
                }
            ],
        }
        return ChatResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_0", server_id="", tool_name="emit_task_spec", arguments=args)],
            finish_reason="tool_calls",
            usage=None,
            raw={},
        )


def _trace_with_one_successful_call() -> Trace:
    """Minimal trace the distiller will accept (one successful agent tool call)."""
    tr = Trace(goal="g")
    tr.tool_specs["fs"] = [ToolSpec(name="read_file", description="read a file")]
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id="fs",
            tool_name="read_file",
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
            result={"content": [{"type": "text", "text": "hello"}]},
        )
    )
    return tr


@pytest.mark.asyncio
async def test_distill_passes_max_tokens_to_chat():
    """Regression: the explicit max_tokens kwarg must reach the chat call.
    Without it, the OpenRouterClient default (4096) kicks in and reasoning
    models truncate before emitting the tool_call."""
    llm = _StubLLM()
    trace = _trace_with_one_successful_call()
    spec = await distill(trace, llm=llm)  # type: ignore[arg-type]
    assert llm.last_kwargs.get("max_tokens") == DISTILLER_MAX_TOKENS
    # And the rest of the schema-discipline kwargs must still be set:
    assert llm.last_kwargs.get("temperature") == 0.0
    assert llm.last_kwargs.get("tool_choice", {}).get("function", {}).get("name") == "emit_task_spec"
    # Spec was successfully constructed (proves the stub round-trip works).
    assert spec.prompt == "do the thing"
    assert spec.checkpoints[0].checkpoint_id == "cp0"


class _TruncatingStubLLM:
    """Simulates the kimi-k2p6 failure mode: returns content-only, no tool_call.
    Used to pin that the existing DistillationError surface still fires when
    the distiller_max_tokens budget IS exhausted (the bug we'd otherwise mask)."""

    model = "stub/truncating"

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(
            content="Let me analyze the trace carefully...\n[reasoning runs out]",
            tool_calls=[],
            finish_reason="length",
            usage=None,
            raw={},
        )


@pytest.mark.asyncio
async def test_distill_still_raises_when_model_returns_no_tool_call():
    """Belt-and-suspenders: a bigger budget makes truncation rarer but not
    impossible. The DistillationError contract (the distiller surface raises
    cleanly so callers can log+skip) must still hold."""
    llm = _TruncatingStubLLM()
    trace = _trace_with_one_successful_call()
    with pytest.raises(DistillationError, match="emit_task_spec"):
        await distill(trace, llm=llm)  # type: ignore[arg-type]
