"""FastAPI app for DMCP Studio.

Six routes (build plan §4), REPLAY-backed in A1. The two slow stages
(explore, score) stream call-by-call over Server-Sent Events; ``/distill`` and
``/score`` also yield a final JSON summary. All real work goes through
``dmcp_adapter`` — the app does HTTP, SSE framing, and inter-event pacing only.

Run:  cd dmcp-studio && uvicorn backend.app:app --reload
Scope of v0 (A1): REPLAY for every route. LIVE wiring lands in A3.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import dmcp_adapter as adapter
from .models import Mode

app = FastAPI(title="DMCP Studio", version="0.1.0")

# Default inter-event pacing for SSE (build plan §4: 300–600 ms). Overridable
# per request via ?delay= so tests can run with no wait.
DEFAULT_DELAY = 0.45


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode_default": "replay"}


@app.get("/api/servers")
def servers(mode: Mode = "replay") -> Any:
    return [s.model_dump() for s in adapter.list_servers(mode)]


class GoalIn(BaseModel):
    server_ids: list[str] = []


@app.post("/api/goal")
def goal(body: GoalIn, mode: Mode = "replay") -> Any:
    return adapter.generate_goal(mode, body.server_ids).model_dump()


@app.get("/api/explore")
async def explore(mode: Mode = "replay", delay: float = DEFAULT_DELAY) -> EventSourceResponse:
    calls, trace_id = adapter.explore_calls(mode)

    async def gen():
        n_ok = 0
        for c in calls:
            await asyncio.sleep(delay)
            n_ok += int(c["ok"])
            yield {"event": "call", "data": json.dumps(c)}
        yield {
            "event": "done",
            "data": json.dumps({"trace_id": trace_id, "n_calls": len(calls), "success": n_ok == len(calls)}),
        }

    return EventSourceResponse(gen())


class DistillIn(BaseModel):
    trace_id: str | None = None


@app.post("/api/distill")
def distill(body: DistillIn, mode: Mode = "replay") -> Any:
    spec = adapter.distill(mode, body.trace_id)
    return {
        "task_spec": spec.model_dump(mode="json"),
        "equivalence_sets": adapter.equivalence_tools(spec),
    }


@app.get("/api/candidates")
def candidates(mode: Mode = "replay") -> Any:
    return [c.model_dump() for c in adapter.candidates(mode)]


@app.get("/api/score")
async def score(
    candidate: str,
    mode: Mode = "replay",
    task_id: str | None = None,
    equiv_overrides: str | None = Query(default=None, description="comma-separated enabled tool names"),
    delay: float = DEFAULT_DELAY,
) -> EventSourceResponse:
    enabled = {t.strip() for t in equiv_overrides.split(",") if t.strip()} if equiv_overrides else None
    calls = adapter.candidate_calls(mode, candidate)
    done = adapter.score(mode, task_id, candidate, enabled)

    async def gen():
        for c in calls:
            await asyncio.sleep(delay)
            yield {"event": "call", "data": json.dumps(c)}
        for v in done.checkpoints:
            await asyncio.sleep(delay * 0.4)
            yield {"event": "checkpoint", "data": json.dumps({"n": v.n, "met": v.met})}
        yield {"event": "done", "data": done.model_dump_json()}

    return EventSourceResponse(gen())


@app.get("/api/leaderboard")
def leaderboard(mode: Mode = "replay") -> Any:
    return adapter.leaderboard(mode).model_dump()


# Friendly error envelope for the demo (no stack traces to the visitor).
@app.exception_handler(adapter.SandboxViolation)
def _sandbox_handler(_req, exc: adapter.SandboxViolation) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "sandbox", "detail": str(exc)})


@app.exception_handler(NotImplementedError)
def _live_handler(_req, exc: NotImplementedError) -> JSONResponse:
    return JSONResponse(status_code=501, content={"error": "live_unsupported", "detail": str(exc)})


# Serve the SPA same-origin (no CORS). Mounted LAST so it only catches paths the
# /api/* routes above didn't match.
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
