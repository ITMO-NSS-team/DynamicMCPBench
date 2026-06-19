"""LIVE-mode plumbing — deterministic parts only (no network/LLM).

The streaming wrapper, the manifest-backed server list, and the route-level
fallback to the REPLAY fixture are tested with fakes. A real live run is the
opt-in ``scripts/live_smoke.py``, never the gate.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from backend import live

pytest.importorskip("fastapi")
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def _sse(text: str) -> list[tuple[str, dict]]:
    out, ev = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            out.append((ev or "message", json.loads(line.split(":", 1)[1].strip())))
    return out


# ---- streaming wrapper (no network) ----


class _FakeInner:
    def __init__(self):
        self.trace = "trace-obj"

    async def call_tool(self, server_id, tool_name, arguments=None):
        return {"isError": tool_name == "bad", "content": []}


async def test_streaming_recorder_emits_one_event_per_call():
    q: asyncio.Queue = asyncio.Queue()
    rec = live.StreamingRecorder(_FakeInner(), q)
    await rec.call_tool("yfinance", "get_x", {"a": 1})
    await rec.call_tool("yfinance", "bad", {})
    e1, e2 = q.get_nowait(), q.get_nowait()
    assert e1 == {"idx": 1, "server_id": "yfinance", "tool_name": "get_x", "arguments": {"a": 1}, "ok": True}
    assert e2["idx"] == 2 and e2["ok"] is False
    assert rec.trace == "trace-obj"  # forwards the inner trace


# ---- manifest-backed server list (reads manifests/local.json, no network) ----


def test_live_servers_from_manifest():
    cards = live.live_servers()
    ids = {c.server_id for c in cards}
    assert ids == set(live.SHOWCASE_SERVER_IDS)
    assert all(c.dynamism == "live_read" for c in cards)  # showcase is read-only


# ---- route-level fallback to the REPLAY fixture ----


def test_explore_live_success_passthrough(monkeypatch):
    async def fake_stream(ids, goal, persona):
        yield {
            "event": "call",
            "data": {"idx": 1, "server_id": "yfinance", "tool_name": "get_x", "arguments": {}, "ok": True},
        }
        yield {"event": "done", "data": {"trace_id": "abc", "n_calls": 1, "success": True}}

    monkeypatch.setattr(live, "stream_explore", fake_stream)
    r = client.get("/api/explore", params={"mode": "live", "goal": "g", "server_ids": "yfinance"})
    events = _sse(r.text)
    assert (
        "call",
        {"idx": 1, "server_id": "yfinance", "tool_name": "get_x", "arguments": {}, "ok": True},
    ) in events
    assert any(e == "done" for e, _ in events)


def test_explore_live_falls_back_to_replay(monkeypatch):
    async def boom(ids, goal, persona):
        if True:
            raise RuntimeError("server unreachable")
        yield  # unreachable; makes boom an async generator

    monkeypatch.setattr(live, "stream_explore", boom)
    r = client.get("/api/explore", params={"mode": "live", "delay": 0, "goal": "g"})
    events = _sse(r.text)
    assert any(e == "fellback" for e, _ in events)
    assert [e for e, _ in events].count("call") == 7  # the replay fixture
    assert any(e == "done" for e, _ in events)


def test_goal_live_falls_back(monkeypatch):
    async def boom(server_ids):
        raise RuntimeError("down")

    monkeypatch.setattr(live, "live_goal", boom)
    r = client.post("/api/goal", params={"mode": "live"}, json={"server_ids": ["yfinance"]})
    body = r.json()
    assert "fellback" in body and "AAPL" in body["goal"]


def test_distill_live_falls_back(monkeypatch):
    async def boom(trace_id):
        raise RuntimeError("no trace")

    monkeypatch.setattr(live, "live_distill", boom)
    r = client.post("/api/distill", params={"mode": "live"}, json={"trace_id": None})
    body = r.json()
    assert "fellback" in body and body["task_spec"]["checkpoints"]


def test_servers_live_falls_back(monkeypatch):
    def boom():
        raise RuntimeError("manifest gone")

    monkeypatch.setattr(live, "live_servers", boom)
    r = client.get("/api/servers", params={"mode": "live"})
    assert r.status_code == 200 and any(s["server_id"] == "yfinance" for s in r.json())


def test_score_is_always_replay():
    # no mode param; scoring is the deterministic graded path
    r = client.get("/api/score", params={"candidate": "hermes3-8b", "delay": 0})
    done = next(d for e, d in _sse(r.text) if e == "done")
    assert done["effect_pass"] is False and done["answer_pass"] is True
