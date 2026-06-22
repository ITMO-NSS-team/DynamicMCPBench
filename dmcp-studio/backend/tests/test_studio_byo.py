"""A4 — bring-your-own-server registration.

Validation (input + sandbox default-deny) is deterministic. The real
tool-surface collection is tested against the local stdio `time` server (a
subprocess; no network, no API key, no LLM), skipped if it isn't installed.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from backend import live

pytest.importorskip("fastapi")
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)

HAVE_TIME = importlib.util.find_spec("mcp_server_time") is not None


@pytest.fixture(autouse=True)
def _clear_registry():
    live._REGISTERED.clear()
    yield
    live._REGISTERED.clear()


# ---- input validation + sandbox default-deny (deterministic, no server) ----


def test_register_rejects_missing_command():
    r = client.post("/api/register-server", json={"server_id": "x", "transport": "stdio"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_server"


def test_register_rejects_stateful_write_without_sandbox():
    r = client.post(
        "/api/register-server",
        json={"server_id": "danger", "command": "echo", "dynamism": "stateful_write"},
    )
    # ServerEntry's validator rejects stateful_write without sandbox=true.
    assert r.status_code in (400, 403)


def test_register_rejects_http_without_endpoint():
    r = client.post(
        "/api/register-server",
        json={"server_id": "h", "transport": "streamable_http"},
    )
    assert r.status_code == 400


def test_register_rejects_blank_id():
    r = client.post("/api/register-server", json={"server_id": "  ", "command": "echo"})
    assert r.status_code == 400


# ---- real collection against the local `time` server ----


@pytest.mark.skipif(not HAVE_TIME, reason="mcp_server_time not installed")
def test_register_stdio_server_collects_tools():
    r = client.post(
        "/api/register-server",
        json={
            "server_id": "byo_time",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_server_time", "--local-timezone", "UTC"],
        },
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["server_id"] == "byo_time"
    assert "get_current_time" in card["tools"]
    assert card["dynamism"] == "live_read"
    # it now shows up in the live server list and the augmented manifest
    assert any(c.server_id == "byo_time" for c in live.live_servers())
    assert "byo_time" in {e.server_id for e in live.augmented_manifest().servers}


@pytest.mark.skipif(not HAVE_TIME, reason="mcp_server_time not installed")
def test_register_bad_command_returns_502():
    r = client.post(
        "/api/register-server",
        json={"server_id": "nope", "command": sys.executable, "args": ["-c", "import sys; sys.exit(1)"]},
    )
    assert r.status_code == 502 and r.json()["error"] == "register_failed"
    assert "nope" not in live._REGISTERED  # not registered on failure
