# Benchmark Advisor Statistical Engine Design

Status: design contract for BA5.4 / T14.
Audience: implementation agents working on the v2 Benchmark Advisor.
Authority: `STATISTICAL_GUIDE.md` and deterministic validators remain
normative. This document defines the engine architecture and execution contract.

## Purpose

The Statistical Engine is the v2 advisor core that turns a user objective into a
defensible benchmark design before any benchmark is generated. It is not a UI
helper and not a post-hoc validator. It is the component that chooses, scores,
and explains candidate statistical designs.

The engine exists because v1 currently follows this rough shape:

```text
intent -> planner picks parameters -> validator checks -> rough planning stats
```

V2 must follow this shape:

```text
intent
  -> claim and method constraints
  -> Statistical Guide rules and citation snippets
  -> Statistical Engine parameter search and scoring
  -> deterministic rule gate
  -> recommended StatisticalPlan plus alternatives and repairs
  -> guarded export / launch only after user approval
```

The practical difference is important: task budget, attempts, target effect,
distribution weights, confirmatory slice count, missingness policy, and
multiplicity policy are engine outputs, not defaults that are explained after
the fact.

## Core Invariants

- The engine runs before the final v2 design is returned from
  `POST /api/advisor/v2/design`.
- The engine owns statistical parameter search, power/MDE planning, and
  candidate-design scoring.
- The MVP does not require a stat-agent or RAG layer. Optional agent/RAG support
  may later propose wording or alternatives, but deterministic code computes
  metrics and deterministic validators decide status, exportability,
  launchability, and claim boundaries.
- Stage 1 outputs are planning diagnostics, not final inferential guarantees.
  MDE and power must carry explicit `planning_heuristic` or `empirical_prior`
  provenance labels.
- Repeated attempts are never treated as independent tasks for iid CI/MDE.
- Pairwise same-task comparisons default to paired task-level methods.
- Leaderboards must include rank-stability planning, not point ranks only.
- Diagnostic slices are exploratory unless explicitly predeclared, powered, and
  covered by a multiplicity plan.
- Public logs can calibrate priors, but cannot prove private-deployment
  behavior.
- The engine must be deterministic for a fixed request, guide snapshot,
  configuration, and random seed.

## Inputs

The engine consumes structured inputs, not raw prompt prose alone.

Required inputs:

- `AdvisorRequest` or v2 successor request.
- Parsed intent signals:
  - requested mode or candidate modes;
  - primary question;
  - candidate models;
  - target deployment slice;
  - named domains, workflow lengths, server scope, and diagnostic pressure;
  - requested effect target or non-inferiority margin when supplied.
- Method constraints from `STATISTICAL_GUIDE.md`:
  - mode and claim-scope rules from G1;
  - estimand/metric rules from G2;
  - distribution rules from G3;
  - budget, power, repeats rules from G4;
  - criterion rules from G5;
  - claim-boundary rules from G6;
  - rationale/UI rules from G7.
- Guide citation/snippet index from `STATISTICAL_GUIDE.md` when available.
- Optional empirical priors:
  - public DynamicMCPBench logs;
  - pilot pass rates;
  - observed model correlation or discordance;
  - stratum variance / historical rank instability;
  - cluster or template design-effect estimates.
- Engine configuration:
  - allowed budget grid;
  - allowed attempt counts;
  - alpha / target power defaults;
  - minimum per-stratum counts;
  - maximum confirmatory slices;
  - maximum launchable corpus size for guarded handoff.

Missing optional priors must not block planning. They become assumption-ledger
entries and sensitivity branches.

## Outputs

The engine returns an `EngineDecision` that the v2 planner wraps into
`StatisticalPlan`.

Required output groups:

- `recommended_design`: the selected v2-compatible `AdvisorDesign`.
- `parameter_candidates`: all evaluated candidate designs, including rejected
  and warning candidates.
- `power_analysis`: `PowerAnalysis` with power/MDE curve, CI-width curve, budget
  alternatives, method labels, and assumptions.
- `design_alternatives`: cheap, recommended, and stronger alternatives.
- `assumption_ledger`: baseline rates, dependence, missingness, multiplicity,
  floor/ceiling, clustering, and private-transfer caveats.
- `issues`: all `StatisticalIssue` objects found during candidate scoring and
  validation.
- `citations`: local guide/source references used for method and rationale
  explanations.
- `claim_card`: allowed claims, not-allowed claims, and plain-language summary.
- `computation_trace`: deterministic provenance for formulas, priors, candidate
  grid, random seed, and selected decision rule.

The v2 API response must not hide weak alternatives. Users should see what their
budget buys and which claim downgrade happens at each budget.

## Component Architecture

```text
V2 service
  -> Intent normalizer
  -> Claim and method selector
  -> Guide citation adapter
  -> Statistical Engine
       -> candidate generator
       -> method-family calculators
       -> sensitivity runner
       -> candidate scorer
       -> repair generator
       -> computation trace builder
  -> Deterministic validator / issue aggregator
  -> v2 response composer
```

### Intent Normalizer

Normalizes raw intent into structured signals. It may use deterministic phrase
extraction and later an LLM proposer, but the engine only receives structured
signals. It must preserve evidence strings so each major parameter can explain
why it exists.

Examples:

- "short finance workflows" -> domain `finance`, short-chain emphasis, claim
  boundary limited to finance/short workflows unless the user asks for broader
  coverage and budget supports it.
- "hard negative tools with similar names" -> same-name / near-miss diagnostic
  pressure and diagnostic slice metadata.
- "which model is better" with two candidates -> pairwise model-selection
  method constraints.

### Claim And Method Selector

Chooses the statistical family before parameter search. It returns constraints,
not final numbers.

Required method families:

| Mode | Default planning family | Post-run family | Key constraints |
|---|---|---|---|
| `pairwise` | paired task-level delta planning with conservative MDE and optional empirical bootstrap power | paired bootstrap and optional approximate randomization | same tasks for both models; no unpaired primary comparison when paired data exists |
| `leaderboard` | rank-stability planning over task bootstrap / simulation | stratified bootstrap rank stability | model count >= 3; top-k and pairwise claims separated; multiplicity plan required |
| `regression` | non-inferiority margin planning | one-sided non-inferiority decision with CI | predeclared margin; fixed regression slice; no post-hoc margin |
| `diagnostic` | descriptive slice precision and coverage planning | descriptive rates or powered slice deltas if predeclared | no broad model-selection claim from diagnostic-only data |
| `smoke` | weak exploratory precision planning | descriptive only | claim downgraded to smoke-test-only |

### Guide Citation Adapter

The guide citation adapter supplies source-backed context and citations from
`STATISTICAL_GUIDE.md`. It must be local, offline, and auditable. A larger
retrieval/source-pack layer is optional future work.

Allowed uses:

- choose candidate method-family explanations;
- fill citation cards;
- explain why a rule exists;
- show UI tooltips and long-form rationale.

Forbidden uses:

- overriding validator thresholds;
- deciding approval/refusal by citation prose alone;
- introducing unreviewed runtime web text;
- producing a launchable export without deterministic validation.

### Candidate Generator

Builds a finite search space of benchmark designs.

Candidate axes:

- unique task budget;
- attempts per task;
- target detectable effect;
- alpha and target power;
- candidate model set;
- primary metric;
- method family;
- task distribution weights;
- confirmatory vs exploratory slices;
- distractor pressure;
- server scope;
- sandbox requirement;
- missingness policy;
- multiplicity policy.

The generator must include at least these named alternatives:

- `budget_minimum`: cheapest non-refused or smoke-only candidate.
- `recommended`: cheapest candidate that supports the requested claim, or the
  strongest honest downgrade if the requested claim is impossible.
- `stronger`: higher-budget candidate that materially improves MDE, rank
  stability, or slice precision.
- `narrowed_claim`: candidate that keeps budget near the user request but narrows
  scope to a defensible claim.

### Method-Family Calculators

Calculators are deterministic functions. They do not call RAG or the LLM.

Required calculators:

- Single-rate Wilson interval width for diagnostic/smoke precision planning.
- Two-proportion conservative MDE for early planning when no paired prior exists.
- Paired-design MDE approximation using baseline rate plus conservative
  dependence/discordance assumptions.
- Empirical bootstrap power curve when historical paired task-level logs exist.
- Stratified bootstrap planning proxy for weighted task distributions.
- Leaderboard rank-stability planning proxy:
  - rank interval estimate;
  - top-k retention probability estimate;
  - pairwise win-probability resolution;
  - Kendall-tau stability target when applicable.
- Non-inferiority margin planning:
  - margin must be predeclared;
  - one-sided claim language;
  - power/MDE interpretation tied to margin.
- Slice precision diagnostics:
  - per-slice task count;
  - Wilson or bootstrap CI width;
  - undercovered primary strata;
  - diagnostic-only caveats.
- Effective sample size caveat:
  - `n_eff <= unique_tasks` by default;
  - optional design-effect adjustment only when calibrated logs exist.
- Missingness impact:
  - expected missingness rate;
  - missingness policy;
  - status downgrade if missingness can invalidate the claim.
- Multiplicity planning:
  - primary confirmatory family;
  - Holm-style plan for small confirmatory families;
  - BH/FDR or descriptive-only framing for diagnostics.

### Sensitivity Runner

Every recommended design must include sensitivity diagnostics for the assumptions
that most affect interpretation.

Required sensitivity branches:

- baseline pass rate low / medium / high;
- paired correlation or discordance low / medium / high when pairwise;
- floor/ceiling risk;
- public-log prior vs no-prior fallback;
- no cluster penalty vs conservative cluster penalty;
- requested effect target vs larger detectable effect;
- full claim vs narrowed claim;
- confirmatory slice count reduced vs unchanged.

The output should make weak spots explicit. Example: "At 120 tasks this is a
smoke/large-effect design; at 240 tasks the same claim becomes medium-effect
defensible under the current assumptions."

### Candidate Scorer

The scorer ranks candidates by usefulness under constraints.

Scoring goals, in order:

1. Preserve the user's primary question when statistically defensible.
2. Avoid unsupported claims.
3. Prefer the cheapest design that supports the allowed claim.
4. Prefer more unique tasks over repeated attempts for model-selection power.
5. Preserve declared primary strata.
6. Keep confirmatory families small enough for the budget.
7. Prefer explicit narrowed claims over vague broad warnings.
8. Surface a stronger alternative when the recommended design is still weak.

The scorer must output reasons for rejected candidates, not just the winner.

### Repair Generator

Every warning/refusal must include concrete repairs.

Repair action categories:

- increase unique task budget;
- accept a larger detectable effect;
- reduce confirmatory slice count;
- move slices to exploratory diagnostics;
- narrow claim boundary;
- switch primary metric;
- add attempts only for repeated-attempt reliability claims;
- add paired-task contract;
- add non-inferiority margin;
- add sandbox/state-reset policy;
- select supported server scope;
- use public logs only as empirical priors;
- downgrade to smoke test.

Repairs must be executable by the validate/edit UI. Avoid vague suggestions such
as "collect more data" without a target field and value.

## Planning Algorithms By Mode

### Pairwise Model Selection

Goal: decide whether model A is better than model B on a declared task
distribution.

Engine behavior:

- Require exactly two candidate models.
- Use paired task-level outcomes as the planned estimand.
- Recommend paired bootstrap as the default post-run criterion.
- Use approximate randomization as a fallback/complement when p-value style
  evidence is needed.
- Use conservative two-proportion planning only when no paired prior exists, and
  label it `planning_heuristic`.
- Prefer unique tasks over attempts for power.
- Keep attempts separate for reliability/pass@k diagnostics.
- Emit underpowered issues when requested effect is below planned MDE.

Minimum output:

- planned paired delta in percentage points;
- planned MDE curve over unique tasks;
- assumptions about baseline rate and dependence;
- paired-data requirement;
- allowed claim scoped to task distribution;
- not-allowed universal-best claim.

### Leaderboard Ranking

Goal: rank three or more models with uncertainty.

Engine behavior:

- Require at least three models.
- Separate "rank display" from "pairwise superiority claims".
- Plan rank-stability, not just pass-rate point estimates.
- Include top-k retention and rank-interval diagnostics where available.
- Add multiplicity plan for any confirmatory pairwise claims.
- Warn when budget can only support an exploratory leaderboard.

Minimum output:

- rank-stability method;
- planned bootstrap/resampling unit;
- top-k or rank interval target;
- pairwise claim restrictions;
- multiplicity notes.

### Regression / Non-Inferiority

Goal: check that a candidate has not regressed beyond an acceptable margin.

Engine behavior:

- Require baseline model, candidate model, fixed slice, and non-inferiority
  margin.
- Use one-sided claim language.
- Refuse post-hoc margins.
- Recommend enough task budget for the margin, or downgrade to smoke/regression
  diagnostic.

Minimum output:

- margin in percentage points;
- one-sided decision rule;
- planned CI/power interpretation;
- allowed non-inferiority claim;
- not-allowed "candidate is better" claim unless separately powered.

### Diagnostic Slice

Goal: understand failure modes such as wrong-server calls, same-name tools, or
recovery failures.

Engine behavior:

- Treat diagnostic slices as exploratory by default.
- Allocate explicit task coverage to named slices.
- Add distractor/generation knobs required to make the slice real.
- Compute slice-level precision, not broad model-selection power.
- Refuse broad selection claims when only diagnostic coverage exists.

Minimum output:

- slice list with ratios and expected counts;
- per-slice precision diagnostics;
- exploratory vs confirmatory labels;
- required generator knobs;
- claim boundary.

## Engine-Owned Schema Additions

T11 already defines the base v2 schema set. T14 may add these fields or typed
subobjects if the implementation needs them:

### ParameterSearchSpace

Required fields:

- `task_budget_grid`: list of integer task budgets.
- `attempts_grid`: list of integer attempt counts.
- `effect_target_grid_pp`: list of percentage-point effects.
- `distribution_candidates`: list of task distribution objects.
- `confirmatory_slice_limit`: integer.
- `method_families`: list of method labels.
- `server_scope_options`: list of server-scope lists.

### ParameterCandidate

Required fields:

- `candidate_id`.
- `design`.
- `power_analysis`.
- `assumption_ledger`.
- `issues`.
- `score`.
- `status`.
- `rejection_reasons`.
- `repair_actions`.

### EngineDecision

Required fields:

- `schema_version`: literal `"benchmark_advisor.engine_decision.v2"`.
- `recommended_candidate_id`.
- `recommended_design`.
- `parameter_search_space`.
- `parameter_candidates`.
- `design_alternatives`.
- `power_analysis`.
- `assumption_ledger`.
- `claim_card`.
- `issues`.
- `citations`.
- `computation_trace`.

### EngineComputationTrace

Required fields:

- `engine_version`.
- `guide_version`.
- `guide_snapshot_id`.
- `random_seed`.
- `candidate_count`.
- `formula_versions`.
- `empirical_prior_sources`.
- `validator_rule_ids`.
- `selected_reason`.

These additions are optional only if their content is represented by an
equivalent typed structure with tests. They must not be replaced by untyped JSON
blobs in v2 frontend or backend schemas.

## UI Expectations

The v2 UI should make the engine visible as the central product feature.

Required surfaces:

- Claim card:
  - allowed claims;
  - not-allowed claims;
  - claim boundary;
  - confirmatory vs exploratory labels.
- Power/budget workbench:
  - MDE curve;
  - CI-width curve;
  - "what budget buys you" alternatives;
  - underpowered repairs.
- Method card:
  - selected method family;
  - why it matches the question;
  - paired/unpaired or rank-stability assumptions;
  - guide rule ids and citations.
- Assumptions panel:
  - baseline rate;
  - dependence/repeated attempts;
  - missingness;
  - multiplicity;
  - floor/ceiling;
  - empirical-prior caveats.
- Alternatives panel:
  - cheaper/smoke;
  - recommended;
  - stronger;
  - narrowed claim.
- Repair buttons:
  - apply specific field edits;
  - call `/api/advisor/v2/validate`;
  - show all resulting issues.
- Citations:
  - local source ids only;
  - no live web authority;
  - clear provenance label.

The UI must not present citation or optional RAG text as the authority for
approval. It should show rule-gated status and cite the deterministic failed
criteria.

## Implementation Phases

### Phase 1: Engine Contract And Deterministic Fallback

- Add engine module and typed output.
- Implement finite candidate search for pairwise, diagnostic, leaderboard, and
  regression modes.
- Use deterministic formulas from the guide.
- Add computation trace.
- Return recommended/cheap/stronger/narrowed alternatives.
- No LLM dependency required.

### Phase 2: Guide Citations And Optional Source Pack

- Attach guide snippets/source keys by rule id and method family.
- Use guide citations in explanations and tooltips.
- Prove snippet text cannot change validator status by itself.
- Add a larger approved source pack only if it improves explanation quality; do
  not make it a runtime dependency.

### Phase 3: Empirical Priors

- Add optional public-log calibration.
- Label all calibrated curves `empirical_prior`.
- Include no-prior fallback and private-transfer caveat.

### Phase 4: Post-Run Bridge

- Reuse method labels and assumptions for T15 `StatisticalReport`.
- Ensure planned claim boundaries become report claim boundaries.
- Preserve outcome tensor missingness and multiplicity policy.

## Test Requirements

Unit tests:

- deterministic output for fixed request and seed;
- candidate grid is finite and contains required alternatives;
- MDE decreases with more unique tasks;
- CI width decreases with more unique tasks;
- attempts do not multiply iid sample size;
- paired vs unpaired assumptions produce distinct issue sets;
- pairwise default method is paired when same tasks are planned;
- leaderboard includes rank-stability diagnostics;
- regression refuses missing margin;
- diagnostic-only design refuses broad selection claim;
- multiplicity policy appears when multiple confirmatory slices exist;
- missingness policy appears in every plan;
- all issues are returned, not only the first;
- unknown guide rule ids fail validation;
- guide citations are local and mapped to known rule ids/source keys;
- validator status is unchanged when snippet prose changes.

Golden fixtures:

- pairwise approved recommended design;
- pairwise underpowered warning with budget repairs;
- pairwise refused small-budget design;
- leaderboard exploratory warning;
- leaderboard stronger alternative with rank-stability target;
- regression missing-margin refusal;
- regression non-inferiority approved plan;
- diagnostic same-name slice with generator pressure;
- diagnostic overclaim refusal;
- edited-design downgrade after validate;
- guide-cited plan with deterministic status unchanged;
- no-prior fallback vs empirical-prior calibrated plan.

Integration smoke:

```text
intent
  -> /api/advisor/v2/design
  -> StatisticalPlan with EngineDecision-derived recommendation
  -> edit budget/distribution
  -> /api/advisor/v2/validate returns all issues
  -> guarded export is available only for approved/warning state
```

## Non-Goals

- The engine must not launch generation or evaluation.
- The engine must not replace deterministic validators.
- The engine must not make final post-run claims from planning assumptions.
- The engine must not use live web retrieval at runtime.
- The engine must not require vector retrieval, an LLM, or a stat-agent for MVP
  operation.
- The engine must not change benchmark scoring.
- The engine must not hide uncertainty to make a plan look approved.

## Handoff Guidance For Agents

Agents implementing T14 should start from this document, then check:

- `STATISTICAL_GUIDE.md` for rule ids and formula notes;
- `INTERFACES.md` for v2 schema types and validator thresholds;
- `T13-dual-engine-planner.md` for guide-first planner composition;
- `T15-post-run-statistical-report.md` for report compatibility;
- `T16-statistical-advisor-ui-v2.md` for frontend display needs.

The first acceptable implementation should be deterministic-only. Optional
RAG/stat-agent integration is secondary; the engine must be valuable with only
`STATISTICAL_GUIDE.md` and deterministic calculators.
