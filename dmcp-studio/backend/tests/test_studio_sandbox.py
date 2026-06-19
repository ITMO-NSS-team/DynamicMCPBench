"""Sandbox default-deny gate (build plan §10, invariant #4)."""

from __future__ import annotations

import pytest
from backend.dmcp_adapter import SandboxViolation, ensure_sandbox_safe


def test_stateful_write_without_sandbox_is_denied():
    with pytest.raises(SandboxViolation):
        ensure_sandbox_safe(server_id="github", dynamism="stateful_write", sandbox=False)


def test_stateful_write_with_sandbox_is_allowed():
    ensure_sandbox_safe(server_id="github", dynamism="stateful_write", sandbox=True)


@pytest.mark.parametrize("dyn", ["static", "live_read"])
def test_read_only_servers_always_allowed(dyn):
    ensure_sandbox_safe(server_id="yfinance", dynamism=dyn, sandbox=False)
