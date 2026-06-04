"""Goal-seeded forward exploration agent (Phase 2A of the rev. 3 plan).

The explorer is what replaces AGB's "sample a subgraph and back-instruct a
question." Instead, it:

  1. opens one or more live MCP servers via the recorder
  2. namespaces the tool surface as OpenAI function schemas
  3. asks an LLM to pursue a goal by chaining tool calls
  4. executes each tool call through the recorder so the full trajectory is
     captured in a Trace
  5. returns when the LLM stops calling tools, hits the step budget, or fails

The Trace is the deliverable. Whether the explored trajectory is *interesting
enough* to become a task (≥2 tools, genuine data dependency, etc.) is the
distiller's call, not the explorer's. Keep this layer narrow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from dmcp.llm import (
    OpenRouterClient,
    delta_snapshot,
    namespace_tool,
    specs_to_openai_tools,
)
from dmcp.recorder import ServerConfig, TraceRecorder
from dmcp.trace import ToolSpec, Trace

DEFAULT_SYSTEM_PROMPT = """You are an exploration agent driving MCP tools to satisfy a user goal.

Rules:
- Call tools to make progress. Do not invent results — use the tools.
- Each tool name is namespaced as `<server_id>__<tool_name>`. Use exactly that form.
- When the goal is satisfied, respond with a short natural-language summary and stop calling tools.
- If a tool errors, read the error, adjust arguments, and try again. Do not give up after one failure.
- Prefer the simplest sequence of calls that achieves the goal.
""".strip()

DEFAULT_BUDGET = 12
DEFAULT_TOOL_RESULT_TRUNCATION = 8000


@dataclass
class ExplorationResult:
    trace: Trace
    outcome: str  # "completed" | "budget_exhausted" | "llm_error" | "no_tools_called"
    tool_call_count: int
    successful_tool_calls: int
    final_message: str | None
    messages: list[dict[str, Any]] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)


def _truncate(s: str, n: int) -> tuple[str, bool]:
    if len(s) <= n:
        return s, False
    return s[:n] + f"\n…[truncated {len(s) - n} chars]", True


def _tool_result_to_str(result: dict[str, Any], max_chars: int) -> tuple[str, bool]:
    """Render an MCP CallToolResult dict as the string the LLM will read.

    MCP CallToolResult typically carries `content: [{type: text, text: ...}, ...]`.
    Concatenate any text parts; fall back to a JSON dump otherwise.
    """
    parts: list[str] = []
    for c in result.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    rendered = "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
    if result.get("isError"):
        rendered = f"[tool error] {rendered}"
    return _truncate(rendered, max_chars)


async def explore(
    *,
    goal: str,
    servers: list[ServerConfig] | None = None,
    recorder: Any = None,
    llm: OpenRouterClient,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    budget: int = DEFAULT_BUDGET,
    persona: str | None = None,
    extra_seed: dict[str, Any] | None = None,
    tool_result_truncation: int = DEFAULT_TOOL_RESULT_TRUNCATION,
    tool_surface: dict[str, list[ToolSpec]] | None = None,
) -> ExplorationResult:
    """Run one goal-seeded exploration session and return a Trace + summary.

    Pass either `servers=` (constructs a live TraceRecorder) OR `recorder=`
    (use a pre-built recorder, e.g. TraceReplayRecorder for deterministic
    evaluation). Exactly one of the two must be set.
    """
    if (servers is None) == (recorder is None):
        raise ValueError("explore() requires exactly one of `servers` or `recorder`")

    seed_metadata: dict[str, Any] = {
        "explorer_version": "0.1.0",
        "llm_model": llm.model,
        "budget": budget,
    }
    if persona:
        seed_metadata["persona"] = persona
    if extra_seed:
        seed_metadata.update(extra_seed)

    if recorder is None:
        recorder = TraceRecorder(servers=servers, goal=goal, seed_metadata=seed_metadata)
    else:
        # Caller-supplied recorder: merge our exploration metadata into its
        # existing seed_metadata without clobbering.
        for k, v in seed_metadata.items():
            recorder.trace.seed_metadata.setdefault(k, v)
        if recorder.trace.goal is None:
            recorder.trace.goal = goal

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal},
    ]
    if persona:
        messages.insert(1, {"role": "system", "content": f"Persona: {persona}"})

    outcome = "budget_exhausted"
    final_message: str | None = None
    tool_call_count = 0
    successful_tool_calls = 0
    usage_before = llm.usage.snapshot()

    async with recorder:
        openai_tools = specs_to_openai_tools(
            tool_surface if tool_surface is not None else recorder.trace.tool_specs
        )
        valid_qualified = {t["function"]["name"] for t in openai_tools}

        for _ in range(budget):
            try:
                resp = await llm.chat(messages=messages, tools=openai_tools)
            except Exception as e:
                outcome = "llm_error"
                final_message = f"{type(e).__name__}: {e}"
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": resp.content or "",
            }
            if resp.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": namespace_tool(tc.server_id, tc.tool_name)
                            if tc.server_id
                            else tc.tool_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in resp.tool_calls
                ]
            messages.append(assistant_msg)

            if not resp.tool_calls:
                outcome = "completed" if tool_call_count > 0 else "no_tools_called"
                final_message = resp.content
                break

            for tc in resp.tool_calls:
                tool_call_count += 1
                qualified = namespace_tool(tc.server_id, tc.tool_name) if tc.server_id else tc.tool_name
                if qualified not in valid_qualified or not tc.server_id:
                    err = f"unknown tool {qualified!r}. Valid: {sorted(valid_qualified)[:20]}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    continue
                try:
                    raw_result = await recorder.call_tool(tc.server_id, tc.tool_name, tc.arguments)
                    rendered, _ = _tool_result_to_str(raw_result, tool_result_truncation)
                    if not raw_result.get("isError"):
                        successful_tool_calls += 1
                except Exception as e:
                    rendered = f"[exception] {type(e).__name__}: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": rendered})

    cost = delta_snapshot(usage_before, llm.usage.snapshot())
    return ExplorationResult(
        trace=recorder.trace,
        outcome=outcome,
        tool_call_count=tool_call_count,
        successful_tool_calls=successful_tool_calls,
        final_message=final_message,
        messages=messages,
        cost=cost,
    )


def stash_exploration_in_trace(result: ExplorationResult) -> None:
    """Attach explorer-side metadata to the trace's seed_metadata.

    Kept separate from the explorer body because the trace primitive itself is
    deliberately ignorant of LLM message history — but the distiller will want
    it, so we tuck it under seed_metadata.exploration.
    """
    result.trace.seed_metadata["exploration"] = {
        "outcome": result.outcome,
        "tool_call_count": result.tool_call_count,
        "successful_tool_calls": result.successful_tool_calls,
        "final_message": result.final_message,
        "messages": result.messages,
    }
    if result.cost:
        result.trace.seed_metadata["cost"] = result.cost
