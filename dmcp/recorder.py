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

import asyncio
import contextlib
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from dmcp import __version__
from dmcp import _mcp_compat as _mcp_compat  # noqa: F401  (lenient MCP message parsing)
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


@dataclass
class _Request:
    method: str  # "list_tools" | "call_tool"
    args: tuple[Any, ...]
    future: asyncio.Future


class _SessionActor:
    """Owns one MCP session inside a single dedicated task.

    The transport (`stdio_client` / `sse_client` / `streamablehttp_client`) and
    `ClientSession` are anyio task-group-based context managers. Driving them
    through an `AsyncExitStack` that is closed later violates anyio's LIFO
    cancel-scope requirement under the asyncio backend, which corrupts the
    *calling* task's cancel scope on teardown — every subsequent ``await`` then
    raises ``CancelledError`` (a persistent, loop-wide poison). Keeping the whole
    ``async with`` lifecycle inside one task, opened and closed in LIFO order
    there, avoids it. The recorder talks to the session over a request queue.
    """

    def __init__(self, cfg: ServerConfig, stderr_sink: TextIO) -> None:
        self._cfg = cfg
        self._stderr = stderr_sink
        self._queue: asyncio.Queue[_Request | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None
        self.init_result: Any = None

    def _transport_cm(self):
        cfg = self._cfg
        if isinstance(cfg, StdioServer):
            return stdio_client(
                StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env),
                errlog=self._stderr,
            )
        if isinstance(cfg, SseServer):
            return sse_client(cfg.url, headers=cfg.headers)
        if isinstance(cfg, StreamableHttpServer):
            return streamablehttp_client(cfg.url, headers=cfg.headers)
        raise TypeError(f"unknown ServerConfig: {type(cfg).__name__}")

    async def start(self) -> None:
        """Spawn the session task and wait until it has initialized (or failed)."""
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._serve())
        await self._ready  # re-raises a boot failure to the caller

    async def _serve(self) -> None:
        assert self._ready is not None
        try:
            async with self._transport_cm() as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    self.init_result = await session.initialize()
                    if not self._ready.done():
                        self._ready.set_result(None)
                    while True:
                        item = await self._queue.get()
                        if item is None:
                            break
                        if item.future.done():
                            continue
                        try:
                            item.future.set_result(await getattr(session, item.method)(*item.args))
                        except Exception as exc:  # surface per-request, keep the session alive
                            item.future.set_exception(exc)
        except BaseException as exc:  # boot/transport failure or cancellation
            if not self._ready.done():
                self._ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
            self._drain(exc)
            if not isinstance(exc, Exception):
                raise  # propagate CancelledError etc.
        finally:
            self._drain(RuntimeError("session closed"))

    def _drain(self, exc: BaseException) -> None:
        err = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is not None and not item.future.done():
                item.future.set_exception(err)

    async def request(self, method: str, *args: Any) -> Any:
        if self._task is None or self._task.done():
            raise RuntimeError(f"session for {self._cfg.server_id!r} is not running")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Request(method, args, fut))
        return await fut

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        if not task.done():
            self._queue.put_nowait(None)  # ask the session loop to exit cleanly (unbounded queue)
        # Best-effort await. If OUR task is being cancelled, suppress it: the
        # actor was already signalled and unwinds its own context managers in its
        # own task, so the calling task is never poisoned. The trace is already
        # recorded, so any teardown bookkeeping error is benign.
        with contextlib.suppress(BaseException):
            await task


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
        self._actors: dict[str, _SessionActor] = {}
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
        self._stderr_sink = self._resolve_server_stderr()
        for server_id, cfg in self._configs.items():
            # Each server runs in its own session actor (one task per session),
            # so a single flaky server can be skipped without aborting the whole
            # exploration — and so the MCP context managers open/close in LIFO
            # order within one task (no cancel-scope corruption; see _SessionActor).
            actor = _SessionActor(cfg, self._stderr_sink)
            try:
                await actor.start()
                fingerprint = await self._fingerprint(server_id, cfg, actor)
            except asyncio.CancelledError as e:
                await actor.stop()
                self.trace.seed_metadata.setdefault("boot_failures", []).append(
                    {"server_id": server_id, "error": f"{type(e).__name__}: {e}"}
                )
                raise
            except Exception as e:
                await actor.stop()
                self.trace.seed_metadata.setdefault("boot_failures", []).append(
                    {"server_id": server_id, "error": f"{type(e).__name__}: {e}"}
                )
                continue
            self._actors[server_id] = actor
            self.trace.servers.append(fingerprint)
        self.trace.started_at = _utcnow()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.trace.ended_at = _utcnow()
        # Each actor unwinds its own MCP context managers inside its own task,
        # so teardown can't poison the calling task's cancel scope.
        for actor in self._actors.values():
            await actor.stop()
        self._actors.clear()
        if self._server_stderr_file is not None:
            with contextlib.suppress(Exception):
                self._server_stderr_file.close()
            self._server_stderr_file = None

    async def _fingerprint(
        self, server_id: str, cfg: ServerConfig, actor: _SessionActor
    ) -> ServerFingerprint:
        # initialize() already happened inside the actor; read its cached result
        # and a tools/list call (routed through the actor's session task).
        tools_resp = await actor.request("list_tools")
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

        init_result = actor.init_result
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

    def _require_actor(self, server_id: str) -> _SessionActor:
        try:
            return self._actors[server_id]
        except KeyError as e:
            raise KeyError(f"no session for server_id={server_id!r}") from e

    async def list_tools(self, server_id: str) -> list[ToolSpec]:
        actor = self._require_actor(server_id)
        started_at = _utcnow()
        status = StepStatus.success
        result_payload: dict[str, Any] | None = None
        error: StepError | None = None
        tools: list[ToolSpec] = []
        try:
            resp = await actor.request("list_tools")
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
        actor = self._require_actor(server_id)
        started_at = _utcnow()
        status = StepStatus.success
        result_payload: dict[str, Any] | None = None
        error: StepError | None = None
        try:
            resp = await actor.request("call_tool", tool_name, arguments or {})
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
