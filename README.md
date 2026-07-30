# DynamicMCPBench

Trace-grounded benchmark generation for LLM agents from live Model Context Protocol (MCP) servers.

The benchmark is built by **observing successful agent trajectories** on real MCP servers, distilling them into path-agnostic effect checkpoints, and grading candidate agents on whether they recreate those effects — never on string-matching a final answer. This makes the benchmark robust to dynamic data (live web, live stock prices, live wikis) and removes the ground-truth-tool-list noise that plagues graph-sampling benchmarks.

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

## Quick start

```bash
uv pip install -e ".[servers]"        # installs dmcp + the 7 substrate MCPs
uv run dmcp record .venv/bin/wikipedia-mcp -t stdio -s wiki --tool search_wikipedia --args '{"query":"Alan Turing"}'

# Generate a benchmark
uv run dmcp goal-gen --manifest manifests/local.json --per-server 3 --cross-pairs 12 -o goals/auto.json
uv run dmcp generate goals/auto.json --traces-out traces/run.jsonl --specs-out specs/run.jsonl

# Evaluate a candidate against the generated benchmark, deterministically
uv run dmcp eval specs/run.jsonl --replay --reference-traces traces/run.jsonl --model anthropic/claude-haiku-4.5 -o evals/run_haiku45.jsonl
uv run dmcp report --specs specs/run.jsonl --evals evals/run_haiku45.jsonl -o reports/leaderboard.md
```

## Autonomous development

This repo can drive itself toward the paper, one reviewed step at a time, with
multiple Claude Code agents in parallel. Clone, run `claude`, and say `/continue`
(or «продолжи»): it claims the next step in [`docs/PLAN.md`](docs/PLAN.md),
implements it, opens a PR, and auto-merges when the gate (`ruff` + `pytest`) is
green. Protocol: [`docs/AUTONOMY.md`](docs/AUTONOMY.md). Background:
[`docs/CONCEPT.md`](docs/CONCEPT.md).

## Roadmap to EMNLP Industry Track

Aiming for **EMNLP 2026 Industry Track** (typical deadline: late July 2026; conference November 2026). Industry track favors applied/practical contributions over pure novelty, which fits this work: a real, runnable, reproducible benchmarking pipeline that generalizes to arbitrary MCP servers.

Legend: `[x]` done, `[~]` in progress, `[ ]` not started.

### Phase 1 — Substrate (Weeks 1-4 of the plan)

Live MCP corpus + dual-mode (record / replay) orchestrator.

- [x] Pydantic schema for `Trace / Step / ServerFingerprint / ToolSpec` (`dmcp/trace.py`)
- [x] `TraceRecorder` over stdio / SSE / streamable_http transports (`dmcp/recorder.py`)
- [x] Server-stderr suppression by default (so scaled crawls stay readable)
- [x] MCP Registry crawler with paged ingest of all 30,125 records (`dmcp/discovery/registry.py`)
- [x] Auto-install for pypi + npm packages (`dmcp/install.py`)
- [x] Smoke-vetter that classifies dynamism heuristically (`dmcp/vet.py`)
- [x] Curated 16-server substrate at `manifests/local.json`: 6 sandboxed + 10 public-API
- [x] Scaled to a **136-server canonical set** (`manifests/servers.json`): 120 crawled no-creds (portable `npx`/`uvx`, 100%-all-tools-pass, dependency-aware verify) + 16 substrate; tagged for subsetting, with `catalog.json` + `direct_alt.json`. Running experiments on subsets or the full set: **`docs/EXPERIMENTS.md`**.
- [x] `TraceReplayRecorder` with deterministic Tier-1 exact-match cache (`dmcp/replay.py`)
- [x] **Tier-2 semantic cache** — field-level normalization + difflib fallback, threshold-tunable, deterministic across machines
- [ ] **Tier-3 LLM tool simulator** — on cache miss + Tier-2 miss, an LLM generates a plausible response so the candidate can keep going (results flagged as simulated). Substrate is in place; just the simulator class to write
- [ ] Credential-injectable manifest tier (Bucket A: GitHub/Brave/Linear/Notion/Slack/Tavily/Supabase, etc.) — checklist at `docs/credentials_bucket_a.md`, env-var plumbing TBD once user provides keys
- [ ] Mine the 10,109-record full discovery scan for additional no-creds public-API candidates (Bucket B extension)

### Phase 2 — Generation (Weeks 5-12 of the plan)

Forward exploration + LLM-driven distillation into TaskSpecs.

- [x] Goal-seeded forward exploration loop (`dmcp/explorer.py`)
- [x] Auto goal-gen from server tool surfaces (`dmcp/goal_gen.py`)
- [x] Anti-hallucination rules in goal-gen (no inventing concrete paths/URLs/identifiers)
- [x] LLM-driven distiller into `TaskSpec` with OpenAI tool-call schema (`dmcp/distiller.py`)
- [x] Discriminated-union checkpoints: `ToolEffectCheckpoint` + `ValueProducedCheckpoint`
- [x] `ArgPredicate` with `must_include` (exact) + `must_match` (starts_with / contains / regex)
- [x] Deterministic feature extraction: `trace_depth`, `runtime_branching`, `state_coupling`, `recovery_required`
- [x] Batched `dmcp generate` (goal-gen → explore → distill → write specs JSONL) with stratification summary
- [x] Scaling demonstration: 60 goals → 56 specs (93% distill rate) on the 16-server manifest
- [ ] Persona seeding library — currently free-form persona field; want a curated set of personas/intents that yields more diverse goals
- [ ] Target ~2-3k task corpus stratified by trace depth × dynamism × cross-server × recovery (currently 1527 validator-valid specs on the shared HF dataset after E8.7 v1+v2 across 4 contributors)
- [ ] Cross-server scenarios with credentialed servers (blocked on Phase 1 credential tier)

### Phase 3 — Evaluation (Weeks 13-20 of the plan)

Multi-tier scoring + multi-agent runs.

- [x] Tier-1 deterministic scorer: per-checkpoint pass/fail with evidence (`dmcp/evaluator.py`)
- [x] Minefield detection + partial-order ordering verification
- [x] Multi-model leaderboard via `dmcp report` (currently Haiku 4.5 / Haiku 3.5 / Qwen3-8B)
- [x] Stratification breakdown in the report (dynamism, depth, cross-server, state-coupling)
- [x] Replay mode wired into `dmcp eval` with reference-trace indexing
- [x] **Tier-2 LLM effect-equivalence judge** for failed `tool_effect` checkpoints (`dmcp/judge.py`)
- [x] Per-trace replay stats stashed in `seed_metadata.replay` (cache size, Tier-2 hits, cache misses)
- [ ] Tier-3 decomposed capability profile (planning / tool-selection / arg-filling / recovery — sub-scores per checkpoint family)
- [ ] `pass^k` reliability metric (run each agent k times, report success rate)
- [ ] External candidate-traces ingestion in `dmcp eval` (currently inline-only; needed so others can score their own runs against our specs)
- [ ] Expanded leaderboard: ≥5 candidate models including GPT-4o, Gemini, Sonnet 4.x, an open-weight 70B+ model

### Phase 4 — Robustness & living benchmark (overlaps Phase 3)

- [x] Refresh protocol (`dmcp/refresh.py`): re-execute reference against live, classify identical / drifted / schema_drift / state_decay / unresolved / skipped
- [x] Refresh preflight (`dmcp/preflight.py`): confirm required files, relations, credentials and write targets first; a task whose own environment is missing is quarantined, not counted as decay or as agent failure
- [ ] Decay metrics: track per-server drift rate over time, surface in the leaderboard
- [x] Refresh failure attribution (`dmcp/attribution.py`): retry transient errors with backoff, blame the server only when discovery confirms a changed/removed tool (`schema_drift`) or an intact schema over a vanished record (`state_decay`); everything else is `unresolved` and deferred to the next window instead of counted as decay
- [ ] LLM-assisted dynamism reclassification when the heuristic disagrees with observed drift

### Phase 5 — Paper + release

- [x] V0 vertical slice green end-to-end
- [x] Curated `docs/credentials_bucket_a.md` for reproducibility (anyone can stand up the credentialed tier)
- [ ] **Section 1 — Introduction**: motivate trace-grounded > answer-matching for dynamic data, contrast with AGB / MCPEval / MCP-Bench (orthogonality story)
- [ ] **Section 2 — Pipeline**: figure of crawl→goal-gen→explore→distill→eval; key design decisions (forward not backward, effect not answer, replay not live for fairness)
- [ ] **Section 3 — Substrate**: 16-server manifest table, dynamism breakdown, mining funnel (30k registry → 16 vetted public-API + sandboxed)
- [ ] **Section 4 — Method**: TaskSpec schema, checkpoint discriminated union, ArgPredicate matching, Tier-1/Tier-2 replay
- [ ] **Section 5 — Experiments**: RQ1-RQ4 from the research plan
- [ ] **Section 6 — Reliability**: 200-task human-validation subset (annotators rate checkpoint quality + spec realism)
- [ ] **Section 7 — Limitations**: cache size, public-API skew, no-creds tier ceiling
- [ ] HuggingFace dataset release (specs JSONL + reference traces)
- [ ] Living leaderboard page (auto-rerun on each refresh)

### Phase 6 — Camera-ready (EMNLP 2026 Industry Track)

Ledger: `docs/CAMERA_READY.md` (each item names the reviewer it answers). Steps:
E9.1-E9.13 in `docs/PLAN.md`.

- [x] Paper text: narrow Principle 1 to a measured invariant, disambiguate the
      two "Tier-2" mechanisms, state the replay path-freedom and tool-exposure
      scope boundaries, add the missing limitations (E9.1)
- [x] Appendix: generation funnel, human confusion matrix, open-universe table (E9.2)
- [x] Main body: leave-own-family-out leaderboard + decay per domain (E9.3)
- [ ] Distiller-fidelity audit — gated on obtaining the annotation protocol (E9.4)
- [x] Restore the six-strategy distractor ablation (E9.5)
- [ ] **Run:** open-universe tool-exposure matrix — rag-k sweep, hier, flat,
      4 models, pass^3 (E9.6)
- [ ] **Run:** Tier-2 override rates per category across judge families (E9.7)
- [x] **Run:** widen the refresh beyond 22 traces / 3 families (E9.8): `scripts/decay_sweep.py` over 246 specs / 100 sampled servers → 938 live calls on 113 servers in 12 domains; 32.6% identical (36% narrow), 67.0% drifted, 0.4% attributably broken (≤25.8% upper bound)
- [ ] Annotate a second model for scorer strictness (E9.9)
- [x] Reference-validator tightening (E9.10), refresh preflight (E9.11) and the finer refresh classifier (E9.12)
- [x] Pre-submission verification sweep (E9.13): reproducibility statement cited by
      path against the HF release, Gwet AC1 regenerated by `scripts/ac1.py`, and the
      16% / 15.5% equivalence-set figures reconciled to one labelled 15.5%
      (`scripts/eqset_stats.py`)

### Research questions (paper-driving)

- [~] **RQ1 (headline)**: Does answer-matching mis-rank agents on dynamic-data tasks, and does trace alignment fix it? — *need to construct paired baseline: same models scored by string-match on final answer vs by trace-effect checkpoints; show ranking shuffles*
- [ ] **RQ2**: Does forward exploration produce more realistic / diverse / executable tasks than backward graph-sampling (AGB) or direct generation (MCPEval)? — *need a head-to-head: regenerate a slice of the corpus using each method, compare on solvability + diversity metrics*
- [ ] **RQ3**: Which emergent trace properties predict agent failure? — *fit a model on (depth, branching, state_coupling, cross_server, dynamism) → pass/fail per model; report feature importances*
- [ ] **RQ4**: How reliable is trace-based scoring vs human judgment? — *the 200-task validation subset feeds this directly*

### Differentiation from AgentGraphBench (sister project)

DynamicMCPBench is a deliberate structural pivot from AGB (the team's submitted NeurIPS paper) — every choice must stay orthogonal. See `memory/feedback_agb_orthogonality.md` for the full rule set; the headline is: **trace is the primitive (not a dependency graph), forward exploration (not backward subgraph sampling), effect alignment (not final-answer matching), live servers (not a static cached catalog)**.

### Current state (EMNLP 2026 Industry Track — accepted, camera-ready in progress)

The paper is accepted; the released dataset and evaluation records live in the
HuggingFace dataset (`scripts/release_hf.py`), including the per-run verdicts at
`leaderboard_e8.10d/verdicts/evals_*.jsonl` that every reported number is
regenerated from. Headline slice: **750 tasks × 8 models × pass^3**, scored in
deterministic replay with Tier-1 effect checkpoints and **no LLM judge**.

Camera-ready work — what was promised to the four reviewers — is tracked
item-by-item in `docs/CAMERA_READY.md` and sequenced as steps **E9.1-E9.13** in
`docs/PLAN.md`. The one new experiment is the open-universe tool-exposure matrix
(`docs/experiments/e9.1-tool-exposure-matrix.md`), pre-registered before the run.

> The Phase 1-5 checkboxes above predate submission and are being re-audited
> under E9; `docs/PLAN.md` is the live ledger, not this list.

## Repo layout

```
dmcp/
  trace.py            schema: Trace / Step / fingerprints
  recorder.py         live MCP capture (stdio/SSE/HTTP)
  replay.py           deterministic replay + Tier-2 fuzzy cache
  manifest.py         servers + dynamism + sandbox validation
  llm.py              OpenRouter client
  explorer.py         goal-seeded forward exploration
  goal_gen.py         auto goal-gen from tool surfaces
  distiller.py        LLM-driven trace → TaskSpec
  spec.py             TaskSpec + discriminated checkpoint union
  evaluator.py        Tier-1 deterministic scorer
  judge.py            Tier-2 LLM effect-equivalence judge
  refresh.py          re-run reference traces, classify drift
  report.py           markdown leaderboard
  discovery/          MCP Registry client + schemas
  install.py          pypi + npm install helpers
  vet.py              smoke + dynamism classification
  cli.py              typer CLI: crawl/goal-gen/explore/distill/generate/eval/refresh/report/record
manifests/local.json  16-server substrate (6 sandboxed + 10 public-API)
docs/credentials_bucket_a.md  curated signup list for credentialed servers
reports/              generated leaderboards
```

## License

Apache-2.0.
