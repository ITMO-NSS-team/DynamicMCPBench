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
├── frontend/                   # SPA: React + Geist (Vercel) kit, built by Vite
│   ├── src/                    # React app (main.tsx, App.tsx, stages/, components/)
│   │                           #   built to frontend/dist via `npm run build`
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

### Docker (no toolchain needed)

From a clean checkout — the only requirement is Docker:

```bash
docker build -f dmcp-studio/Dockerfile -t dmcp-studio .   # from the repo root
docker run --rm -p 8000:8000 dmcp-studio
# → open http://localhost:8000
```

or with Compose: `docker compose -f dmcp-studio/docker-compose.yml up --build`.
A Node stage builds the SPA and the image ships only the built bundle plus a
pre-built REPLAY fixture, so it runs offline with no API keys (REPLAY is the
default, deterministic path).

### From source

One command (builds the frontend if Node is present, builds fixtures if missing,
serves the SPA + API):

```bash
uv pip install -e ".[studio]"        # once: fastapi + uvicorn + sse-starlette
dmcp-studio/scripts/run_demo.sh      # → http://127.0.0.1:8000  (PORT=… to override)
```

`run_demo.sh` checks any existing Studio server on the selected port before it
rebuilds `frontend/dist`. If that server is an older backend without the current
advisor v2 routes, the script stops and asks you to stop the stale process first.
This avoids serving a fresh frontend bundle from an old API process.

Or run the pieces by hand:

```bash
# (re)build the frozen showcase fixture — asserts the three verdicts
uv run python dmcp-studio/experiments/e3_curate.py
# build the React frontend (Vite) → frontend/dist
cd dmcp-studio/frontend && npm install && npm run build && cd -
# restart the REPLAY backend after backend or frontend changes; it serves the SPA
# same-origin and fixtures are pre-warmed on boot
cd dmcp-studio && uvicorn backend.app:app --reload
```

The frontend is a React + Geist (Vercel) SPA (`frontend/src/`), built to
`frontend/dist` by Vite; the backend serves that bundle when present. During
development, `npm run dev` runs Vite with HMR and proxies `/api` to the backend
on `:8000` (run `uvicorn backend.app:app` alongside it).

Then the API is live (default `mode=replay`):

```bash
curl localhost:8000/api/servers
curl "localhost:8000/api/explore?delay=0"                       # SSE: 7 calls + done
curl "localhost:8000/api/score?candidate=hermes3-8b&delay=0"    # effect-fail / answer-pass
```

The React frontend wires to these.

### LIVE mode

The header toggle switches **REPLAY** (default, deterministic, booth-safe) to
**LIVE**, which drives the real pipeline for collect/goal/explore/distill against
read-only servers in `manifests/local.json`; if a server is unreachable the stage
falls back to the REPLAY fixture. **Scoring always uses deterministic replay** —
the graded path. A real end-to-end live run (paid LLM calls; needs
`OPENROUTER_API_KEY` and `".[servers]"`):

```bash
uv run python dmcp-studio/scripts/live_smoke.py --yes-spend   # default: yfinance
```
