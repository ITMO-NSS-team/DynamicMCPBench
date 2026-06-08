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
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

from dmcp.pricing import compute_cost_usd, get_price
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
    wall_ms: float | None = None


@dataclass
class UsageAccumulator:
    """Lifetime token/latency/cost tally for one OpenRouterClient (E8.1 / B1).

    Snapshots are deltas-friendly: callers stash `before = client.usage.snapshot()`
    around a work unit (one explore() call) and diff against `after` to attribute
    cost per spec. `unknown_price` flips True the first time a call records cost
    for a model we don't have a pinned price for; the flag rides into the
    EvaluationResult summary so the cost/latency Pareto stays honest.
    """

    model: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    wall_ms_total: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    unknown_price: bool = False

    def add(self, usage: dict[str, Any] | None, wall_ms: float) -> None:
        self.calls += 1
        self.wall_ms_total += wall_ms
        self.latencies_ms.append(wall_ms)
        pt = int((usage or {}).get("prompt_tokens") or 0)
        ct = int((usage or {}).get("completion_tokens") or 0)
        self.prompt_tokens += pt
        self.completion_tokens += ct
        if get_price(self.model) is None and (pt or ct):
            self.unknown_price = True
        self.cost_usd += compute_cost_usd(self.model, pt, ct)

    def snapshot(self) -> dict[str, Any]:
        """Immutable view; subtract two snapshots to attribute a work unit."""
        return {
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "wall_ms_total": round(self.wall_ms_total, 3),
            "latencies_ms": list(self.latencies_ms),
            "unknown_price": self.unknown_price,
        }


def delta_snapshot(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Subtract two snapshots to get usage for the work between them.

    `latencies_ms` is the suffix list; tokens/cost/wall are scalar deltas.
    """
    bl = before.get("latencies_ms", [])
    al = after.get("latencies_ms", [])
    lat = al[len(bl) :] if len(al) >= len(bl) else list(al)
    return {
        "model": after.get("model"),
        "calls": int(after.get("calls", 0)) - int(before.get("calls", 0)),
        "prompt_tokens": int(after.get("prompt_tokens", 0)) - int(before.get("prompt_tokens", 0)),
        "completion_tokens": int(after.get("completion_tokens", 0)) - int(before.get("completion_tokens", 0)),
        "cost_usd": round(float(after.get("cost_usd", 0)) - float(before.get("cost_usd", 0)), 6),
        "wall_ms_total": round(
            float(after.get("wall_ms_total", 0)) - float(before.get("wall_ms_total", 0)), 3
        ),
        "latencies_ms": lat,
        "unknown_price": bool(after.get("unknown_price")),
    }


def namespace_tool(server_id: str, tool_name: str) -> str:
    """Combine server + tool into a function name the LLM sees."""
    return f"{server_id}{TOOL_NAMESPACE_SEP}{tool_name}"


def unnamespace_tool(qualified: str) -> tuple[str, str]:
    """Inverse of namespace_tool. Raises if the input is not namespaced."""
    if TOOL_NAMESPACE_SEP not in qualified:
        raise ValueError(f"tool name not namespaced: {qualified!r}")
    server_id, tool_name = qualified.rsplit(TOOL_NAMESPACE_SEP, 1)
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
                        "parameters": s.input_schema or {"type": "object", "properties": {}},
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
        base_url: str | None = None,
        app_title: str = "DynamicMCPBench",
        app_url: str = "https://github.com/jrzkaminski/DynamicMCPBench",
    ) -> None:
        _load_env_once()
        # Auto-resolve the provider for `model` when caller didn't pin both.
        # Free-pool ids (deepseek-v4-pro, kimi-k2p*, glm-5p1, gpt-oss-120b,
        # minimax-m2p7) route to FREE_MODELS_BASE_URL + FREE_MODELS_API_KEY;
        # everything else stays on OpenRouter. See dmcp/providers.py.
        if api_key is None or base_url is None:
            from dmcp.providers import endpoint_for, resolve

            resolved_url, resolved_key = endpoint_for(resolve(model))
            base_url = base_url or resolved_url
            api_key = api_key or resolved_key
        self.model = model
        self.usage = UsageAccumulator(model=model)
        self._client = AsyncOpenAI(
            api_key=api_key,
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

        t0 = time.monotonic()
        completion = await self._client.chat.completions.create(**kwargs)
        wall_ms = (time.monotonic() - t0) * 1000.0
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
        self.usage.add(usage_dict, wall_ms)

        return ChatResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage_dict,
            raw=completion.model_dump(mode="json"),
            wall_ms=wall_ms,
        )

    async def embed(self, texts: list[str], *, model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
        """Embed texts via OpenRouter's OpenAI-compatible embeddings endpoint.

        Same key/base_url as chat. Model pinned for reproducibility (embeddings
        are deterministic per snapshot). Returns one vector per input text.
        """
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]
