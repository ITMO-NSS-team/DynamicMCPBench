"""HTTP routes + SSE framing (guarded on fastapi being installed)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def _sse_events(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    ev = None
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.append((ev or "message", json.loads(line.split(":", 1)[1].strip())))
    return events


def test_servers_route():
    r = client.get("/api/servers")
    assert r.status_code == 200
    ids = {s["server_id"] for s in r.json()}
    assert "yfinance" in ids


def test_goal_route():
    r = client.post("/api/goal", json={"server_ids": ["yfinance"]})
    assert r.status_code == 200 and "AAPL" in r.json()["goal"]


def test_explore_sse_streams_calls_then_done():
    r = client.get("/api/explore", params={"delay": 0})
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert [e for e, _ in events].count("call") == 7
    done = next(d for e, d in events if e == "done")
    assert done["success"] is True and done["n_calls"] == 7


def test_distill_route_returns_spec_and_equiv_sets():
    r = client.post("/api/distill", json={"trace_id": None})
    body = r.json()
    assert body["task_spec"]["checkpoints"]
    assert body["equivalence_sets"]["cp3"] == ["download", "get_price_history"]


def test_score_sse_carries_both_verdicts():
    r = client.get("/api/score", params={"candidate": "hermes3-8b", "delay": 0})
    events = _sse_events(r.text)
    done = next(d for e, d in events if e == "done")
    assert done["effect_pass"] is False  # incomplete aggregation
    assert done["answer_pass"] is True  # but the prose looks right
    assert done["met_count"] == done["required"] - 1


def test_score_equiv_override_via_query():
    r = client.get(
        "/api/score",
        params={"candidate": "qwen3.7-max", "equiv_overrides": "download", "delay": 0},
    )
    done = next(d for e, d in _sse_events(r.text) if e == "done")
    assert done["effect_pass"] is False  # qwen used get_price_history, now disabled


def test_leaderboard_route():
    r = client.get("/api/leaderboard")
    assert r.status_code == 200 and r.json()["placeholder"] is True


def test_spa_served_without_shadowing_api():
    # the static mount serves the SPA at /, and /api still resolves
    index = client.get("/")
    assert index.status_code == 200 and "DMCP Studio" in index.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/servers").status_code == 200
