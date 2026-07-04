# BA5.4 Current Contract Snapshot

This file is a repo-grounded snapshot for deep-research agents working on BA5.4.
Research recommendations must not silently conflict with these current BA5.1 to
BA5.3 contracts. If a recommendation intentionally changes one of these values,
state the conflict and explain the migration.

Snapshot source files:

- `benchmark_advisor/schema.py`
- `benchmark_advisor/v2_schema.py`
- `benchmark_advisor/v2_engine.py`
- `benchmark_advisor/stats.py`
- `benchmark_advisor/validator.py`
- `docs_benchmark_advisor/planning/INTERFACES.md`

## Shared Registries

V2 imports these shared types from the v1 schema layer.

```python
Status = Literal["approved", "warning", "refused", "needs_clarification"]
Mode = Literal["pairwise", "leaderboard", "regression", "diagnostic"]
ClaimScope = Literal[
    "confirmatory_model_selection",
    "leaderboard_ranking",
    "regression_non_inferiority",
    "diagnostic_slice",
    "smoke_test_only",
]
PrimaryMetric = Literal[
    "trace_effect_pass_rate",
    "pass_at_3",
    "pairwise_delta_pp",
    "non_inferiority_margin_pp",
    "rank_stability",
    "slice_failure_rate",
]
TestFamily = Literal[
    "paired_bootstrap",
    "two_proportion_wilson",
    "non_inferiority_margin",
    "rank_stability_bootstrap",
    "diagnostic_descriptive",
]
CIMethod = Literal["wilson_score", "paired_bootstrap", "stratified_bootstrap"]
MDEMethod = Literal["normal_approx_two_proportion", "paired_bootstrap_heuristic"]
RankStabilityMethod = Literal["bootstrap_tasks_within_strata", "not_applicable"]
Severity = Literal["info", "warning", "critical"]
```

Current v1 warning codes:

```python
WarningCode = Literal[
    "underpowered_design",
    "too_few_repeats",
    "task_mix_bias",
    "insufficient_cross_server_coverage",
    "insufficient_long_chain_coverage",
    "insufficient_recovery_coverage",
    "too_many_secondary_slices",
    "public_logs_are_prior_only",
    "smoke_test_only",
]
```

Current v1 refusal codes:

```python
RefusalCode = Literal[
    "cannot_support_claim",
    "invalid_distribution",
    "insufficient_budget",
    "unsupported_final_answer_claim",
    "generation_launch_forbidden",
    "missing_required_design_field",
]
```

Current v2 engine adds issue codes as free-form non-empty strings inside
`StatisticalIssue.code`. In BA5.3, the extra engine-specific codes are:

- `unsupported_candidate_model_count`
- `missing_non_inferiority_margin`
- `needs_clarification`

These are not yet part of the v1 `WarningCode` / `RefusalCode` literals.

## Core Design Shapes

`AdvisorDesign` is still the concrete design object inside v2 `StatisticalPlan`
and `EngineDecision`.

```python
class AdvisorDesign:
    evaluation_question: NonEmptyStr
    mode: Mode
    claim_scope: ClaimScope
    candidate_models: list[NonEmptyStr]
    task_budget: int >= 1
    attempts_per_task: int >= 1
    target_detectable_effect_pp: float in (0, 100] | None
    estimand: NonEmptyStr
    hypotheses: HypothesisPlan
    criteria: list[Criterion] min_length=1
    task_distribution: TaskDistribution
    analysis_plan: AnalysisPlan
    claim_boundary: NonEmptyStr
    intent_evidence: list[NonEmptyStr]
    statistical_guide_version: Literal["statistical_guide.v1"]
```

Task distribution:

```python
class TaskDistribution:
    short_chain: Ratio
    medium_chain: Ratio
    long_chain: Ratio
    cross_server_ratio: Ratio
    recovery_required_ratio: Ratio
    prerequisite_strict_ratio: Ratio
    stateful_write_ratio: Ratio
    categories: list[NonEmptyStr] min_length=1
    distractors: DistractorPolicy
    diagnostic_slices: list[DiagnosticSlice]

class DistractorPolicy:
    same_name_fraction: Ratio
    near_miss_fraction: Ratio
    cross_domain_fraction: Ratio
    random_fraction: Ratio

class DiagnosticSlice:
    slice_id: NonEmptyStr
    label: NonEmptyStr
    ratio: Ratio
    confirmatory: bool
```

Analysis plan and criterion:

```python
class AnalysisPlan:
    ci_method: CIMethod
    mde_method: MDEMethod
    rank_stability_method: RankStabilityMethod
    pairwise_test: TestFamily | None
    alpha: UnitOpen
    beta: UnitOpen
    planning_assumptions: list[NonEmptyStr] min_length=1
    heuristic_label: Literal["planning_heuristic"]

class Criterion:
    criterion_id: NonEmptyStr
    purpose: NonEmptyStr
    estimand: NonEmptyStr
    null_hypothesis: NonEmptyStr
    alternative_hypothesis: NonEmptyStr
    primary_metric: PrimaryMetric
    test_family: TestFamily
    alpha: UnitOpen
    beta_or_target_power: UnitOpen
    minimum_detectable_effect_pp: PercentPoints | None
    required_data: list[NonEmptyStr]
    decision_rule: NonEmptyStr
    allowed_claim: NonEmptyStr
    failure_modes: list[NonEmptyStr]
    confirmatory: bool
    guide_references: list[StatisticalGuideReference] min_length=1
    selection_rationale: NonEmptyStr
```

## Exact V2 Schema Contracts

All v2 schemas use `extra="forbid"`.

Version constants:

```python
V2_SCHEMA_VERSION = "benchmark_advisor.v2"
STATISTICAL_PLAN_SCHEMA_VERSION = "benchmark_advisor.statistical_plan.v2"
OUTCOME_TENSOR_SCHEMA_VERSION = "benchmark_advisor.outcome_tensor.v2"
STATISTICAL_REPORT_SCHEMA_VERSION = "benchmark_advisor.report.v2"
LAUNCH_SCHEMA_VERSION = "benchmark_advisor.launch.v2"
LAUNCH_JOB_SCHEMA_VERSION = "benchmark_advisor.launch_job.v2"
LaunchStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
```

Citation and issue cards:

```python
class LocalStatisticalCitation:
    source_id: NonEmptyStr
    title: NonEmptyStr
    section: NonEmptyStr
    evidence_status: NonEmptyStr
    source_keys: list[NonEmptyStr] = []
    snippet: NonEmptyStr
    guide_references: list[StatisticalGuideReference] = []

class StatisticalIssue:
    severity: Severity
    code: NonEmptyStr
    message: NonEmptyStr
    failed_field: str | None
    failed_criterion_id: str | None
    statistical_reason: NonEmptyStr
    repair_options: list[NonEmptyStr] min_length=1
    guide_references: list[StatisticalGuideReference] = []
```

Planning objects:

```python
class AssumptionLedger:
    baseline_rate: Ratio | None
    paired_design: bool
    independence_assumption: NonEmptyStr
    repeated_attempts_policy: NonEmptyStr
    missingness_policy: NonEmptyStr
    multiplicity_policy: NonEmptyStr
    sensitivity_notes: list[str] = []
    guide_references: list[StatisticalGuideReference] = []

class PowerCurvePoint:
    task_budget: int >= 1
    mde_pp: PercentPoints
    ci_width_pp: PercentPoints

class BudgetAlternative:
    task_budget: int >= 1
    detectable_effect_pp: PercentPoints
    claim_status: Status

class PowerAnalysis:
    alpha: UnitOpen
    target_power: UnitOpen
    planned_mde_pp: PercentPoints
    ci_width_pp: PercentPoints
    method: NonEmptyStr
    power_curve: list[PowerCurvePoint] = []
    budget_alternatives: list[BudgetAlternative] = []
    assumptions: AssumptionLedger

class DesignAlternative:
    alternative_id: NonEmptyStr
    label: NonEmptyStr
    task_budget: int >= 1
    attempts_per_task: int >= 1
    target_detectable_effect_pp: PercentPoints | None
    status: Status
    tradeoff: NonEmptyStr
    repair_actions: list[str] = []

class ClaimCard:
    allowed_claims: list[NonEmptyStr] min_length=1
    not_allowed_claims: list[str] = []
    plain_language_summary: NonEmptyStr
```

Engine objects:

```python
class ParameterSearchSpace:
    task_budget_grid: list[int >= 1] min_length=1
    attempts_grid: list[int >= 1] min_length=1
    effect_target_grid_pp: list[PercentPoints] min_length=1
    distribution_candidates: list[TaskDistribution] min_length=1
    confirmatory_slice_limit: int >= 1
    method_families: list[NonEmptyStr] min_length=1
    server_scope_options: list[list[NonEmptyStr]] = []

class ParameterCandidate:
    candidate_id: NonEmptyStr
    design: AdvisorDesign
    power_analysis: PowerAnalysis
    assumption_ledger: AssumptionLedger
    issues: list[StatisticalIssue] = []
    score: float
    status: Status
    rejection_reasons: list[str] = []
    repair_actions: list[str] = []

class EngineComputationTrace:
    engine_version: NonEmptyStr
    guide_version: Literal["statistical_guide.v1"]
    guide_snapshot_id: str | None
    random_seed: int | None
    candidate_count: int >= 1
    formula_versions: list[NonEmptyStr] min_length=1
    empirical_prior_sources: list[str] = []
    validator_rule_ids: list[str] = []
    selected_reason: NonEmptyStr

class EngineDecision:
    schema_version: Literal["benchmark_advisor.engine_decision.v2"]
    recommended_candidate_id: NonEmptyStr
    recommended_design: AdvisorDesign
    parameter_search_space: ParameterSearchSpace
    parameter_candidates: list[ParameterCandidate] min_length=1
    design_alternatives: list[DesignAlternative] = []
    power_analysis: PowerAnalysis
    assumption_ledger: AssumptionLedger
    claim_card: ClaimCard
    issues: list[StatisticalIssue] = []
    citations: list[LocalStatisticalCitation] = []
    computation_trace: EngineComputationTrace

class StatisticalPlan:
    schema_version: Literal["benchmark_advisor.statistical_plan.v2"]
    design: AdvisorDesign
    engine_decision: EngineDecision | None = None
    power_analysis: PowerAnalysis
    design_alternatives: list[DesignAlternative] = []
    assumption_ledger: AssumptionLedger
    issues: list[StatisticalIssue] = []
    citations: list[LocalStatisticalCitation] = []
    claim_card: ClaimCard
```

Requests and responses:

```python
class AdvisorV2DesignRequest:
    schema_version: Literal["benchmark_advisor.v2"]
    intent: NonEmptyStr
    mode: Mode
    task_budget: int >= 1
    attempts_per_task: int >= 1
    candidate_models: list[NonEmptyStr] = []
    target_detectable_effect_pp: PercentPoints | None = None
    alpha: UnitOpen = 0.05
    beta: UnitOpen = 0.2
    deployment_context: DeploymentContext | None = None
    server_scope: list[NonEmptyStr] = []
    user_overrides: dict[str, Any] = {}
    retrieval_mode: Literal["local_only"] = "local_only"

class AdvisorV2DesignResponse:
    schema_version: Literal["benchmark_advisor.v2"]
    status: Status
    statistical_plan: StatisticalPlan | None
    issues: list[StatisticalIssue] = []
    export_config: ExportConfig | None
    launchable: bool

class AdvisorV2ValidationRequest:
    schema_version: Literal["benchmark_advisor.v2"]
    statistical_plan: StatisticalPlan
    original_request: AdvisorV2DesignRequest | None = None
    edited_fields: list[str] = []
```

Report and launch schemas already exist, but BA5.4 must not implement post-run
reporting or launch behavior.

## Exact `stats.py` Helpers

Constants:

```python
HEURISTIC_LABEL = "planning_heuristic"
COVERAGE_THRESHOLDS = {
    "cross_server": (0.25, 0.10),
    "long_chain": (0.30, 0.15),
    "recovery": (0.10, 0.05),
}
```

Functions:

```python
wilson_ci(n: int, p: float = 0.5, z: float = 1.96) -> tuple[float, float]
ci_width_pp(n: int, p: float = 0.5, z: float = 1.96) -> float
planned_mde_pp(n_per_group: int, baseline: float = 0.5) -> float
required_tasks_for_mde(mde_pp: float, baseline: float = 0.5) -> int
budget_mde_curve(budgets: list[int], baseline: float = 0.5, groups: int = 2) -> list[tuple[int, float]]
coverage_status(planned: float, dimension: str) -> str
coverage_diagnostic(dimension: str, planned: float) -> CoverageDiagnostic
plan_statistics(task_budget, attempts_per_task, baseline_rate=0.5, coverage_claims=None) -> PlanningStats
```

Current formula behavior:

- `wilson_ci` uses `dmcp.curves.proportion_ci`.
- `ci_width_pp` returns full Wilson interval width in percentage points.
- `planned_mde_pp` uses a two-proportion normal approximation:
  `delta = (z_alpha_05 + z_power_80) * sqrt(2 * p * (1 - p) / n)`.
- `planned_mde_pp` defaults to `baseline=0.5` and caps at `100.0`.
- `required_tasks_for_mde` reuses `dmcp.ablation.power_n`.
- `budget_mde_curve` currently calls `planned_mde_pp(b // groups, baseline)`.
- `plan_statistics` currently calls `planned_mde_pp(task_budget, baseline_rate)`;
  this differs from `budget_mde_curve`'s per-group split and should be treated
  carefully by BA5.4 research.

Dataclasses:

```python
@dataclass(frozen=True)
class CoverageDiagnostic:
    dimension: str
    planned: float
    approved_floor: float
    warning_floor: float
    status: str
    label: str = HEURISTIC_LABEL

@dataclass(frozen=True)
class PlanningStats:
    task_budget: int
    attempts_per_task: int
    baseline_rate: float
    planned_mde_pp: float
    ci_width_pp: float
    coverage: list[CoverageDiagnostic] = []
    label: str = HEURISTIC_LABEL
```

## Current BA5.1-BA5.3 Thresholds

Budget bands:

| Mode | Approved | Warning | Refused |
|---|---:|---:|---:|
| `pairwise` | `task_budget >= 100` | `60..99` | `< 60` |
| `leaderboard` | `task_budget >= 150` | `80..149` | `< 80` |
| `regression` | `task_budget >= 60` | `30..59` | `< 30` |
| `diagnostic` | `task_budget >= 40` | `20..39` | `< 20` |

Target effect threshold:

- planned MDE is `planned_mde_pp(design.task_budget)`.
- If `target_detectable_effect_pp < 0.75 * planned_mde`, validator refuses with
  `insufficient_budget`.
- If `target_detectable_effect_pp < planned_mde`, validator warns with
  `underpowered_design`.

Coverage thresholds:

| Marker in `task_distribution.categories` | Attribute | Approved | Warning | Refused |
|---|---|---:|---:|---:|
| `cross_server` | `cross_server_ratio` | `>= 0.25` | `0.10..0.249` | `< 0.10` |
| `long_chain` | `long_chain` | `>= 0.30` | `0.15..0.299` | `< 0.15` |
| `recovery` | `recovery_required_ratio` | `>= 0.10` | `0.05..0.099` | `< 0.05` |

Distractor-pressure thresholds:

| Marker in `task_distribution.categories` | Attribute | Approved | Warning | Refused |
|---|---|---:|---:|---:|
| `same_name` | `distractors.same_name_fraction` | `>= 0.25` | `0.10..0.249` | `< 0.10` |
| `near_miss` | `distractors.near_miss_fraction` | `>= 0.25` | `0.10..0.249` | `< 0.10` |
| `hard_negative` | `distractors.near_miss_fraction` | `>= 0.25` | `0.10..0.249` | `< 0.10` |

Slice thresholds:

- `max_confirmatory_slices = max(1, task_budget // 40)`.
- `max_diagnostic_slices = max(1, task_budget // 25)`.
- If confirmatory scope and `len(confirmatory_slices) > 2 * max_confirmatory_slices`,
  validator refuses with `cannot_support_claim`.
- Else if `len(confirmatory_slices) > max_confirmatory_slices`, validator warns
  with `too_many_secondary_slices`.
- If `len(diagnostic_slices) > max_diagnostic_slices`, validator warns with
  `too_many_secondary_slices`.

Pass@3 attempts:

- If any criterion uses `primary_metric == "pass_at_3"`:
  - `attempts_per_task == 2` warns with `too_few_repeats`.
  - `attempts_per_task < 2` refuses with `cannot_support_claim` for
    confirmatory scopes.
  - `attempts_per_task < 2` warns with `too_few_repeats` for non-confirmatory
    scopes.

Structural refusals:

- Chain fractions must sum to `1.0` within tolerance `0.001`.
- Distractor fractions must sum to at most `1.0` within tolerance `0.001`.
- `stateful_write_ratio > 0` requires `sandbox_required is True`.
- Unknown `statistical_guide.v1` rule ids refuse with
  `missing_required_design_field`.
- Diagnostic designs cannot use confirmatory model-selection or leaderboard
  claim scopes.
- Comparison modes with no candidate models return clarification.

Current v2 engine method constraints:

- `pairwise` with candidate count not equal to `2` adds critical issue
  `unsupported_candidate_model_count`.
- `leaderboard` with fewer than `3` candidates adds critical issue
  `unsupported_candidate_model_count`.
- `regression` with `target_detectable_effect_pp is None` adds critical issue
  `missing_non_inferiority_margin`.
- Any critical `StatisticalIssue` makes v2 status `refused`.
- Any warning `StatisticalIssue` makes v2 status `warning`.

## Current `v2_engine.py` Search And Scoring

Constants:

```python
ENGINE_VERSION = "benchmark_advisor.statistical_engine.v0"
ENGINE_DECISION_SCHEMA_VERSION = "benchmark_advisor.engine_decision.v2"
_PAIRWISE_REPAIR = "Use exactly two candidate models for a pairwise comparison."
_LEADERBOARD_REPAIR = "Use at least three candidate models for leaderboard rank-stability planning."
_REGRESSION_REPAIR = "Set target_detectable_effect_pp as the predeclared non-inferiority margin."
```

Budget grid:

```python
approved_floor, warning_floor = BUDGET_BANDS[request.mode]
values = {
    request.task_budget,
    warning_floor,
    approved_floor,
    max(approved_floor, request.task_budget * 2),
    max(approved_floor + 20, int(round(approved_floor * 1.5))),
}
if request.target_detectable_effect_pp is not None:
    values.add(required_tasks_for_mde(request.target_detectable_effect_pp))
return sorted(max(1, min(5000, int(v))) for v in values)
```

Attempts grid:

```python
values = {request.attempts_per_task}
if "pass@3" in request.intent.lower() or "pass at 3" in request.intent.lower():
    values.add(3)
```

Effect grid:

```python
values = {round(planned_mde_pp(b), 3) for b in budgets}
if request.target_detectable_effect_pp is not None:
    values.add(round(request.target_detectable_effect_pp, 3))
```

Current assumptions:

```python
baseline_rate = 0.5
paired_design = mode == "pairwise"
independence_assumption = (
    "unique tasks are the iid planning unit; same-task model outputs are paired"
)
repeated_attempts_policy = (
    "attempts can support reliability metrics but do not multiply unique-task power"
)
missingness_policy = "explicit_null_with_reason before post-run reporting"
multiplicity_policy = (
    "single primary criterion; diagnostic slices remain exploratory unless predeclared"
)
sensitivity_notes = [
    "Inspect low/medium/high baseline-rate sensitivity before launch.",
    "Treat public logs as priors only, not private-deployment evidence.",
]
```

Current power analysis:

- Curve budgets are `{task_budget // 2, task_budget, round(task_budget * 1.5),
  task_budget * 2}` after minimum guards.
- `mde_pp = round(planned_mde_pp(b), 3)`.
- `ci_width_pp = round(ci_width_pp(b), 3)`.
- `planned_mde_pp = round(planned_mde_pp(design.task_budget), 3)`.
- `method = design.analysis_plan.mde_method`.

Current scoring:

```python
base = {
    "approved": 3000.0,
    "warning": 2000.0,
    "needs_clarification": 500.0,
    "refused": 0.0,
}[status]
score = base - task_budget
```

Selection picks max by:

```python
(candidate.score, -candidate.design.task_budget, candidate.candidate_id)
```

Current alternatives:

- `alt.budget_minimum`
- `alt.recommended`
- `alt.stronger`
- `alt.narrowed_claim`

Current claim cards:

- Refused:
  - allowed: `"No confirmatory claim until the critical issues are repaired."`
  - not allowed: `"model selection"`, `"universal model ranking"`,
    `"private-deployment guarantee"`
- Non-refused by mode:
  - pairwise: `"Scoped pairwise difference on the planned task distribution."`
  - leaderboard: `"Scoped leaderboard display with rank-stability caveats."`
  - regression: `"Scoped non-inferiority claim within the predeclared margin."`
  - diagnostic: `"Exploratory diagnostic slice description."`
  - not allowed: `"universal best-model claim"`,
    `"unseen private-deployment guarantee"`

## What `task_budget` Means Today

`task_budget` is the number of planned unique benchmark tasks / TaskSpecs, not
the number of model calls and not `tasks * attempts_per_task`.

Current contract clues:

- `INTERFACES.md` defines `attempts_per_task` separately as "planned candidate
  evaluation repeats, not generation repeats".
- `STATISTICAL_GUIDE.md` explicitly says repeated attempts, shared templates,
  shared servers, and correlated task clusters reduce independent information;
  do not treat `tasks * attempts_per_task` as iid sample size.
- `v2_engine.py` assumption text says unique tasks are the iid planning unit and
  attempts can support reliability metrics but do not multiply unique-task
  power.
- `ExportConfig.tasks` receives `AdvisorDesign.task_budget`.
- `PowerAnalysis.power_curve[*].task_budget` uses unique task counts.

Implications for BA5.4 research:

- Any power/MDE/CI-width recommendation that uses iid sample size must use
  unique tasks, or an explicitly smaller/equal effective sample size.
- Repeated attempts may support reliability/pass@k diagnostics, but must not
  repair underpowered model-selection claims by multiplying task count.
- Candidate budget grids should be expressed in unique tasks.
- If a source discusses "sample size", map it to unique task units unless the
  source explicitly handles repeated measures or clustered designs.
- If a formula requires per-group sample size, state whether current
  `task_budget` should be interpreted as paired shared tasks, per-arm tasks, or
  total unique tasks. This is an open BA5.4 clarification point because current
  code sometimes uses `planned_mde_pp(task_budget)` while
  `budget_mde_curve(..., groups=2)` uses `planned_mde_pp(task_budget // 2)`.

## What Research Agents Should Avoid

Do not propose:

- new enum values without saying which schema must change;
- warning/refusal code names without checking current `WarningCode`,
  `RefusalCode`, and v2 free-form `StatisticalIssue.code`;
- task-budget defaults that conflict with current `BUDGET_BANDS` unless the
  answer explicitly recommends changing those bands;
- formulas that use `task_budget * attempts_per_task` as iid N;
- live web/RAG runtime dependencies;
- post-run report requirements as BA5.4 acceptance criteria.

