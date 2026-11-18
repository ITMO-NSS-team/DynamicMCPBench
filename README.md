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

## Citation

```bibtex
@inproceedings{kaminski-etal-2026-dynamicmcpbench,
    title = "{D}ynamic{MCPB}ench: A Trace-Grounded, Effect-Scored Benchmark for {LLM} Agents over Live {MCP} Servers",
    author = "Kami{\'n}ski, Jerzy  and
      Galyukshev, Ilya  and
      Kuznetsov, Artem  and
      Chuprin, Sergey  and
      Redko, Kirill  and
      Shumbalov, Aidar  and
      Kalyuzhnaya, Anna",
    editor = "Atanasova, Pepa  and
      Haffari, Gholamreza  and
      Wang, Minghan",
    booktitle = "Proceedings of the 2026 Conference on Empirical Methods in Natural Language Processing: Industry Track",
    month = oct,
    year = "2026",
    address = "Budapest, Hungary",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2026.emnlp-industry.202/",
    doi = "10.18653/2026.emnlp-industry.202",
    pages = "3391--3411",
    ISBN = "979-8-89176-460-6",
    abstract = "Large language model (LLM) agents are increasingly deployed over Model Context Protocol (MCP) servers, yet the benchmarks used to evaluate them score the final answer or a fixed ``ground-truth'' list of tools, both of which are fragile once the underlying data is live and stateful. We present DynamicMCPBench, a reusable framework rather than a fixed dataset. A practitioner can run it on their own MCP servers to test models on their own tasks, or let it collect servers automatically to measure a model{'}s general ability to solve agentic tasks. Given the servers and any set of models, it generates realistic goals, pursues each one live to record a successful trajectory, distills that trajectory into path-agnostic effect checkpoints, and scores an agent on whether it reproduces those effects, never on the final answer. To show what the framework reveals, we run it at scale: 24 models over 121 servers and 750 tasks spread evenly over 15 task categories (50 each), where each category targets a distinct tool-use challenge of the generated questions. Each task is scored by pass{\textasciicircum}3, it counts as solved only if all three independent attempts succeed. Even the strongest agents solve only about half of the tasks, 31{\%} of tasks are solved by no model at all, and accuracy collapses as the required tool chain grows longer (from 39{\%} on the shortest chains to 13{\%} on the longest). A human validation study confirms the automatic scoring is reliable (chance-corrected agreement of 0.76). DynamicMCPBench thus turns benchmark construction into something practitioners can rerun on their own servers and models, while exposing a consistent inability of current agents to handle long, multi-step agentic tasks."
}
```

## License

Apache-2.0.
