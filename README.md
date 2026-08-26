# DynamicMCPBench

Trace-grounded benchmark generation for LLM agents over live Model Context
Protocol (MCP) servers.

The benchmark is built by **observing successful agent trajectories** on real MCP
servers, distilling them into path-agnostic **effect checkpoints**, and grading
candidate agents on whether they recreate those effects — never on string-matching
a final answer. This makes it robust to dynamic data (live web, live prices, live
wikis) and removes the ground-truth-tool-list noise that plagues graph-sampling
benchmarks. The design rationale is in [`docs/CONCEPT.md`](docs/CONCEPT.md).

## Pipeline

```
MCP Registry crawl  →  goal-gen  →  forward exploration  →  distill
                                          (live MCP)         (LLM-driven)

                                                                  ↓
                                                            TaskSpec JSONL
                                                                  ↓
                                            evaluate (replay, Tier-1 + Tier-2)
                                                                  ↓
                                                          markdown leaderboard
```

CLI: `dmcp crawl / goal-gen / explore / distill / generate / eval / refresh / report / record`.

## Install

```bash
uv pip install -e ".[servers]"        # dmcp + the substrate MCP servers
cp .env.example .env                   # then set OPENROUTER_API_KEY (see the file)
```

Optional extras: `.[studio]` (the DMCP Studio web app), `.[dev]` (ruff + pytest),
`.[annotate]`. See [`docs/SETUP.md`](docs/SETUP.md) for standing up the
docker-compose substrate and the credentialed server tier.

## Quick start

```bash
# Smoke a single server (no benchmark run)
uv run dmcp record .venv/bin/wikipedia-mcp -t stdio -s wiki \
  --tool search_wikipedia --args '{"query":"Alan Turing"}'

# Generate a benchmark
uv run dmcp goal-gen --manifest manifests/local.json --per-server 3 --cross-pairs 12 -o goals/auto.json
uv run dmcp generate goals/auto.json --traces-out traces/run.jsonl --specs-out specs/run.jsonl

# Evaluate a candidate against the generated benchmark, deterministically
uv run dmcp eval specs/run.jsonl --replay --reference-traces traces/run.jsonl \
  --model anthropic/claude-haiku-4.5 -o evals/run_haiku45.jsonl
uv run dmcp report --specs specs/run.jsonl --evals evals/run_haiku45.jsonl -o reports/leaderboard.md
```

`dmcp eval/explore/generate/crawl` make paid LLM/network calls — run them
deliberately, not as casual checks.

## Components

- **[`dmcp/`](dmcp/)** — the benchmark framework and `dmcp` CLI
  (crawl → generate → eval → report), with deterministic Tier-1 effect scoring
  and an optional Tier-2 fuzzy/LLM-equivalence layer.
- **[`benchmark_advisor/`](benchmark_advisor/)** — a pre-run statistical planner
  that scopes a defensible benchmark (minimum detectable effect, power) before
  generation.
- **[`dmcp-studio/`](dmcp-studio/)** — an interactive web studio that drives the
  pipeline (collect → explore → distill → score) and flips a candidate's verdict
  between effect-based and answer-based grading. See its
  [`README.md`](dmcp-studio/README.md).

## Repo layout

```
dmcp/                 the benchmark framework + `dmcp` CLI
  trace.py            schema: Trace / Step / fingerprints
  recorder.py         live MCP capture (stdio/SSE/HTTP)
  replay.py           deterministic replay + Tier-2 fuzzy cache
  manifest.py         servers + dynamism + sandbox validation
  explorer.py         goal-seeded forward exploration
  goal_gen.py         auto goal-gen from tool surfaces
  distiller.py        LLM-driven trace → TaskSpec
  spec.py             TaskSpec + discriminated checkpoint union
  evaluator.py        Tier-1 deterministic scorer
  judge.py            Tier-2 LLM effect-equivalence judge
  refresh.py          re-run reference traces, classify drift
  report.py           markdown leaderboard
  cli.py              typer CLI entrypoint
benchmark_advisor/    pre-run statistical planner
dmcp-studio/          interactive studio (FastAPI + React)
manifests/local.json  substrate manifest (sandboxed + public-API servers)
docs/CONCEPT.md       design rationale and method catalogue
docs/SETUP.md         substrate + credentialed-tier setup
```

## License

Apache-2.0.
