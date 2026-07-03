"""FastAPI app for DMCP Studio.

Six routes (build plan §4). REPLAY is the default and the graded path; LIVE
(A3) drives the real pipeline for collect/goal/explore/distill and falls back to
the REPLAY fixture if a live server is unreachable. Scoring stays on
deterministic replay even in LIVE mode (risk register: LIVE explore is proof,
not the graded path). The two slow stages stream call-by-call over SSE.

Run:  cd dmcp-studio && uvicorn backend.app:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from benchmark_advisor import AdvisorRequest, AdvisorValidationRequest
from benchmark_advisor.service import advisor_design, advisor_validate
from benchmark_advisor.v2_schema import AdvisorV2DesignRequest, AdvisorV2ValidationRequest
from benchmark_advisor.v2_service import advisor_v2_design, advisor_v2_validate

from . import dmcp_adapter as adapter
from . import live, replay_store
from .models import Mode

log = logging.getLogger("dmcp_studio")


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Pre-warm the REPLAY fixtures so the first request is already hot (A5).
    try:
        replay_store.load_showcase()
        replay_store.load_leaderboard()
        log.info("REPLAY fixtures pre-warmed")
    except Exception as e:  # a missing fixture shouldn't crash boot; routes surface it
        log.warning("fixture pre-warm skipped: %s", e)
    yield


app = FastAPI(title="DMCP Studio", version="0.1.0", lifespan=_lifespan)

# Default inter-event pacing for SSE (build plan §4: 300–600 ms). Overridable
# per request via ?delay= so tests can run with no wait.
DEFAULT_DELAY = 0.45


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode_default": "replay"}


@app.get("/api/servers")
def servers(mode: Mode = "replay") -> Any:
    if mode == "live":
        try:
            return [s.model_dump() for s in live.live_servers()]
        except Exception:
            return [s.model_dump() for s in adapter.list_servers("replay")]
    return [s.model_dump() for s in adapter.list_servers(mode)]


class GoalIn(BaseModel):
    server_ids: list[str] = []


@app.post("/api/goal")
async def goal(body: GoalIn, mode: Mode = "replay") -> Any:
    if mode == "live":
        try:
            return (await live.live_goal(body.server_ids)).model_dump()
        except Exception as e:
            out = adapter.generate_goal("replay", body.server_ids).model_dump()
            out["fellback"] = str(e)[:200]
            return out
    return adapter.generate_goal(mode, body.server_ids).model_dump()


async def _replay_explore_events(delay: float) -> AsyncIterator[dict]:
    calls, trace_id = adapter.explore_calls("replay")
    n_ok = 0
    for c in calls:
        await asyncio.sleep(delay)
        n_ok += int(c["ok"])
        yield {"event": "call", "data": json.dumps(c)}
    yield {
        "event": "done",
        "data": json.dumps({"trace_id": trace_id, "n_calls": len(calls), "success": n_ok == len(calls)}),
    }


@app.get("/api/explore")
async def explore(
    mode: Mode = "replay",
    delay: float = DEFAULT_DELAY,
    server_ids: str | None = None,
    goal: str | None = None,
    persona: str | None = None,
) -> EventSourceResponse:
    if mode == "live":
        ids = [s for s in (server_ids or "").split(",") if s] or live.SHOWCASE_SERVER_IDS

        async def live_gen() -> AsyncIterator[dict]:
            try:
                async for ev in live.stream_explore(ids, goal or "", persona):
                    yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                return
            except Exception as e:  # connect/LLM failure → fall back to the fixture
                yield {"event": "fellback", "data": json.dumps({"reason": str(e)[:200]})}
            async for ev in _replay_explore_events(delay):
                yield ev

        return EventSourceResponse(live_gen())
    return EventSourceResponse(_replay_explore_events(delay))


class DistillIn(BaseModel):
    trace_id: str | None = None


@app.post("/api/distill")
async def distill(body: DistillIn, mode: Mode = "replay") -> Any:
    fellback: str | None = None
    if mode == "live":
        try:
            spec = await live.live_distill(body.trace_id)
        except Exception as e:
            spec = adapter.distill("replay", body.trace_id)
            fellback = str(e)[:200]
    else:
        spec = adapter.distill(mode, body.trace_id)
    out: dict[str, Any] = {
        "task_spec": spec.model_dump(mode="json"),
        "equivalence_sets": adapter.equivalence_tools(spec),
    }
    if fellback:
        out["fellback"] = fellback
    return out


class RegisterIn(BaseModel):
    server_id: str
    transport: str = "stdio"  # stdio | streamable_http | sse
    command: str | None = None
    args: list[str] = []
    endpoint: str | None = None
    dynamism: str = "live_read"
    sandbox: bool = False
    description: str | None = None


@app.post("/api/register-server")
async def register_server(body: RegisterIn) -> Any:
    """A4 — bring-your-own-server: register a read-only MCP server at runtime,
    collect its tool surface, and make it explorable in LIVE mode."""
    try:
        card = await live.register_server(body.model_dump())
        return card.model_dump()
    except ValueError as e:  # bad input / sandbox-gate rejection
        return JSONResponse(status_code=400, content={"error": "invalid_server", "detail": str(e)})
    except adapter.SandboxViolation as e:
        return JSONResponse(status_code=403, content={"error": "sandbox", "detail": str(e)})
    except Exception as e:  # didn't boot / unreachable
        return JSONResponse(status_code=502, content={"error": "register_failed", "detail": str(e)[:200]})


@app.get("/api/candidates")
def candidates() -> Any:
    # Candidates come from the replay fixture; scoring is the graded replay path.
    return [c.model_dump() for c in adapter.candidates("replay")]


@app.get("/api/score")
async def score(
    candidate: str,
    task_id: str | None = None,
    equiv_overrides: str | None = Query(default=None, description="comma-separated enabled tool names"),
    delay: float = DEFAULT_DELAY,
) -> EventSourceResponse:
    # Scoring is ALWAYS deterministic replay — the graded path — even in LIVE.
    enabled = {t.strip() for t in equiv_overrides.split(",") if t.strip()} if equiv_overrides else None
    calls = adapter.candidate_calls("replay", candidate)
    done = adapter.score("replay", task_id, candidate, enabled)

    async def gen() -> AsyncIterator[dict]:
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


# --- Benchmark Advisor (Stage 0 — Design): pre-run planning gate (BA3.1) -------
# Deterministic planner -> validator -> export preview. Never launches generation
# or evaluation, never touches candidate scoring.


@app.post("/api/advisor/design")
def advisor_design_route(body: AdvisorRequest) -> Any:
    return advisor_design(body).model_dump(mode="json")


@app.post("/api/advisor/validate")
def advisor_validate_route(body: AdvisorValidationRequest) -> Any:
    return advisor_validate(body).model_dump(mode="json")


@app.post("/api/advisor/v2/design")
def advisor_v2_design_route(body: AdvisorV2DesignRequest) -> Any:
    return advisor_v2_design(body).model_dump(mode="json")


@app.post("/api/advisor/v2/validate")
def advisor_v2_validate_route(body: AdvisorV2ValidationRequest) -> Any:
    return advisor_v2_validate(body).model_dump(mode="json")


# Friendly error envelope for the demo (no stack traces to the visitor).
@app.exception_handler(adapter.SandboxViolation)
def _sandbox_handler(_req, exc: adapter.SandboxViolation) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "sandbox", "detail": str(exc)})


# Serve the SPA same-origin (no CORS). Mounted LAST so it only catches paths the
# /api/* routes above didn't match. Prefer the built Vite bundle (frontend/dist);
# fall back to frontend/ for a source checkout.
_FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"
_FRONTEND = _FRONTEND_ROOT / "dist" if (_FRONTEND_ROOT / "dist").is_dir() else _FRONTEND_ROOT
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
