# DMCP Studio — progress log

Running log per the build plan §10. One bullet per change; newest at top.
Plan: `docs/dmcp_studio_build_plan.md`. Map: `backend/INTEGRATION_NOTES.md`.

## Milestone status

| ID | Milestone | Status |
|---|---|---|
| A0 | Map the existing pipeline | ✅ done — `backend/INTEGRATION_NOTES.md` |
| A1 | Adapter + REPLAY-only backend | ✅ done — FastAPI app, 6 routes, SSE |
| A2 | Port the frontend to the backend | ✅ done — SPA wired via fetch/SSE |
| A3 | Wire LIVE mode | ✅ plumbing done; live-explore blocked upstream (see below) |
| A4 | Bring-your-own-server (stretch) | ⬜ |
| A5 | Polish & demo-safety | ⬜ |
| A6 | Package for submission | ⬜ |
| E1 | Studio-vs-batch agreement | ✅ done — 100% (118 pairs, 708 checkpoints) |
| E2 | Latency budget | ⬜ |
| E3 | Showcase fixtures | ✅ done — showcase_aapl frozen (A1) |

## Log (newest first)

- **Paper main figure captured.** `experiments/capture_screenshot.py` drives the
  REPLAY backend in headless Chromium (Playwright) through all four stages to
  the scoring stage and shoots the hero figure: the `hermes3-8b` candidate
  marked **FAILED** (income-statement checkpoint \#5 unmet) while its prose
  would pass answer-matching — the verdict flip. Committed as
  `paper_demo/figures/fig_studio.png` and wired into `fig:studio`
  (`figures/studio_screenshot.tex`, caption updated). Paper compiles; main text
  still ends on p4 (≤6pp). Playwright is opt-in (documented in the script,
  not a pinned dep).
- **E1 done — studio-vs-batch agreement = 100%.** New harness
  `experiments/e1_agreement.py` scores 118 deterministic (spec, candidate)
  pairs (22 pass / 96 fail) two ways: the studio core
  (`dmcp_adapter.score_pair`, the exact `/api/score` path) vs. the real
  `dmcp eval --candidate-traces` CLI as a subprocess. Overall verdict 118/118
  and all 708 per-checkpoint verdicts agree exactly — the studio's JSON
  round-trip doesn't perturb the deterministic Tier-1 verdict. Refactored the
  adapter to share `score_pair` between the route and E1. Report:
  `docs/experiments/studio-e1-agreement.md`; numbers in the paper's
  `tab:agreement`. No network/LLM; reproducible.

## Known blocker — live-explore disabled by a dependency regression

The live smoke (real run) surfaced a pipeline/dependency bug that blocks live
goal-gen/explore end-to-end. **REPLAY (the default, graded path) is unaffected;
LIVE falls back to REPLAY automatically, so the demo is safe.** Two findings,
both reproduced with NO studio code and NO paid calls:

1. **`dmcp/goal_gen.py::_fetch_tool_specs`** wraps the recorder in
   `anyio.move_on_after`, which raises `RuntimeError: Attempted to exit a cancel
   scope that isn't the current task's current cancel scope` under
   `asyncio.run`. Fix is known (wrap a self-contained capture coroutine in
   `asyncio.wait_for`) — not landed (shared pipeline code; needs sign-off).
2. **`TraceRecorder` teardown persistently poisons the event loop.** After one
   recorder closes, *every* subsequent `anyio.to_thread` on that loop is
   `CancelledError` (verified across 3 consecutive calls). openai 2.x runs its
   one-time `get_platform()` via `anyio.to_thread`, so the first LLM call after
   any recorder teardown dies — and the whole uvicorn loop stays poisoned.
   Repro:
   ```python
   async with TraceRecorder(...): pass
   await anyio.to_thread.run_sync(time.sleep, 0)   # -> CancelledError, persistently
   ```

**Root cause:** version drift. Installed `openai 2.38.0` (pin is only `>=1.40`),
`mcp 1.27.1`, `anyio 4.13.0`. openai 2.x is the proximate trigger; the
mcp/anyio recorder teardown is the underlying poison. Because the poison is
persistent and loop-local, cheap studio-side workarounds (pre-warm) do NOT
work — the recorder and the LLM call cannot share a loop once a teardown
happens.

**Decision:** do NOT rush a fix into shared pipeline code under the demo
deadline. Keep the studio REPLAY-default + LIVE-fallback (shipped in A3). The
fix is its own deliberate task: try an `openai<2` pin (or an mcp/anyio bump) in
a throwaway env; if that doesn't clear it, isolate each recorder session in its
own event loop/thread so the poison can't reach the LLM loop. Revisit
post-demo-priority.

## Log

- **A3 done.** LIVE mode wires the real pipeline for **collect / goal /
  explore / distill** (`backend/live.py`), backed by `manifests/local.json`
  (curated read-only set: yfinance, arxiv, wikipedia). Explore streams real
  tool calls via a `StreamingRecorder` wrapper (wrap, don't patch `explore()`);
  a recorded trace is cached in-process so live `/api/distill` finds it. Every
  stage has a timeout and **graceful fallback to the REPLAY fixture** if a
  server is unreachable (surfaced to the UI as a `fellback` event / banner).
  **Scoring stays deterministic replay** even in LIVE — the graded path (risk
  register). Sandbox default-deny gate runs before any live connection. Header
  has a **LIVE/REPLAY toggle** (default REPLAY) that restarts the walkthrough.
  8 new deterministic tests (streaming wrapper, manifest server list, and
  fallback for every live route) — **no network in the gate**. Real runs are
  the opt-in `scripts/live_smoke.py --yes-spend`. 27 studio tests; frontend
  typechecks + bundles. *Real live end-to-end not yet executed here (paid).*
- **A2 done.** Ported the `dmcp studio.html` mockup into `frontend/`
  (`index.html` + `styles.css` verbatim from the mockup). The script is
  **TypeScript** (`frontend/src/app.ts`, strict), bundled to `frontend/app.js`
  by **Bun** (`bun run build`; `bun run check` typechecks first). API payloads
  are typed to mirror `backend/models.py`. The committed bundle lets the demo
  run without a build step. Rewired from canned data to
  `fetch` + `EventSource`. The four-stage click-through now runs against the
  real backend: servers → goal → explore (SSE) → distill (renders the TaskSpec +
  editable equivalence chips) → score (SSE). The Effect/Answer toggle is a pure
  re-render over the one `done` payload (both verdicts), never a second call;
  toggling an equivalence-set member re-scores live via `equiv_overrides`.
  FastAPI serves the SPA same-origin (no CORS). 19 studio tests (added SPA
  serving). **Acceptance:** live HTTP click-through reproduces all three
  verdicts; disabling `get_price_history` flips the clean candidate to FAILED.
  `app.js` passes `node --check`. (Remaining: a real in-browser pass.)
- **A1 done.** REPLAY-only backend, all six routes (build plan §4) over a
  FastAPI app; explore/score stream call-by-call over SSE. The adapter
  (`backend/dmcp_adapter.py`) is the sole integration point and runs the **real
  deterministic `evaluate()`** on the frozen fixture — so REPLAY exercises the
  pipeline scorer, not a mock. `answer_pass` is a studio-side foil only.
  Fixtures built + verdict-asserted by `experiments/e3_curate.py`
  (`backend/fixtures/showcase_aapl.json`). Sandbox default-deny gate +
  18 studio tests (sandbox, adapter verdicts, HTTP/SSE). Dep: optional
  `[studio]` extra (fastapi/uvicorn/sse-starlette). **Acceptance met:** live
  `uvicorn` smoke — all routes 200, explore streams 7 calls, score shows the
  answer-pass/effect-fail disagreement over HTTP. Equivalence-override re-score
  works (disable `get_price_history` → clean candidate fails cp3).
- **A0 done.** Read every pipeline entry point from source and wrote
  `backend/INTEGRATION_NOTES.md`: data models to reuse, per-stage entry points
  (collect/goal/explore/distill/score), the exact candidate-run-under-replay
  recipe, and the replay world. **Key finding:** the pipeline computes *only*
  the effect verdict — there is no answer-matching scorer in `dmcp/` (invariant
  #1), so the Effect⇄Answer toggle's `answer_pass` is a studio-side demo foil,
  never a benchmark number.
- **Skeleton created.** `dmcp-studio/{backend,frontend,experiments,scripts}`
  per build plan §3 (the demo *paper* stays in `paper_demo/`, so
  `dmcp-studio/paper/` is intentionally omitted).

## Open decisions to confirm before A1

- **Dependency:** A1 needs FastAPI + an SSE helper (uvicorn, sse-starlette or
  manual). Proposed as an optional `[studio]` extra in `pyproject.toml` so core
  `dmcp` stays lean (CLAUDE.md: no heavy dep without PR discussion).
- **Sandbox default-deny** gets a unit test in A1 (build plan §10).
