"""Record-mode MCP client wrapper.

Wraps the official `mcp` Python SDK's transports (stdio / SSE / streamable
HTTP) and ClientSession. Every tools/list and tools/call goes through this
wrapper, which timestamps it, canonicalizes arguments, and appends a Step to
the in-memory Trace. On exit, the Trace can be serialized to JSONL.

Scope of v0:
- Top-level agent-issued calls only. Server-internal sub-steps (StepKind.
  call_tool_server_internal) are reserved in the schema but not yet captured;
  add hooks once we exercise a server-loop-capable server.
- No truncation, no retry, no replay. Faithful capture only.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from dmcp import __version__
from dmcp.trace import (
    ServerFingerprint,
    Step,
    StepError,
    StepKind,
    StepStatus,
    ToolSpec,
    Trace,
    TransportKind,
    hash_tool_surface,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class StdioServer:
    """Launch an MCP server as a subprocess and speak stdio to it."""

    server_id: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None

    transport = TransportKind.stdio

    @property
    def endpoint(self) -> str:
        return " ".join([self.command, *self.args])


@dataclass
class SseServer:
    """Connect to an MCP server over the (legacy) SSE transport."""

    server_id: str
    url: str
    headers: dict[str, str] | None = None

    transport = TransportKind.sse

    @property
    def endpoint(self) -> str:
        return self.url


@dataclass
class StreamableHttpServer:
    """Connect to an MCP server over the 2025-11 streamable HTTP transport."""

    server_id: str
    url: str
    headers: dict[str, str] | None = None

    transport = TransportKind.streamable_http

    @property
    def endpoint(self) -> str:
        return self.url


ServerConfig = StdioServer | SseServer | StreamableHttpServer


class TraceRecorder:
    """Opens one or more MCP sessions and records every interaction.

    Usage:
        recorder = TraceRecorder(
            servers=[StreamableHttpServer("time", "http://localhost:8020/mcp")],
            goal="check current time in Tokyo",
        )
        async with recorder:
            tools = await recorder.list_tools("time")
            result = await recorder.call_tool("time", "get_current_time",
                                              {"timezone": "Asia/Tokyo"})
        recorder.write_jsonl(Path("trace.jsonl"))
    """

    def __init__(
        self,
        servers: list[ServerConfig],
        *,
        goal: str | None = None,
        seed_metadata: dict[str, Any] | None = None,
        server_stderr: TextIO | str | None = "suppress",
    ) -> None:
        """Construct a recorder over one or more MCP servers.

        server_stderr: where the spawned servers' stderr goes. Defaults to
        "suppress" (→ /dev/null) because most servers print banners and
        npm-vulnerability noise on every startup, which makes scaled crawls
        unreadable. Pass None to let stderr inherit (Python's sys.stderr),
        or pass a TextIO / file path string for diagnostic logging.
        """
        self._configs: dict[str, ServerConfig] = {s.server_id: s for s in servers}
        self.trace = Trace(
            recorder_version=__version__,
            goal=goal,
            seed_metadata=seed_metadata or {},
        )
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        self._init_results: dict[str, Any] = {}
        self._server_stderr_spec = server_stderr
        self._server_stderr_file: TextIO | None = None

    def _resolve_server_stderr(self) -> TextIO:
        spec = self._server_stderr_spec
        if spec is None:
            return sys.stderr
        if spec == "suppress":
            f = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 — managed by __aexit__
            self._server_stderr_file = f
            return f
        if isinstance(spec, str):
            f = open(spec, "a", encoding="utf-8")  # noqa: SIM115 — managed by __aexit__
            self._server_stderr_file = f
            return f
        return spec

    async def __aenter__(self) -> TraceRecorder:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        self._stderr_sink = self._resolve_server_stderr()
        for server_id, cfg in self._configs.items():
            session, init_result = await self._open_session(cfg)
            self._sessions[server_id] = session
            self._init_results[server_id] = init_result
            fingerprint = await self._fingerprint(server_id, cfg, session)
            self.trace.servers.append(fingerprint)
        self.trace.started_at = _utcnow()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.trace.ended_at = _utcnow()
        assert self._stack is not None
        await self._stack.__aexit__(exc_type, exc, tb)
        self._stack = None
        self._sessions.clear()
        if self._server_stderr_file is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self._server_stderr_file.close()
            self._server_stderr_file = None

    async def _open_session(self, cfg: ServerConfig) -> tuple[ClientSession, Any]:
        assert self._stack is not None
        if isinstance(cfg, StdioServer):
            transport_cm = stdio_client(
                StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env),
                errlog=self._stderr_sink,
            )
            read, write = await self._stack.enter_async_context(transport_cm)
            session = await self._stack.enter_async_context(ClientSession(read, write))
        elif isinstance(cfg, SseServer):
            transport_cm = sse_client(cfg.url, headers=cfg.headers)
            read, write = await self._stack.enter_async_context(transport_cm)
            session = await self._stack.enter_async_context(ClientSession(read, write))
        elif isinstance(cfg, StreamableHttpServer):
            transport_cm = streamablehttp_client(cfg.url, headers=cfg.headers)
            read, write, _ = await self._stack.enter_async_context(transport_cm)
            session = await self._stack.enter_async_context(ClientSession(read, write))
        else:
            raise TypeError(f"unknown ServerConfig: {type(cfg).__name__}")
        init_result = await session.initialize()
        return session, init_result

    async def _fingerprint(
        self, server_id: str, cfg: ServerConfig, session: ClientSession
    ) -> ServerFingerprint:
        # session.initialize() already happened; pull the cached result via the
        # SDK if it exposes one, otherwise re-derive from a tools/list call.
        tools_resp = await session.list_tools()
        tool_specs = [
            ToolSpec(
                name=t.name,
                description=t.description,
                input_schema=t.inputSchema,
                output_schema=getattr(t, "outputSchema", None),
            )
            for t in tools_resp.tools
        ]
        self.trace.tool_specs[server_id] = tool_specs

        init_result = self._init_results.get(server_id)
        server_name = server_version = protocol_version = None
        capabilities: dict[str, Any] | None = None
        if init_result is not None:
            server_info = getattr(init_result, "serverInfo", None)
            if server_info is not None:
                server_name = getattr(server_info, "name", None)
                server_version = getattr(server_info, "version", None)
            protocol_version = getattr(init_result, "protocolVersion", None)
            caps = getattr(init_result, "capabilities", None)
            if caps is not None:
                capabilities = caps.model_dump(mode="json") if hasattr(caps, "model_dump") else dict(caps)

        return ServerFingerprint(
            server_id=server_id,
            transport=cfg.transport,
            endpoint=cfg.endpoint,
            server_name=server_name,
            server_version=server_version,
            protocol_version=protocol_version,
            capabilities=capabilities,
            tool_count=len(tool_specs),
            tool_surface_hash=hash_tool_surface([t.name for t in tool_specs]),
        )

    def _require_session(self, server_id: str) -> ClientSession:
        try:
            return self._sessions[server_id]
        except KeyError as e:
            raise KeyError(f"no session for server_id={server_id!r}") from e

    async def list_tools(self, server_id: str) -> list[ToolSpec]:
        session = self._require_session(server_id)
        started_at = _utcnow()
        status = StepStatus.success
        result_payload: dict[str, Any] | None = None
        error: StepError | None = None
        tools: list[ToolSpec] = []
        try:
            resp = await session.list_tools()
            tools = [
                ToolSpec(
                    name=t.name,
                    description=t.description,
                    input_schema=t.inputSchema,
                    output_schema=getattr(t, "outputSchema", None),
                )
                for t in resp.tools
            ]
            result_payload = {"tools": [t.model_dump(mode="json") for t in tools]}
        except Exception as exc:
            status = StepStatus.error
            error = StepError(code=type(exc).__name__, message=str(exc))
            raise
        finally:
            ended_at = _utcnow()
            self.trace.steps.append(
                Step.build(
                    step_id=self.trace.next_step_id(),
                    kind=StepKind.list_tools,
                    server_id=server_id,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=status,
                    result=result_payload,
                    error=error,
                )
            )
        return tools

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._require_session(server_id)
        started_at = _utcnow()
        status = StepStatus.success
        result_payload: dict[str, Any] | None = None
        error: StepError | None = None
        try:
            resp = await session.call_tool(tool_name, arguments or {})
            if hasattr(resp, "model_dump"):
                result_payload = resp.model_dump(mode="json")
            else:
                result_payload = dict(resp)
            if getattr(resp, "isError", False):
                status = StepStatus.error
                error = StepError(
                    code="ToolError",
                    message="tool returned isError=true",
                    raw=result_payload,
                )
        except Exception as exc:
            status = StepStatus.error
            error = StepError(code=type(exc).__name__, message=str(exc))
            raise
        finally:
            ended_at = _utcnow()
            self.trace.steps.append(
                Step.build(
                    step_id=self.trace.next_step_id(),
                    kind=StepKind.call_tool_agent,
                    server_id=server_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=status,
                    result=result_payload,
                    error=error,
                )
            )
        return result_payload or {}

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(self.trace.to_jsonl())
            f.write("\n")
