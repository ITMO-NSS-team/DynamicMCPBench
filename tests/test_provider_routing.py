"""provider.require_parameters routing is gated on the OpenRouter base_url (E8 fix)."""

import asyncio
import contextlib

from dmcp.llm import OpenRouterClient


class _CapturingChat:
    """Stand-in that records the create() kwargs then aborts the call."""

    def __init__(self):
        self.captured: dict = {}

        outer = self

        class _Completions:
            async def create(self, **kwargs):
                outer.captured.update(kwargs)
                raise RuntimeError("stop after capture")

        self.completions = _Completions()


def _capture_chat(client, **chat_kwargs) -> dict:
    fake = _CapturingChat()
    client._client.chat = fake
    with contextlib.suppress(RuntimeError):
        asyncio.run(client.chat(messages=[{"role": "user", "content": "hi"}], **chat_kwargs))
    return fake.captured


def test_openrouter_base_url_sets_flag():
    c = OpenRouterClient(model="x", api_key="k", base_url="https://openrouter.ai/api/v1")
    assert c._openrouter is True


def test_free_endpoint_base_url_does_not_set_flag():
    c = OpenRouterClient(model="x", api_key="k", base_url="https://free.example.internal/v1")
    assert c._openrouter is False


def test_chat_injects_provider_routing_on_openrouter_with_tools():
    c = OpenRouterClient(model="x", api_key="k", base_url="https://openrouter.ai/api/v1")
    captured = _capture_chat(
        c,
        tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
        tool_choice="required",
    )
    assert captured.get("extra_body") == {"provider": {"require_parameters": True}}


def test_chat_no_provider_routing_without_tools():
    c = OpenRouterClient(model="x", api_key="k", base_url="https://openrouter.ai/api/v1")
    captured = _capture_chat(c)
    assert "extra_body" not in captured


def test_chat_no_provider_routing_on_free_endpoint():
    c = OpenRouterClient(model="x", api_key="k", base_url="https://free.example.internal/v1")
    captured = _capture_chat(
        c,
        tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
        tool_choice="required",
    )
    assert "extra_body" not in captured
