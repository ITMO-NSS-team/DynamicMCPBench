# DMCP Studio — progress log

Running log per the build plan §10. One bullet per change; newest at top.
Plan: `docs/dmcp_studio_build_plan.md`. Map: `backend/INTEGRATION_NOTES.md`.

## Milestone status

| ID | Milestone | Status |
|---|---|---|
| A0 | Map the existing pipeline | ✅ done — `backend/INTEGRATION_NOTES.md` |
| A1 | Adapter + REPLAY-only backend | ✅ done — FastAPI app, 6 routes, SSE |
| A2 | Port the frontend to the backend | ✅ done — SPA wired via fetch/SSE |
| A3 | Wire LIVE mode | ⬜ next |
| A4 | Bring-your-own-server (stretch) | ⬜ |
| A5 | Polish & demo-safety | ⬜ |
| A6 | Package for submission | ⬜ |
| E1 | Studio-vs-batch agreement | ⬜ |
| E2 | Latency budget | ⬜ |
| E3 | Showcase fixtures | ⬜ |

## Log

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
