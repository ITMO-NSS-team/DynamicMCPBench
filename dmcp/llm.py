"""LLM client — OpenRouter via the OpenAI-compatible API.

A single thin wrapper used by the explorer (Phase 2A), the distiller
(Phase 2B), and the LLM-judge tier of the scorer (Phase 4 Tier 2). Default
model is Claude Haiku 4.5 because exploration is the most cost-sensitive
stage of the pipeline.

We deliberately stay on the OpenAI Chat Completions surface (not the
Responses API and not Anthropic's native messages API) because OpenRouter is
strongest there and because keeping one transport for all models lets us swap
in open-source models for ablations without code changes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

from dmcp.trace import ToolSpec

DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_EMBED_MODEL = "openai/text-embedding-3-small"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TOOL_NAMESPACE_SEP = "__"


def _load_env_once() -> None:
    """Idempotent .env load — pulls OPENROUTER_API_KEY into os.environ."""
    load_dotenv(override=False)


@dataclass(frozen=True)
class ToolCall:
    id: str
    server_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    usage: dict[str, Any] | None
    raw: dict[str, Any] = field(default_factory=dict)


def namespace_tool(server_id: str, tool_name: str) -> str:
    """Combine server + tool into a function name the LLM sees."""
    return f"{server_id}{TOOL_NAMESPACE_SEP}{tool_name}"


def unnamespace_tool(qualified: str) -> tuple[str, str]:
    """Inverse of namespace_tool. Raises if the input is not namespaced."""
    if TOOL_NAMESPACE_SEP not in qualified:
        raise ValueError(f"tool name not namespaced: {qualified!r}")
    server_id, tool_name = qualified.split(TOOL_NAMESPACE_SEP, 1)
    return server_id, tool_name


def specs_to_openai_tools(
    specs_by_server: dict[str, list[ToolSpec]],
) -> list[dict[str, Any]]:
    """Convert MCP ToolSpecs from one or more servers into OpenAI tool schema.

    Server id is folded into the function name with TOOL_NAMESPACE_SEP so the
    explorer can route the call back to the right MCP session.
    """
    tools: list[dict[str, Any]] = []
    for server_id, specs in specs_by_server.items():
        for s in specs:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": namespace_tool(server_id, s.name),
                        "description": s.description or "",
                        "parameters": s.input_schema
                        or {"type": "object", "properties": {}},
                    },
                }
            )
    return tools


class OpenRouterClient:
    """Async chat client backed by OpenRouter's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        app_title: str = "DynamicMCPBench",
        app_url: str = "https://github.com/jrzkaminski/DynamicMCPBench",
    ) -> None:
        _load_env_once()
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set (looked in env + .env)")
        self.model = model
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": app_url,
                "X-Title": app_title,
            },
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
        max_tokens: int | None = 4096,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if extra:
            kwargs.update(extra)

        completion = await self._client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            qualified = tc.function.name
            try:
                server_id, tool_name = unnamespace_tool(qualified)
            except ValueError:
                # Model produced a non-namespaced tool name; pass through
                # with empty server_id so caller can decide how to handle.
                server_id, tool_name = "", qualified
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": tc.function.arguments}
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    server_id=server_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )

        usage_dict: dict[str, Any] | None = None
        if completion.usage is not None:
            usage_dict = completion.usage.model_dump(mode="json")

        return ChatResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage_dict,
            raw=completion.model_dump(mode="json"),
        )

    async def embed(
        self, texts: list[str], *, model: str = DEFAULT_EMBED_MODEL
    ) -> list[list[float]]:
        """Embed texts via OpenRouter's OpenAI-compatible embeddings endpoint.

        Same key/base_url as chat. Model pinned for reproducibility (embeddings
        are deterministic per snapshot). Returns one vector per input text.
        """
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]
