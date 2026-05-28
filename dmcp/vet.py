"""Vet installed servers: smoke MCP initialize+list_tools, classify dynamism.

A vetted server is one we have actually talked MCP to: we know its tool
surface, its server_name/version from initialize, and a heuristic dynamism
class derived from its tool names.

The dynamism heuristic is intentionally cheap — keyword scan over tool
names. It will misclassify edge cases (a tool literally named `read_query`
in mcp-server-sqlite is actually used for stateful_write contexts), but the
manifest validator catches the worst footgun (stateful_write must be
sandboxed). LLM-based classification is a future-iteration layer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dmcp.discovery.schemas import DiscoveredServer
from dmcp.install import InstallResult, InstallStatus
from dmcp.manifest import Dynamism, ServerEntry
from dmcp.recorder import StdioServer, TraceRecorder
from dmcp.trace import TransportKind

log = logging.getLogger(__name__)

WRITE_KEYWORDS = {
    "write", "create", "insert", "update", "delete", "remove", "drop", "commit",
    "push", "send", "post", "patch", "put", "edit", "modify", "rename", "move",
    "destroy", "store", "save", "upload", "publish", "execute", "run",
}
READ_KEYWORDS = {
    "read", "get", "list", "show", "fetch", "search", "query", "find", "lookup",
    "describe", "browse", "view", "inspect", "load", "stat", "info", "head",
    "current", "now",
}
STATIC_KEYWORDS = {
    "convert", "format", "parse", "calculate", "render", "encode", "decode",
    "hash", "validate", "transform", "compute", "diff", "compare",
}

SERVER_ID_RE = re.compile(r"[^a-z0-9_]+")


def _sanitize_server_id(name: str) -> str:
    """Catalog name like `ai.adeu/adeu` → `ai_adeu__adeu`. Stable, unique, valid."""
    s = name.lower().replace("/", "__")
    s = SERVER_ID_RE.sub("_", s)
    s = s.strip("_")
    return s or "server"


def _classify_dynamism(tool_names: list[str]) -> Dynamism:
    """Coarse heuristic over tool name tokens."""
    if not tool_names:
        return Dynamism.live_read
    toks = " ".join(tool_names).lower()
    tok_set = set(re.findall(r"[a-z]+", toks))
    if tok_set & WRITE_KEYWORDS:
        return Dynamism.stateful_write
    if tok_set & READ_KEYWORDS:
        return Dynamism.live_read
    if tok_set <= (STATIC_KEYWORDS | {"time", "date", "timezone", "math", "currency"}):
        return Dynamism.static
    return Dynamism.live_read


class VetStatus(str, Enum):
    success = "success"
    initialize_failed = "initialize_failed"
    list_tools_failed = "list_tools_failed"
    timeout = "timeout"
    no_tools = "no_tools"


@dataclass
class VetResult:
    server_name: str
    server_id: str
    status: VetStatus
    reason: str = ""
    elapsed_s: float = 0.0
    server_name_reported: str | None = None
    server_version_reported: str | None = None
    protocol_version: str | None = None
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    dynamism: Dynamism | None = None
    manifest_entry: ServerEntry | None = None


async def _vet_one(
    discovered: DiscoveredServer,
    install: InstallResult,
    *,
    smoke_timeout_s: float,
) -> VetResult:
    assert install.invoke_command is not None
    server_id = _sanitize_server_id(discovered.name)
    cfg = StdioServer(
        server_id=server_id,
        command=install.invoke_command,
        args=list(install.invoke_args),
    )
    t0 = time.monotonic()
    recorder = TraceRecorder(servers=[cfg], goal=f"vet:{discovered.name}")
    try:
        async with asyncio.timeout(smoke_timeout_s):
            async with recorder:
                fp = recorder.trace.servers[0] if recorder.trace.servers else None
                specs = recorder.trace.tool_specs.get(server_id, [])
                tool_names = [t.name for t in specs]
    except TimeoutError:
        return VetResult(
            server_name=discovered.name,
            server_id=server_id,
            status=VetStatus.timeout,
            reason=f"smoke timed out after {smoke_timeout_s:.0f}s",
            elapsed_s=time.monotonic() - t0,
        )
    except Exception as e:
        # Treat any exception during initialize/list as initialize_failed.
        return VetResult(
            server_name=discovered.name,
            server_id=server_id,
            status=VetStatus.initialize_failed,
            reason=f"{type(e).__name__}: {str(e)[:300]}",
            elapsed_s=time.monotonic() - t0,
        )
    elapsed = time.monotonic() - t0
    if not tool_names:
        return VetResult(
            server_name=discovered.name,
            server_id=server_id,
            status=VetStatus.no_tools,
            reason="server initialized but exposed 0 tools",
            elapsed_s=elapsed,
            server_name_reported=fp.server_name if fp else None,
            server_version_reported=fp.server_version if fp else None,
            protocol_version=fp.protocol_version if fp else None,
        )
    dynamism = _classify_dynamism(tool_names)
    # stateful_write requires sandbox=True per Manifest validator. We mark
    # crawled servers as sandbox=true by default — they run with no
    # credentials in subprocess isolation; that's our v0 sandbox.
    sandbox = dynamism is Dynamism.stateful_write
    entry = ServerEntry(
        server_id=server_id,
        transport=TransportKind.stdio,
        command=install.invoke_command,
        args=list(install.invoke_args),
        dynamism=dynamism,
        sandbox=sandbox,
        description=(discovered.description or "")[:240] or None,
        tags=["crawled", "mcp-registry"],
    )
    return VetResult(
        server_name=discovered.name,
        server_id=server_id,
        status=VetStatus.success,
        reason=f"initialized + {len(tool_names)} tools",
        elapsed_s=elapsed,
        server_name_reported=fp.server_name if fp else None,
        server_version_reported=fp.server_version if fp else None,
        protocol_version=fp.protocol_version if fp else None,
        tool_count=len(tool_names),
        tool_names=tool_names,
        dynamism=dynamism,
        manifest_entry=entry,
    )


def vet_one(
    discovered: DiscoveredServer,
    install: InstallResult,
    *,
    smoke_timeout_s: float = 30.0,
) -> VetResult:
    """Sync wrapper around the async smoke. Each server gets its own loop so
    failures don't poison the next attempt."""
    if install.status is not InstallStatus.success:
        return VetResult(
            server_name=discovered.name,
            server_id=_sanitize_server_id(discovered.name),
            status=VetStatus.initialize_failed,
            reason=f"install failed: {install.reason}",
        )
    return asyncio.run(_vet_one(discovered, install, smoke_timeout_s=smoke_timeout_s))


def vet_result_summary(result: VetResult) -> dict[str, Any]:
    return {
        "server_name": result.server_name,
        "server_id": result.server_id,
        "status": result.status.value,
        "reason": result.reason,
        "elapsed_s": round(result.elapsed_s, 2),
        "server_name_reported": result.server_name_reported,
        "server_version_reported": result.server_version_reported,
        "protocol_version": result.protocol_version,
        "tool_count": result.tool_count,
        "tool_names": result.tool_names,
        "dynamism": result.dynamism.value if result.dynamism else None,
    }
