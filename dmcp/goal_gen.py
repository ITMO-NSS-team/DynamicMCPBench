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

import asyncio
import json
import logging
import random
from itertools import combinations
from typing import Any

from dmcp.goals import GoalEntry, Goals
from dmcp.llm import OpenRouterClient
from dmcp.manifest import Manifest, ServerEntry
from dmcp.personas import select_personas
from dmcp.recorder import TraceRecorder
from dmcp.sampling import VALID_STRATEGIES, ToolCatalog, ToolEntry, sample_distractors
from dmcp.spec import ToolReference
from dmcp.trace import ToolSpec

log = logging.getLogger(__name__)

GOAL_GEN_VERSION = "0.1.0"

GOAL_GEN_SYSTEM = """You are designing realistic user goals for an MCP-agent benchmark.

You will be shown one or more MCP servers, each with:
  - server_id (use this exact string in `servers`)
  - dynamism class (static / live_read / stateful_write)
  - sandbox_resources: a list of concrete resources we HAVE actually set up
    for this server (paths, file specs, env-provided IDs). Empty means we
    have set up nothing — design the goal around discovery/exploration of
    whatever the tools expose by default.
  - tool surface: name + short description + input schema

Your job: call `emit_goals` exactly once with N realistic user goals that
exercise these servers. Hard rules:

  1. Each goal is a natural-language request a real user might make. Do NOT
     write "call tool X with args Y" — write the request the user would
     actually voice.

  2. Each goal must be solvable using ONLY the servers shown. Do not
     reference tools or capabilities that aren't in the provided surface.

  3. NEVER INVENT concrete external resources. This is the most common
     failure mode. Specifically:
       - DO NOT invent file paths (e.g. /tmp/contract.docx, ~/data/foo.json)
         unless the exact path appears in sandbox_resources.
       - DO NOT invent IDs, wallet addresses, API keys, account numbers,
         user names, or order numbers. These are not real and the tool
         call will fail.
       - DO NOT invent URLs except for well-known public sites
         (example.com, iana.org, wikipedia.org).
     If sandbox_resources is empty and you'd otherwise need to invent a
     resource, design the goal around DISCOVERY instead: "list the tables",
     "what categories does this expose", "describe the schema". Such goals
     work without external resources and still exercise the tool surface.

  4. When sandbox_resources is non-empty, use those exact strings verbatim
     in the goal — paths and IDs the agent will need.

  5. Vary complexity: include a mix of single-call and multi-step goals
     (2-5 successful tool calls is the sweet spot).

  6. For stateful_write servers WITH sandbox_resources, prefer goals that
     produce verifiable effects (created records, written files, new
     branches) using only the provided resources. For stateful_write servers
     WITHOUT sandbox_resources, prefer read-only / discovery-shaped goals —
     don't invent new resource names to write into.

  7. For cross-server goals, design genuine data dependencies — the
     output of one server's call must feed another's input or be
     summarized with it. A goal that "uses both" but each call is
     independent is weak; reject that shape.

  8. Avoid destructive operations (drop / delete / reset) unless the task
     is explicitly an undo or recovery scenario.

  9. Choose tags from:
     ['shallow','single-server','cross-server','deep','runtime-branching',
      'recovery','read-only-usage','parallel-calls','discovery']
""".strip()


# Argument flags whose value is a usable concrete resource.
_RESOURCE_ARG_FLAGS = {
    "--repository",
    "--repo",
    "--db-path",
    "--database",
    "--db",
    "--path",
    "--root",
    "--workspace",
    "--data-dir",
    "--config",
    "--file",
    "--input",
    "--output-dir",
    "--local-timezone",
}

# Env variable name → "kind" hint shown to the LLM.
_RESOURCE_ENV_HINTS = {
    "MEMORY_FILE_PATH": "knowledge-graph file path",
    "DATABASE_URI": "database connection string",
    "DATABASE_URL": "database connection string",
    "WORKSPACE_PATH": "workspace path",
    "DATA_DIR": "data directory",
}


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


def _extract_sandbox_resources(entry: ServerEntry) -> list[dict[str, str]]:
    """Pull concrete resources we know exist for this server, for the LLM.

    Walks `args` looking for `--flag value` pairs whose flag is in our
    known resource-flag set, then any env vars whose name is in the
    resource-env hint set. Returns [{"kind": ..., "value": ...}, ...].
    """
    resources: list[dict[str, str]] = []
    args = list(entry.args or [])
    i = 0
    while i < len(args):
        a = args[i]
        if isinstance(a, str) and a in _RESOURCE_ARG_FLAGS and i + 1 < len(args):
            v = args[i + 1]
            if isinstance(v, str):
                resources.append({"kind": a.lstrip("-"), "value": v})
            i += 2
            continue
        if isinstance(a, str) and a.startswith("/") and len(a) > 1:
            resources.append({"kind": "path", "value": a})
        i += 1
    for env_name, kind_hint in _RESOURCE_ENV_HINTS.items():
        v = (entry.env or {}).get(env_name)
        if v:
            resources.append({"kind": kind_hint, "value": v})
    return resources


def _server_view(entry: ServerEntry, specs: list[ToolSpec]) -> dict[str, Any]:
    return {
        "server_id": entry.server_id,
        "dynamism": entry.dynamism.value,
        "sandbox": entry.sandbox,
        "sandbox_resources": _extract_sandbox_resources(entry),
        "description": entry.description,
        "tools": _tool_view(specs),
    }


async def _fetch_tool_specs(entry: ServerEntry, *, timeout_s: float = 25.0) -> list[ToolSpec]:
    """Open a stdio session just long enough to capture the tool surface."""
    cfg = entry.to_config()
    rec = TraceRecorder(servers=[cfg], goal=f"goal-gen:{entry.server_id}")

    async def _do() -> list[ToolSpec]:
        async with rec:
            return list(rec.trace.tool_specs.get(entry.server_id, []))

    return await asyncio.wait_for(_do(), timeout=timeout_s)


async def _ask_for_goals(
    llm: OpenRouterClient,
    server_views: list[dict[str, Any]],
    n_goals: int,
    scope_label: str,
    personas: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    persona_block = ""
    if personas:
        listed = "\n".join(f"  - {p['label']}: {p['intent']}" for p in personas)
        persona_block = (
            "\n\nAdopt a DISTINCT user persona/intent for each goal — vary them across "
            "the goals, drawn from this set. Do NOT name the persona in the goal text; "
            f"just let it shape what the user asks for:\n{listed}"
        )
    messages = [
        {"role": "system", "content": GOAL_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Generate {n_goals} goal(s) for this {scope_label}.\n\n"
                "Servers and tool surfaces:\n"
                f"```json\n{json.dumps(server_views, indent=2, default=str)}\n```"
                f"{persona_block}\n\n"
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
    use_personas: bool = True,
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
                llm,
                view,
                single_per_server,
                f"single server '{sid}'",
                personas=select_personas(single_per_server, seed) if use_personas else None,
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
                llm,
                view,
                1,
                f"cross-server pair '{a} + {b}'",
                personas=select_personas(1, seed) if use_personas else None,
            )
        except Exception as e:
            log.warning("goal-gen for pair (%s, %s) failed: %s", a, b, e)
            continue
        for g in raw_goals:
            gid = _sanitize_goal_id(str(g.get("goal_id") or "auto"), prefix=f"auto-x-{a}-{b}-")
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


async def _capture_surfaces(
    manifest: Manifest, server_ids: list[str]
) -> tuple[dict[str, list[ToolSpec]], dict[str, ServerEntry]]:
    """Boot each server once and capture its tool surface (shared first pass)."""
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
            continue
        surfaces[sid] = specs
        entries[sid] = entry
    return surfaces, entries


async def generate_strategy_goals(
    *,
    manifest: Manifest,
    server_ids: list[str],
    llm: OpenRouterClient,
    strategy: str,
    n_goals: int,
    seed_set_size: int = 4,
    seed: int = 0,
    use_personas: bool = True,
) -> Goals:
    """Strategy-driven goal seeding (E6.1). Reuse the eval-side sampler to pick a SEED
    tool-set by RELATIONSHIP (random / hard_neg / cross_domain / same_name / sibling /
    stratified), then ask the LLM for a realistic human goal exercising exactly those
    tools. Only the seed is strategy-controlled; the explorer still explores forward, so
    the headline stays trace-native."""
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; pick from {VALID_STRATEGIES}")
    surfaces, entries = await _capture_surfaces(manifest, server_ids)
    if not surfaces:
        return Goals(entries=[])
    catalog = ToolCatalog(
        entries=[
            ToolEntry(
                server_id=sid,
                tool_name=ts.name,
                description=(ts.description or ""),
                tags=tuple(entries[sid].tags),
            )
            for sid, specs in surfaces.items()
            for ts in specs
        ]
    )
    all_tools = [(sid, ts) for sid, specs in surfaces.items() for ts in specs]
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[GoalEntry] = []
    for i in range(n_goals):
        if not all_tools:
            break
        anchor_sid, anchor_ts = rng.choice(all_tools)
        anchor = ToolReference(server_id=anchor_sid, tool_name=anchor_ts.name)
        related = sample_distractors(strategy, [anchor], catalog, n=max(1, seed_set_size - 1), seed=seed + i)
        seed_pairs = [(anchor_sid, anchor_ts.name)] + [(e.server_id, e.tool_name) for e in related]
        by_server: dict[str, set[str]] = {}
        for sid, tname in seed_pairs:
            by_server.setdefault(sid, set()).add(tname)
        views = [
            _server_view(entries[sid], [ts for ts in surfaces[sid] if ts.name in tnames])
            for sid, tnames in by_server.items()
        ]
        scope = "intra-server" if len(by_server) == 1 else "cross-server"
        label = (
            f"{strategy} seed set ({scope}) — design ONE realistic single-turn user goal that "
            "genuinely REQUIRES using these specific tools (chain output->input where natural), "
            "without naming the tools: " + ", ".join(f"{s}::{t}" for s, t in seed_pairs)
        )
        try:
            raw = await _ask_for_goals(
                llm,
                views,
                1,
                label,
                personas=select_personas(1, seed + i) if use_personas else None,
            )
        except Exception as e:
            log.warning("strategy goal-gen (%s) failed: %s", strategy, e)
            continue
        for gd in raw:
            gid = _ensure_unique(
                _sanitize_goal_id(str(gd.get("goal_id") or "auto"), prefix=f"auto-{strategy}-"), seen
            )
            seen.add(gid)
            servers = [s for s in (gd.get("servers") or list(by_server)) if s in surfaces] or list(by_server)
            tags = list(gd.get("tags") or [])
            for t in (f"strategy:{strategy}", scope):
                if t not in tags:
                    tags.append(t)
            try:
                out.append(
                    GoalEntry(goal_id=gid, goal=str(gd.get("goal", "")).strip(), servers=servers, tags=tags)
                )
            except Exception as e:
                log.warning("malformed strategy goal %r: %s", gd, e)
    return Goals(entries=out)
