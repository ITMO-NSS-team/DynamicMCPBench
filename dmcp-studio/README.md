# DMCP Studio

An interactive, trace-grounded studio for **effect-scored** evaluation of LLM
agents over live MCP servers — the demonstration companion to DynamicMCPBench.
It walks through the pipeline in four live stages (**Collect → Explore →
Distill → Score**) and flips a candidate's verdict with an
**Effect ⇄ Answer** toggle.

> Status: **scaffolding (A0 complete).** The backend/frontend are being built
> per `docs/dmcp_studio_build_plan.md`. See `PROGRESS.md` for live status and
> `backend/INTEGRATION_NOTES.md` for how the studio wraps the `dmcp` pipeline.

## Layout

```
dmcp-studio/
├── PROGRESS.md                 # running build log
├── backend/                    # FastAPI app wrapping the dmcp pipeline (A1)
│   ├── INTEGRATION_NOTES.md    # A0: the pipeline map (built)
│   └── fixtures/               # frozen REPLAY runs (A1/E3)
├── frontend/                   # SPA: TypeScript (src/app.ts) bundled by Bun
│   ├── src/app.ts              # source; built to app.js via `bun run build`
├── experiments/                # studio validation: E1 agreement, E2 latency
└── scripts/                    # run_demo.sh (A6)
```

## Design invariants (from the parent repo)

- **Wrap, don't rewrite.** All real work flows through the existing `dmcp`
  pipeline; the backend never reimplements distillation or scoring.
- **REPLAY is the default**, deterministic and booth-safe; **LIVE** is an
  explicit toggle that drives the real pipeline against read-only servers.
- **Effect-scored only.** `answer_pass` is a studio-side demo foil for the
  toggle, never a benchmark verdict (see `backend/INTEGRATION_NOTES.md` §6).
- **Sandbox default-deny.** No tool runs on a `stateful_write` server unless it
  is flagged sandboxed.

## Quickstart

```bash
# from the repo root
uv pip install -e ".[studio]"        # fastapi + uvicorn + sse-starlette

# (re)build the frozen showcase fixture — asserts the three verdicts
uv run python dmcp-studio/experiments/e3_curate.py

# build the TypeScript frontend (Bun) → frontend/app.js
cd dmcp-studio/frontend && bun install && bun run build && cd -

# run the REPLAY backend (serves the SPA same-origin)
cd dmcp-studio && uvicorn backend.app:app --reload
```

The frontend is TypeScript (`frontend/src/app.ts`), bundled to `frontend/app.js`
by Bun. The bundle is committed so the demo runs without a build step; rerun
`bun run build` (or `bun run check` to typecheck first) after editing the source.

Then the API is live (default `mode=replay`):

```bash
curl localhost:8000/api/servers
curl "localhost:8000/api/explore?delay=0"                       # SSE: 7 calls + done
curl "localhost:8000/api/score?candidate=hermes3-8b&delay=0"    # effect-fail / answer-pass
```

The frontend (built from the `dmcp_studio.html` mockup) wires to these in A2.
