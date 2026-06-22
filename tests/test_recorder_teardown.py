"""TraceRecorder must tear down cleanly without poisoning the event loop.

`stdio_client` / `ClientSession` are anyio task-group-based context managers.
Driving them through an `AsyncExitStack` closed later violated anyio's LIFO
cancel-scope requirement under asyncio, corrupting the *calling* task's cancel
scope on teardown — after which every `await` raised `CancelledError` (a
persistent, loop-wide poison that broke live goal-gen → explore). The recorder
now runs each session in its own task (`_SessionActor`), so the MCP context
managers open/close in LIFO order in one task.

These are real integration tests against the local stdio `time` server (a
subprocess; no network, no API key), skipped if it isn't installed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys

import pytest

from dmcp.recorder import StdioServer, TraceRecorder
from dmcp.trace import StepKind, StepStatus

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp_server_time") is None,
    reason="mcp_server_time not installed (pip install -e '.[servers]')",
)


def _time_server() -> StdioServer:
    return StdioServer(
        server_id="time",
        command=sys.executable,
        args=["-m", "mcp_server_time", "--local-timezone", "UTC"],
    )


async def test_recorder_no_loop_poison():
    """The regression: after a recorder closes, the loop must still work."""
    async with TraceRecorder(servers=[_time_server()], goal="t"):
        pass
    # Pre-fix this raised CancelledError (the loop's cancel scope was corrupted).
    await asyncio.sleep(0.01)
    await asyncio.gather(asyncio.sleep(0), asyncio.sleep(0))


async def test_recorder_records_real_stdio():
    """A real list_tools + call_tool are captured as Steps."""
    async with TraceRecorder(servers=[_time_server()], goal="what time is it") as rec:
        tools = await rec.list_tools("time")
        assert any(t.name == "get_current_time" for t in tools)
        result = await rec.call_tool("time", "get_current_time", {"timezone": "UTC"})
        assert result and not result.get("isError")
    calls = [s for s in rec.trace.steps if s.kind is StepKind.call_tool_agent]
    assert len(calls) == 1
    assert calls[0].status is StepStatus.success
    assert calls[0].server_id == "time" and calls[0].tool_name == "get_current_time"
    assert rec.trace.servers and rec.trace.servers[0].tool_count >= 1


async def test_two_recorders_sequential():
    """goal-gen → explore: a second recorder after the first must work (no poison)."""
    async with TraceRecorder(servers=[_time_server()], goal="first") as rec1:
        await rec1.call_tool("time", "get_current_time", {"timezone": "UTC"})
    await asyncio.sleep(0)  # would raise here pre-fix
    async with TraceRecorder(servers=[_time_server()], goal="second") as rec2:
        r = await rec2.call_tool("time", "get_current_time", {"timezone": "UTC"})
    assert r and not r.get("isError")


async def test_cancel_mid_session_no_poison():
    """Cancelling a task mid-session (e.g. an explore timeout) must tear the
    recorder down without poisoning the surrounding loop."""

    async def worker():
        async with TraceRecorder(servers=[_time_server()], goal="t") as rec:
            await rec.call_tool("time", "get_current_time", {"timezone": "UTC"})
            await asyncio.sleep(10)  # block so we can cancel while the session is open

    t = asyncio.create_task(worker())
    await asyncio.sleep(0.6)  # let it boot + make the call
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    await asyncio.sleep(0.01)  # surrounding loop must be healthy
    async with TraceRecorder(servers=[_time_server()], goal="t2") as rec2:
        r = await rec2.call_tool("time", "get_current_time", {"timezone": "UTC"})
    assert r and not r.get("isError")


async def test_bad_server_skipped_without_poison():
    """A server that fails to boot is recorded as a boot failure and skipped,
    and the loop is not poisoned."""
    bad = StdioServer(server_id="bad", command=sys.executable, args=["-c", "import sys; sys.exit(1)"])
    async with TraceRecorder(servers=[bad], goal="t") as rec:
        assert "time" not in rec._actors
    assert rec.trace.seed_metadata.get("boot_failures")
    await asyncio.sleep(0.01)  # not poisoned
