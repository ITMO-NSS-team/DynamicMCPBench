"""Trace data model — the central primitive of DynamicMCPBench.

A Trace records one exploration session against one or more MCP servers. It is
designed to be faithful (every agent-issued and server-internal call is
captured), replay-friendly (server fingerprint enables drift detection,
canonical args enable cache keying), and forward-compatible (a schema_version
field and permissive result payloads).

Effect derivation (checkpoints, minefields, causal ordering) is *not* the
recorder's job — those live in the distiller and consume traces. The recorder
captures raw execution faithfully and leaves interpretation to later stages.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def canonicalize_args(args: dict[str, Any] | None) -> str:
    """Stable JSON serialization for cache keying and equality checks.

    Keys sorted, separators tight, ensure_ascii=False. Two calls with the same
    arguments — regardless of dict insertion order — produce identical strings.
    """
    if args is None:
        return "{}"
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_tool_surface(tool_names: list[str]) -> str:
    """Stable fingerprint of a server's tool surface. Change ⇒ schema drift."""
    payload = "\n".join(sorted(tool_names)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


class TransportKind(str, Enum):
    """How the recorder reaches the server. The 2025-11 MCP spec deprecated
    plain SSE in favor of streamable_http; both are kept for compatibility."""

    stdio = "stdio"
    sse = "sse"
    streamable_http = "streamable_http"


class StepKind(str, Enum):
    """What the step represents.

    The agent_call / server_internal distinction resolves the 2025-11 spec
    ambiguity around server-side agent loops: one agent-issued call may spawn
    server-internal steps. Checkpoint counting MUST filter on this field.
    """

    list_tools = "list_tools"
    call_tool_agent = "call_tool_agent"
    call_tool_server_internal = "call_tool_server_internal"


class StepStatus(str, Enum):
    success = "success"
    error = "error"
    timeout = "timeout"


class StepError(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str | None = None
    message: str
    raw: dict[str, Any] | None = None


class ToolSpec(BaseModel):
    """Captured tool description at session start; used for replay drift checks."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class ServerFingerprint(BaseModel):
    """Identity + observed state of one MCP server at the start of a session.

    server_id is *our* slug (chosen by the recorder config), independent of
    anything the server itself reports. Everything else is read from the
    server's initialize response and tools/list call.
    """

    model_config = ConfigDict(extra="allow")

    server_id: str
    transport: TransportKind
    endpoint: str
    server_name: str | None = None
    server_version: str | None = None
    protocol_version: str | None = None
    capabilities: dict[str, Any] | None = None
    tool_count: int = 0
    tool_surface_hash: str = ""
    observed_at: datetime = Field(default_factory=_utcnow)


class Step(BaseModel):
    """One recorded action. Either a tools/list or a tools/call.

    parent_step_id is set only for server-internal sub-steps (StepKind.
    call_tool_server_internal). For top-level agent calls it is None.
    """

    model_config = ConfigDict(extra="allow")

    step_id: int
    parent_step_id: int | None = None
    kind: StepKind
    server_id: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    arguments_canonical: str = ""
    result: dict[str, Any] | None = None
    result_truncated: bool = False
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: StepStatus
    error: StepError | None = None

    @classmethod
    def build(
        cls,
        *,
        step_id: int,
        kind: StepKind,
        server_id: str,
        started_at: datetime,
        ended_at: datetime,
        status: StepStatus,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        result_truncated: bool = False,
        parent_step_id: int | None = None,
        error: StepError | None = None,
    ) -> Step:
        latency_ms = (ended_at - started_at).total_seconds() * 1000.0
        return cls(
            step_id=step_id,
            parent_step_id=parent_step_id,
            kind=kind,
            server_id=server_id,
            tool_name=tool_name,
            arguments=arguments,
            arguments_canonical=canonicalize_args(arguments),
            result=result,
            result_truncated=result_truncated,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )


class Trace(BaseModel):
    """A single recorded exploration session.

    A Trace is the unit of ground truth for DynamicMCPBench: distillation reads
    a Trace and emits a TaskSpec; evaluation produces a candidate Trace and
    compares it to the reference TaskSpec's effect checkpoints.
    """

    model_config = ConfigDict(extra="allow")

    trace_id: UUID = Field(default_factory=uuid4)
    schema_version: str = SCHEMA_VERSION
    recorder_version: str = ""
    goal: str | None = None
    seed_metadata: dict[str, Any] = Field(default_factory=dict)
    servers: list[ServerFingerprint] = Field(default_factory=list)
    tool_specs: dict[str, list[ToolSpec]] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None

    def next_step_id(self) -> int:
        return (self.steps[-1].step_id + 1) if self.steps else 0

    def to_jsonl(self) -> str:
        """One trace per line — fits HF datasets, jq pipelines, and grep."""
        return self.model_dump_json(exclude_none=False)
