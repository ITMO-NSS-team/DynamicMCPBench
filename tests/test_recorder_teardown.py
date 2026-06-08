"""TraceRecorder.__aexit__ must survive the MCP/anyio cancel-scope teardown bug.

stdio_client / ClientSession tear down internal anyio task groups; under
cancellation or after a flaky boot anyio raises "Attempted to exit cancel scope
in a different task than it was entered in". The trace is already recorded by
that point, so the recorder must swallow exactly that RuntimeError and keep
going — otherwise a single bad goal zeroes out an entire explorer shard.
"""

from __future__ import annotations

import asyncio

import pytest

from dmcp.recorder import TraceRecorder


class _FakeStack:
    """Stand-in for the AsyncExitStack whose close raises a given error."""

    def __init__(self, exc: BaseException | None):
        self._exc = exc
        self.closed = False

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        if self._exc is not None:
            raise self._exc
        return None


async def _exit_with(stack_exc: BaseException | None) -> TraceRecorder:
    rec = TraceRecorder(servers=[], goal="g")
    # Skip __aenter__ (no real servers); install our fake stack directly.
    rec._stack = _FakeStack(stack_exc)  # type: ignore[assignment]
    await rec.__aexit__(None, None, None)
    return rec


def test_swallows_cancel_scope_runtimeerror():
    exc = RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")
    rec = asyncio.run(_exit_with(exc))  # must NOT raise
    assert rec._stack is None


def test_swallows_cancel_scope_inside_exceptiongroup():
    exc = BaseExceptionGroup(
        "teardown",
        [RuntimeError("Attempted to exit cancel scope in a different task")],
    )
    rec = asyncio.run(_exit_with(exc))  # must NOT raise
    assert rec._stack is None


def test_reraises_unrelated_runtimeerror():
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(_exit_with(RuntimeError("boom")))


def test_reraises_unrelated_error_in_group():
    grp = BaseExceptionGroup(
        "teardown",
        [
            RuntimeError("Attempted to exit cancel scope in a different task"),
            ValueError("real problem"),
        ],
    )
    with pytest.raises(BaseExceptionGroup):
        asyncio.run(_exit_with(grp))
