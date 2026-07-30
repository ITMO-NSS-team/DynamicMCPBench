"""Refresh preflight — check a task's environment before it is readmitted (Phase 4B).

`dmcp refresh` re-executes a spec's reference trace live and classifies every
call as identical / drifted / broken. That classification quietly assumes the
environment the task needs is still there. When it isn't — a fixture file
deleted, a sandbox table never seeded, an API key rotated out of `.env`, a write
target on a read-only mount — every reference call fails, the spec is recorded
as broken, and once it is readmitted every candidate agent fails it too. The
benchmark then reports our own broken setup as server decay and as agent
failure. Both numbers are wrong, and neither is recoverable after the fact.

Preflight separates that case out. It derives the preconditions a reference
trace depends on, checks the ones it can check, and reports what is unmet. A
task with an unmet precondition is **quarantined** by `dmcp.refresh`: no live
calls are made, nothing enters the decay tally, and nothing is charged to an
agent.

Requirement kinds:
  credential — env var names the server declares in `requires_env` (presence
               only; validity is the server's business).
  file       — an absolute path a read call consumed; must still exist.
  writable   — an absolute path a `stateful_write` call targeted; the file, or
               its parent directory when the file does not exist yet, must be
               writable.
  table      — a relation named by a `table`-ish argument or by SQL text.
               Confirming one needs the server, so it is checked against an
               inventory from `discover_tables` and reported `unknown` when no
               inventory is available.

Scope of v0: local, deterministic checks plus a read-only table probe. The
requirements themselves are derived from argument names and value shapes — a
heuristic, deliberately biased toward *not* claiming a requirement it cannot
justify, because a false quarantine silently shrinks the benchmark while a
missed one only leaves today's behaviour. Two consequences of that bias are
load-bearing: relative paths are never claimed (they depend on a working
directory we do not control at refresh time), and `unknown` never quarantines.
Out of scope: server reachability (that is refresh's own job), credential
validity, and inferring requirements from the goal prose.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dmcp.manifest import Dynamism, Manifest
from dmcp.trace import StepKind, StepStatus, Trace

PREFLIGHT_VERSION = "0.1.0"

RequirementKind = Literal["credential", "file", "writable", "table"]
FindingStatus = Literal["satisfied", "unmet", "unknown"]

# Argument names that make a string value a candidate path / relation. Matched
# as substrings of the lowercased key, so `output_path` and `src_file` hit.
PATH_ARG_HINTS = ("path", "file", "dir", "folder", "source", "destination", "target")
TABLE_ARG_HINTS = ("table", "relation")
SQL_ARG_HINTS = ("query", "sql", "statement")

# Relations named directly by SQL. Deliberately narrow: it recognises the four
# clauses that name a base relation and nothing else, so a CTE or a subquery
# yields no requirement rather than a wrong one.
_SQL_TABLE_RE = re.compile(
    r"\b(?:from|join|into|update)\s+[`\"\[]?([a-z_][a-z0-9_.]*)[`\"\]]?",
    re.IGNORECASE,
)

# Read-only listing tools we know how to ask for a relation inventory.
TABLE_LIST_TOOLS = ("list_tables", "show_tables", "get_tables", "list_relations")


class Requirement(BaseModel):
    """One precondition a reference trace depends on."""

    model_config = ConfigDict(extra="forbid")

    kind: RequirementKind
    target: str
    server_id: str
    # Why we believe this is required — quoted back in the quarantine reason so
    # a maintainer can tell a real missing fixture from a bad inference.
    origin: str


class PreflightFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: Requirement
    status: FindingStatus
    detail: str


class PreflightResult(BaseModel):
    """Findings for one task, plus the quarantine verdict they imply."""

    model_config = ConfigDict(extra="forbid")

    preflight_version: str = PREFLIGHT_VERSION
    findings: list[PreflightFinding] = Field(default_factory=list)

    @property
    def unmet(self) -> list[PreflightFinding]:
        return [f for f in self.findings if f.status == "unmet"]

    @property
    def ok(self) -> bool:
        """True when nothing is known to be missing. `unknown` does not block."""
        return not self.unmet

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for f in self.findings if f.status == s) for s in ("satisfied", "unmet", "unknown")}

    def summary(self) -> str:
        if self.ok:
            c = self.counts()
            return f"preflight ok ({c['satisfied']} satisfied, {c['unknown']} unknown)"
        parts = [f"{f.requirement.kind} {f.requirement.target} ({f.detail})" for f in self.unmet]
        return f"preflight unmet: {'; '.join(parts)}"


def _is_absolute_path(value: str) -> bool:
    """Only absolute (or `~`-anchored) paths are claimed as requirements.

    A relative path is resolved against whatever directory the refresh happens
    to run in, so checking one would quarantine on our own cwd rather than on
    the task's environment.
    """
    if not value or "://" in value or "\n" in value:
        return False
    return value.startswith("~") or Path(value).is_absolute()


def _expand(value: str) -> Path:
    return Path(value).expanduser()


def _string_args(arguments: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten arguments to (key, string value) pairs, one level into lists."""
    pairs: list[tuple[str, str]] = []
    for key, value in arguments.items():
        if isinstance(value, str):
            pairs.append((key, value))
        elif isinstance(value, list):
            pairs.extend((key, v) for v in value if isinstance(v, str))
    return pairs


def _sql_tables(text: str) -> list[str]:
    return [m.group(1).lower() for m in _SQL_TABLE_RE.finditer(text)]


def derive_requirements(reference: Trace, manifest: Manifest) -> list[Requirement]:
    """Read a reference trace's successful calls for the environment they assume.

    Deduplicated on (kind, server, target) and returned in a stable order so two
    runs over the same trace produce the same quarantine reason.
    """
    seen: dict[tuple[str, str, str], Requirement] = {}

    def add(kind: RequirementKind, target: str, server_id: str, origin: str) -> None:
        seen.setdefault(
            (kind, server_id, target),
            Requirement(kind=kind, target=target, server_id=server_id, origin=origin),
        )

    for step in reference.steps:
        if step.kind is not StepKind.call_tool_agent or step.status is not StepStatus.success:
            continue
        sid = step.server_id
        try:
            entry = manifest.by_id(sid)
        except KeyError:
            # Not our server to vouch for; refresh skips it too.
            continue

        for var in entry.requires_env:
            add("credential", var, sid, f"server {sid} declares requires_env")

        tool = step.tool_name or "?"
        writes = entry.dynamism is Dynamism.stateful_write
        for key, value in _string_args(step.arguments or {}):
            low = key.lower()
            if any(h in low for h in PATH_ARG_HINTS) and _is_absolute_path(value):
                kind: RequirementKind = "writable" if writes else "file"
                add(kind, value, sid, f"{tool} argument {key!r}")
            elif any(h in low for h in TABLE_ARG_HINTS):
                add("table", value.lower(), sid, f"{tool} argument {key!r}")
            elif any(h in low for h in SQL_ARG_HINTS):
                for name in _sql_tables(value):
                    add("table", name, sid, f"{tool} argument {key!r} (SQL)")

    return sorted(seen.values(), key=lambda r: (r.kind, r.server_id, r.target))


def _check_one(req: Requirement, table_inventory: dict[str, set[str]] | None) -> PreflightFinding:
    def finding(status: FindingStatus, detail: str) -> PreflightFinding:
        return PreflightFinding(requirement=req, status=status, detail=detail)

    if req.kind == "credential":
        if os.environ.get(req.target):
            return finding("satisfied", "set in the environment")
        return finding("unmet", "not set in the environment")

    if req.kind == "file":
        path = _expand(req.target)
        if path.exists():
            return finding("satisfied", "exists")
        return finding("unmet", "no such file or directory")

    if req.kind == "writable":
        path = _expand(req.target)
        if path.exists():
            if os.access(path, os.W_OK):
                return finding("satisfied", "exists and is writable")
            return finding("unmet", "exists but is not writable")
        parent = path.parent
        if not parent.is_dir():
            return finding("unmet", f"parent directory {parent} does not exist")
        if os.access(parent, os.W_OK):
            return finding("satisfied", f"parent directory {parent} is writable")
        return finding("unmet", f"parent directory {parent} is not writable")

    inventory = (table_inventory or {}).get(req.server_id)
    if inventory is None:
        return finding("unknown", f"no relation inventory for {req.server_id}")
    # A qualified name matches on its last segment: the probe reports bare
    # relation names, the SQL may carry a schema.
    if req.target in inventory or req.target.rsplit(".", 1)[-1] in inventory:
        return finding("satisfied", "present on the server")
    return finding("unmet", f"not among the {len(inventory)} relation(s) the server reports")


def check_requirements(
    requirements: list[Requirement],
    *,
    table_inventory: dict[str, set[str]] | None = None,
    load_env: bool = True,
) -> PreflightResult:
    """Evaluate derived requirements. Loads `.env` first, as `gate_credentials` does."""
    if load_env and any(r.kind == "credential" for r in requirements):
        with contextlib.suppress(Exception):
            from dotenv import load_dotenv

            load_dotenv(override=False)
    return PreflightResult(findings=[_check_one(r, table_inventory) for r in requirements])


def run_preflight(
    reference: Trace,
    manifest: Manifest,
    *,
    table_inventory: dict[str, set[str]] | None = None,
    load_env: bool = True,
) -> PreflightResult:
    """Derive and check in one call — the entry point `dmcp.refresh` uses."""
    return check_requirements(
        derive_requirements(reference, manifest),
        table_inventory=table_inventory,
        load_env=load_env,
    )


def parse_relation_names(text: str) -> set[str]:
    """Pull relation names out of a listing tool's text result.

    Accepts a JSON array of names, a JSON array of objects carrying a name-ish
    key, or one name per line / comma-separated. Anything else yields an empty
    set, which downgrades the check to `unknown` rather than failing it.
    """
    text = text.strip()
    if not text:
        return set()
    with contextlib.suppress(Exception):
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ("tables", "relations", "result", "rows"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
        if isinstance(parsed, list):
            names: set[str] = set()
            for item in parsed:
                if isinstance(item, str):
                    names.add(item.strip().lower())
                elif isinstance(item, dict):
                    for key in ("name", "table", "table_name", "relation"):
                        if isinstance(item.get(key), str):
                            names.add(item[key].strip().lower())
                            break
            if names:
                return names
    tokens = re.split(r"[\n,]+", text)
    return {t.strip().strip("\"'`| ").lower() for t in tokens if t.strip()} - {""}


async def discover_tables(recorder: Any, server_ids: list[str]) -> dict[str, set[str]]:
    """Best-effort read-only relation inventory, one entry per server that answers.

    A server that exposes no listing tool, or whose listing call fails, is left
    out of the mapping entirely — its table requirements then read `unknown`,
    which is the honest answer and does not quarantine.
    """
    inventory: dict[str, set[str]] = {}
    for sid in server_ids:
        try:
            tools = await recorder.list_tools(sid)
            names = {getattr(t, "name", "") for t in tools}
        except Exception:
            continue
        probe = next((t for t in TABLE_LIST_TOOLS if t in names), None)
        if probe is None:
            continue
        try:
            result = await recorder.call_tool(sid, probe, {})
        except Exception:
            continue
        if not isinstance(result, dict) or result.get("isError"):
            continue
        texts = [
            c.get("text", "")
            for c in (result.get("content") or [])
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        relations = parse_relation_names("\n".join(texts))
        if relations:
            inventory[sid] = relations
    return inventory
