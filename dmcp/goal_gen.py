"""Automated goal generation from server tool surfaces.

At one server it's fine to hand-author `goals.json`. At a hundred you
need an automated path: feed the manifest into an LLM and let it propose
realistic user goals per server (and selected cross-server pairs).

The LLM is constrained via a tool-call schema (`emit_goals`) so output is
structured, not free-form text. Each generated goal carries:
  - goal_id (auto-prefixed for collision-freeness)
  - goal (fuzzy natural-language user request)
  - servers (list[str]) — exactly the servers the goal will exercise
  - tags

The output `Goals` object is the same one consumed by `dmcp generate`,
so the generated goals feed straight into the existing pipeline.

Out of scope for v0:
  - Persona seeding (rev. 3 plan calls for this; today the prompt just
    asks for "realistic user requests")
  - Goal quality filtering (rev. 3 plan calls for LLM critic; today we
    trust the generator)
  - Goal de-duplication beyond goal_id uniqueness
"""

from __future__ import annotations

import json
import logging
import random
from itertools import combinations
from typing import Any

from dmcp.goals import GoalEntry, Goals
from dmcp.llm import OpenRouterClient
from dmcp.manifest import Manifest, ServerEntry
from dmcp.recorder import TraceRecorder
from dmcp.trace import ToolSpec

log = logging.getLogger(__name__)

GOAL_GEN_VERSION = "0.1.0"

GOAL_GEN_SYSTEM = """You are designing realistic user goals for an MCP-agent benchmark.

You will be shown one or more MCP servers, each with:
  - server_id (use this exact string in `servers`)
  - dynamism class (static / live_read / stateful_write)
  - sandbox path or relevant context, when applicable
  - tool surface: name + short description + input schema

Your job: call `emit_goals` exactly once with N realistic user goals that
exercise these servers. Hard rules:

  1. Each goal is a natural-language request a real user might make. Do NOT
     write "call tool X with args Y" — write the request the user would
     actually voice.

  2. Each goal must be solvable using ONLY the servers shown. Do not
     reference tools or capabilities that aren't in the provided surface.

  3. Include concrete context the agent needs to act on: sandbox paths,
     file names, URLs, identifiers. A goal that mentions "the database"
     without saying which path / which table is unsolvable at eval time.

  4. Vary complexity: include a mix of single-call and multi-step goals
     (2-5 successful tool calls is the sweet spot).

  5. For stateful_write servers, prefer goals that produce verifiable
     effects (created records, written files, new branches). Avoid
     destructive operations (drop / delete / reset) unless the task is
     explicitly an undo or recovery scenario.

  6. For cross-server goals, design genuine data dependencies — the
     output of one server's call must feed another's input or be
     summarized with it. A goal that "uses both" but each call is
     independent is weak; reject that shape.

  7. Choose tags from:
     ['shallow','single-server','cross-server','deep','runtime-branching',
      'recovery','read-only-usage','parallel-calls']
""".strip()


def _emit_goals_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_goals",
            "description": "Emit a list of generated goals.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["goals"],
                "properties": {
                    "goals": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["goal_id", "goal", "servers"],
                            "properties": {
                                "goal_id": {
                                    "type": "string",
                                    "description": (
                                        "Short kebab-case identifier; will be prefixed "
                                        "with 'auto-' if not already."
                                    ),
                                },
                                "goal": {"type": "string"},
                                "servers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def _tool_view(specs: list[ToolSpec], max_tools: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in specs[:max_tools]:
        out.append(
            {
                "name": t.name,
                "description": (t.description or "")[:240],
                "input_schema": t.input_schema or {},
            }
        )
    if len(specs) > max_tools:
        out.append({"_note": f"and {len(specs) - max_tools} more tools elided"})
    return out


def _server_view(
    entry: ServerEntry, specs: list[ToolSpec]
) -> dict[str, Any]:
    sandbox_path: str | None = None
    for arg in entry.args:
        if isinstance(arg, str) and arg.startswith("/"):
            sandbox_path = arg
            break
    return {
        "server_id": entry.server_id,
        "dynamism": entry.dynamism.value,
        "sandbox": entry.sandbox,
        "sandbox_path": sandbox_path,
        "description": entry.description,
        "tools": _tool_view(specs),
    }


async def _fetch_tool_specs(entry: ServerEntry) -> list[ToolSpec]:
    """Open a stdio session just long enough to capture the tool surface."""
    cfg = entry.to_config()
    rec = TraceRecorder(servers=[cfg], goal=f"goal-gen:{entry.server_id}")
    async with rec:
        return list(rec.trace.tool_specs.get(entry.server_id, []))


async def _ask_for_goals(
    llm: OpenRouterClient,
    server_views: list[dict[str, Any]],
    n_goals: int,
    scope_label: str,
) -> list[dict[str, Any]]:
    messages = [
        {"role": "system", "content": GOAL_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Generate {n_goals} goal(s) for this {scope_label}.\n\n"
                "Servers and tool surfaces:\n"
                f"```json\n{json.dumps(server_views, indent=2, default=str)}\n```\n\n"
                "Call `emit_goals` exactly once."
            ),
        },
    ]
    resp = await llm.chat(
        messages=messages,
        tools=[_emit_goals_tool_schema()],
        tool_choice={"type": "function", "function": {"name": "emit_goals"}},
        temperature=0.3,
        max_tokens=4096,
    )
    if not resp.tool_calls:
        log.warning("LLM did not call emit_goals (scope=%s, content=%r)", scope_label, resp.content)
        return []
    args = resp.tool_calls[0].arguments
    return list(args.get("goals") or [])


def _sanitize_goal_id(raw: str, prefix: str) -> str:
    base = raw.strip().lower().replace(" ", "-").replace("_", "-")
    base = "".join(c if (c.isalnum() or c == "-") else "" for c in base) or "goal"
    if not base.startswith(prefix):
        base = f"{prefix}{base}"
    return base[:80]


def _ensure_unique(goal_id: str, seen: set[str]) -> str:
    if goal_id not in seen:
        return goal_id
    i = 2
    while f"{goal_id}-{i}" in seen:
        i += 1
    return f"{goal_id}-{i}"


async def generate_goals(
    *,
    manifest: Manifest,
    server_ids: list[str],
    llm: OpenRouterClient,
    single_per_server: int = 2,
    cross_pairs: int = 5,
    seed: int = 0,
) -> Goals:
    """Generate goals for the requested servers.

    Returns a Goals object: `single_per_server` goals per server, plus
    `cross_pairs` cross-server goals over randomly chosen distinct pairs of
    stateful_write+read-capable servers.
    """
    if not server_ids:
        return Goals(entries=[])

    # First pass: capture each server's tool surface (one open per server).
    surfaces: dict[str, list[ToolSpec]] = {}
    entries: dict[str, ServerEntry] = {}
    for sid in server_ids:
        try:
            entry = manifest.by_id(sid)
        except KeyError:
            log.warning("server %r not in manifest; skipping", sid)
            continue
        try:
            specs = await _fetch_tool_specs(entry)
        except Exception as e:
            log.warning("could not capture tool surface for %s: %s", sid, e)
            continue
        if not specs:
            log.warning("server %s exposes no tools; skipping", sid)
            continue
        surfaces[sid] = specs
        entries[sid] = entry

    seen_ids: set[str] = set()
    out_entries: list[GoalEntry] = []

    # Per-server generation.
    for sid in list(surfaces.keys()):
        view = [_server_view(entries[sid], surfaces[sid])]
        try:
            raw_goals = await _ask_for_goals(
                llm, view, single_per_server, f"single server '{sid}'"
            )
        except Exception as e:
            log.warning("goal-gen for server %s failed: %s", sid, e)
            continue
        for g in raw_goals:
            gid = _sanitize_goal_id(str(g.get("goal_id") or "auto"), prefix=f"auto-{sid}-")
            gid = _ensure_unique(gid, seen_ids)
            seen_ids.add(gid)
            servers = g.get("servers") or [sid]
            servers = [s for s in servers if s in surfaces]
            if not servers:
                continue
            tags = list(g.get("tags") or [])
            if "single-server" not in tags and len(servers) == 1:
                tags.append("single-server")
            try:
                out_entries.append(
                    GoalEntry(
                        goal_id=gid,
                        goal=str(g.get("goal", "")).strip(),
                        servers=servers,
                        tags=tags,
                    )
                )
            except Exception as e:
                log.warning("malformed generated goal %r: %s", g, e)

    # Cross-server pairs.
    sids_for_pairs = list(surfaces.keys())
    pairs_pool = list(combinations(sids_for_pairs, 2))
    rng = random.Random(seed)
    rng.shuffle(pairs_pool)
    for a, b in pairs_pool[:cross_pairs]:
        view = [_server_view(entries[a], surfaces[a]), _server_view(entries[b], surfaces[b])]
        try:
            raw_goals = await _ask_for_goals(
                llm, view, 1, f"cross-server pair '{a} + {b}'"
            )
        except Exception as e:
            log.warning("goal-gen for pair (%s, %s) failed: %s", a, b, e)
            continue
        for g in raw_goals:
            gid = _sanitize_goal_id(
                str(g.get("goal_id") or "auto"), prefix=f"auto-x-{a}-{b}-"
            )
            gid = _ensure_unique(gid, seen_ids)
            seen_ids.add(gid)
            servers = g.get("servers") or [a, b]
            servers = [s for s in servers if s in surfaces]
            if not servers:
                continue
            tags = list(g.get("tags") or [])
            if "cross-server" not in tags and len(servers) > 1:
                tags.append("cross-server")
            try:
                out_entries.append(
                    GoalEntry(
                        goal_id=gid,
                        goal=str(g.get("goal", "")).strip(),
                        servers=servers,
                        tags=tags,
                    )
                )
            except Exception as e:
                log.warning("malformed generated cross goal %r: %s", g, e)

    return Goals(entries=out_entries)
