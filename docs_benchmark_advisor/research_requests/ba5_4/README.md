# BA5.4 Deep Research Request Pack

Purpose: this folder contains delegation-ready research cards for BA5.4,
"Statistical Engine and real planning statistics", in DynamicMCPBench Benchmark
Advisor.

Each card is intended for a separate deep-research agent. The cards are context
documents, not implementation prompts. The expected result from each agent is a
source-backed, implementation-oriented answer that can be converted into
deterministic Python code, tests, golden fixtures, and UI-facing wording.

## Project Context

DynamicMCPBench evaluates agents that use MCP tools. The Benchmark Advisor is a
pre-run planning module that helps a user design a statistically defensible
benchmark before generation or evaluation starts.

The advisor must turn a user's benchmark objective into:

- a scoped statistical claim;
- a benchmark mode: `pairwise`, `leaderboard`, `regression`, `diagnostic`, or a
  weaker smoke / exploratory framing;
- task budget and attempts-per-task recommendations;
- target detectable effect or non-inferiority margin handling;
- task distribution and diagnostic slice coverage;
- confirmatory vs exploratory boundaries;
- missingness and multiplicity policies;
- power / MDE / CI-width planning diagnostics;
- alternatives and repair actions;
- local citations and assumption caveats.

BA5.1 already introduced v2 schema contracts. BA5.2 introduced a local,
offline citation index over `STATISTICAL_GUIDE.md`. BA5.3 implemented a
guide-first v2 composition layer and a minimal deterministic engine. BA5.4 is
still open: it must expand the MVP into a full deterministic Statistical Engine
for real pre-run planning statistics.

## Key Local References

Use these repo documents as the contract boundary:

- `docs_benchmark_advisor/research_requests/ba5_4/00_current_contract_snapshot.md`
- `docs_benchmark_advisor/planning/STATISTICAL_ENGINE_DESIGN.md`
- `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`
- `docs_benchmark_advisor/planning/INTERFACES.md`
- `docs_benchmark_advisor/planning/TASKS/T14-real-planning-statistics.md`
- `benchmark_advisor/v2_schema.py`
- `benchmark_advisor/v2_engine.py`
- `benchmark_advisor/stats.py`
- `benchmark_advisor/validator.py`

Existing statistical helper modules that may be relevant:

- `dmcp/curves.py` for Wilson confidence intervals;
- `dmcp/ablation.py` for power-style calculations and multiple-comparison
  helpers;
- `dmcp/baselines/rq1_compare.py` for Kendall tau / ranking comparison ideas;
- `dmcp/baselines/rq4_agreement.py` for agreement and deterministic reporting
  patterns.

## Hard Boundaries

The BA5.4 engine must not:

- launch benchmark generation;
- launch evaluation;
- perform post-run inference from actual outcome tensors;
- use live web retrieval at runtime;
- let RAG, LLM prose, or citation snippets decide approval/refusal;
- treat repeated attempts on the same task as independent iid tasks;
- present planning MDE/power as final inferential proof;
- hide weak alternatives or unsupported claim boundaries.

The engine should be valuable with only deterministic calculators and the local
statistical guide. Empirical priors may be optional if they are clearly labeled
and have a deterministic no-prior fallback.

## Expected Research Output

Every delegated answer should include:

1. Recommended rule/value/formula/template.
2. Conditions under which it applies.
3. Conditions under which it must not be used.
4. Source-backed rationale.
5. Implementation mapping to advisor fields or tests.
6. Failure modes and caveats.
7. Concrete examples using DynamicMCPBench-style benchmark planning.

Prefer tables and checklists over long essay prose. Avoid vague advice such as
"collect more data" unless it is translated into a concrete field edit, e.g.
`task_budget >= 240`, `confirmatory_slice_limit = 2`, or
`target_detectable_effect_pp = 12`.

## Cards

- `00_current_contract_snapshot.md`: exact current schemas, enums, dataclasses,
  constants, warning/refusal issue formats, thresholds, and `task_budget`
  semantics.
- `03_statistical_defaults.md`: default assumptions, budgets, branches, and
  planning constants.
- `04_mode_formulas.md`: mode-specific deterministic formulas and planning
  proxies.
- `05_status_thresholds.md`: approval / warning / refusal thresholds.
- `06_canonical_fixtures.md`: golden research fixtures for BA5.4 tests.
- `07_claims_repairs_wording.md`: controlled claim and repair wording.
