# DMCP Studio — progress log

Running log per the build plan §10. One bullet per change; newest at top.
Plan: `docs/dmcp_studio_build_plan.md`. Map: `backend/INTEGRATION_NOTES.md`.

## Milestone status

| ID | Milestone | Status |
|---|---|---|
| A0 | Map the existing pipeline | ✅ done — `backend/INTEGRATION_NOTES.md` |
| A1 | Adapter + REPLAY-only backend | ✅ done — FastAPI app, 6 routes, SSE |
| A2 | Port the frontend to the backend | ✅ done — SPA wired via fetch/SSE |
| A3 | Wire LIVE mode | ✅ done — live goal/explore/distill working (recorder bug fixed) |
| A4 | Bring-your-own-server (stretch) | ✅ done — register a server, explore it live |
| A5 | Polish & demo-safety | ✅ done — run_demo.sh, pre-warm, errors, a11y |
| A6 | Package for submission | ✅ done — Docker image, <10-min clean-checkout |
| E1 | Studio-vs-batch agreement | ✅ done — 100% (118 pairs, 708 checkpoints) |
| E2 | Latency budget | ✅ done — REPLAY booth path sub-ms; booth=REPLAY |
| E3 | Showcase fixtures | ✅ done — showcase_aapl frozen (A1) |

## Log (newest first)

- **A4 done — bring-your-own-server.** A visitor can register a read-only MCP
  server at runtime (stdio command or http(s) URL) on Stage 1; the backend
  validates it, enforces the sandbox default-deny (`stateful_write` refused
  unless sandboxed), opens it once to collect its tool surface (live, no LLM),
  and adds it to an in-process registry that the live goal/explore/distill path
  resolves (`augmented_manifest`). Frontend: a BYO form that switches to LIVE,
  reloads the grid, and auto-selects the new server. New route
  `POST /api/register-server`; 6 tests (input + sandbox validation; real
  collection of the local `time` server; bad-command 502). Verified headless:
  form → register → byo_time appears selected in LIVE. Depends on the recorder
  fix below (live capture). 457 tests green.
- **Recorder bug FIXED — LIVE mode works.** Rewrote `TraceRecorder`'s session
  management: each MCP server runs in its own `_SessionActor` task so the
  transport/`ClientSession` context managers open+close in LIFO order in one
  task (no `AsyncExitStack`), ending the cancel-scope corruption that poisoned
  the loop. +5 real-stdio integration tests (regression, real record, two
  sequential recorders, mid-session cancel, bad-server skip) against the local
  `time` server. Full suite 451 green; CLI `dmcp record` smoke OK; real live
  smoke on yfinance ran goal → 2 live tool calls → distill end to end. Resolves
  the blocker above.
- **Screencast script drafted.** `paper_demo/screencast_script.md` — a
  beat-by-beat, timed (~2:20, under the 2:30 cap) script for the mandatory
  screencast, grounded in the working REPLAY demo (collect → explore → distill →
  the hermes3-8b verdict flip → the stale-answer case → close). Honest about
  LIVE being REPLAY-backed. The user records the actual video.
- **A6 done — installable package (Docker).** The CFP's required demo link is
  satisfied by an installable package (accepted in lieu of a hosted URL).
  `dmcp-studio/Dockerfile` (+ `docker-compose.yml`, root `.dockerignore`) builds
  a self-contained image from a clean checkout: `docker build -f
  dmcp-studio/Dockerfile -t dmcp-studio .` then `docker run -p 8000:8000
  dmcp-studio` → http://localhost:8000, no API keys, no network (REPLAY). Ships
  the committed frontend bundle (no Node/Bun in-image) and pre-builds the REPLAY
  fixture at image-build time (a build-time verdict smoke test). README has the
  Docker + from-source quickstarts; the paper's Availability section points to
  the installable package. Image verified to build + serve + score end to end.
- **A5 done — polish & demo-safety.** (1) `scripts/run_demo.sh`: one command —
  builds the frontend if Bun is present, builds fixtures if missing, serves the
  SPA + API (verified end-to-end). (2) Backend pre-warms the REPLAY fixtures on
  startup (FastAPI lifespan) so the first request is hot. (3) Friendly,
  in-voice error banners on every data-load path (servers/goal/distill/
  candidates/leaderboard + interrupted SSE) — no stack traces to the visitor.
  (4) **A11y fix:** `prefers-reduced-motion` previously left trace-lines at
  `opacity:0` (invisible) — now forced visible (verified: 6/6 lines visible
  under reduced motion); plus a `:focus-visible` outline. Frontend typechecks +
  rebuilds; +1 pre-warm test (28 studio tests).
- **E2 done — latency budget.** `experiments/e2_latency.py` times the REPLAY
  booth path through the real routes (SSE pacing disabled → compute, not the
  cosmetic delay), n=200/stage: every stage is **< 1.4 ms**, the evaluator is
  0.021 ms/pair over the 118-battery, and cold-start → first verdict is
  **≈ 1.3 ms** (vs the 30 s A5 bar). Decision rule result: the booth runs
  REPLAY for every stage — forced by the live blocker and also the right call
  on the numbers. Report `docs/experiments/studio-e2-latency.md`; paper
  `tab:latency` + prose filled. Deterministic, no network/LLM.
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

## RESOLVED — live-explore recorder bug (fixed in `dmcp/recorder.py`)

**Fixed.** Root cause was `TraceRecorder` driving the MCP `stdio_client` /
`ClientSession` context managers through an `AsyncExitStack` closed later —
which violates anyio's LIFO cancel-scope rule under asyncio and corrupted the
calling task's cancel scope on teardown (every later `await` → `CancelledError`).
Fix: each server now runs in its own `_SessionActor` task that opens and closes
its MCP context managers in LIFO order within that one task. Validated:
`async with TraceRecorder(...): pass` then `await asyncio.sleep(0)` no longer
raises (regression test in `tests/test_recorder_teardown.py`), the full suite
(451) is green, the CLI `dmcp record` smoke works, and a **real live smoke**
(`live_smoke.py --yes-spend yfinance`) ran goal → 2 live tool calls → distill
(3-checkpoint TaskSpec) end to end. The studio's LIVE mode now works (it still
falls back to REPLAY on a server outage). Original diagnosis kept below for the
record.

### Original diagnosis (now fixed)

The live smoke (real run) surfaced a pipeline/dependency bug that blocked live
goal-gen/explore end-to-end. **REPLAY (the default, graded path) was unaffected;
LIVE fell back to REPLAY automatically.** Two findings, both reproduced with NO
studio code and NO paid calls:

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

**Root cause (deepened — two hypotheses tested and RULED OUT, all free):**

- *Not an openai version issue.* Pinned `openai>=1.40,<2` (got 1.109.1) and
  re-ran the repro: the poison persists. openai 1.x has the **same**
  `self._platform = await asyncify(get_platform)()` (`_base_client.py:1494`,
  gated on `_platform is None`) — so it hits the same `anyio.to_thread`. The
  openai version is the *victim*, not the cause. Pin reverted (2.x is what the
  pipeline currently runs on; no unjustified change).
- *Not just `to_thread`; the whole task is left cancelled.* After one recorder
  teardown, **every** await on that task raises `CancelledError` — verified for
  `asyncio.sleep(0.01)`, a plain coroutine, AND a real `httpx` GET, not only
  `to_thread`. So a platform pre-warm cannot help either: the httpx request that
  carries the LLM call is itself cancelled.

The true cause is the **`TraceRecorder` MCP-session teardown** (`mcp 1.27.1` /
`anyio 4.13.0` under `asyncio.run`): closing the `stdio_client`/`ClientSession`
task groups across task boundaries leaves a corrupted cancel scope on the
calling task, cancelling everything after it. This is shared pipeline code the
industry-paper pipeline depends on.

**Decision:** do NOT rush a fix into shared pipeline code under the demo
deadline. Keep the studio REPLAY-default + LIVE-fallback (shipped in A3). The
real fix is a deliberate, separately-validated task on the recorder's session
lifecycle: manage each MCP `stdio_client`/`ClientSession` within a single task
(avoid closing its task group from a different task than entered it) — e.g. a
per-session dedicated task/thread + its own event loop — and add a regression
test (`async with TraceRecorder(...): pass` then `await asyncio.sleep(0)` must
not raise). The cheap pin/pre-warm routes are now disproven, so the next attempt
should go straight at the recorder.

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
