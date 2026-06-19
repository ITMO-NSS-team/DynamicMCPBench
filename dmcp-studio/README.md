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
├── frontend/                   # SPA built from the dmcp_studio.html mockup (A2)
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

_Backend/frontend land in A1–A2. Until then:_

```bash
uv pip install -e ".[servers,dev]"   # from the repo root; [studio] extra lands with A1
```
