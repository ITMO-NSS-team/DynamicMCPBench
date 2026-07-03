# Benchmark Advisor Interfaces

Status: frozen v1 contracts plus additive v2 planning contracts. Changes to v1
after T00 require an integration decision and updates to affected task packets.
V2 contracts are the next implementation target and must not break v1 routes.

These contracts are normative. Examples are illustrative only; implementation
agents must build the Pydantic models from the field lists, enum registries,
state matrix, and validator thresholds below.

Planner choices must be grounded in
`docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`. The LLM may propose a
design, but every criterion and every major user-visible parameter must carry
structured guide references and a short rationale suitable for UI hover text.

## Migration Note

The existing prototype surface, if present, is legacy: `POST /api/advisor`,
`schema_version: "0.1.0"`, `BenchmarkAdvisorRequest`, and
`BenchmarkAdvisorOutput` are not the v1 contract. T05 may keep a compatibility
adapter, but v1 completion requires `POST /api/advisor/design`,
`POST /api/advisor/validate`, `schema_version: "benchmark_advisor.v1"`, and the
`AdvisorResponse` shape below. Tests must assert the v1 routes directly.

## V2 Additive Contract Note

V2 makes the advisor a full statistical advisor rather than only a pre-run
heuristic gate. V2 is additive:

- v1 route names, schema versions, enum values, and response-state behavior stay
  compatible;
- v2 routes live under `/api/advisor/v2/*`;
- v2 may add fields and richer issue/report objects, but it must not weaken v1
  refusal, clarification, no-export, and no-auto-launch invariants;
- the MVP is guide-first: `STATISTICAL_GUIDE.md` rule ids, source keys, and
  snippets are enough for method selection and explanations. A RAG/stat-agent
  proposer may be added later, but deterministic rules decide approval, warning,
  refusal, exportability, launchability, and report claim boundaries.
- the Statistical Engine runs before the final v2 design is returned and owns
  parameter search/scoring for task budget, attempts, target effect,
  distribution, confirmatory slices, missingness policy, and multiplicity
  policy.

## Shared Type Rules

- Python schemas use Pydantic v2 and `ConfigDict(extra="forbid")`.
- JSON field names use `snake_case`.
- All public responses include `schema_version`.
- Stage-1 metrics are planning heuristics unless explicitly marked as computed
  from task-level outcomes.
- Ratio fields are floats in `[0, 1]`.
- Percentage-point fields are floats in `(0, 100]`.
- Count fields are integers `>= 1` unless stated otherwise.
- Nullable fields must be declared as nullable in the Pydantic schema; absent and
  `null` are not interchangeable.
- `guide_references` always refer to `statistical_guide.v1` rule ids.
- Hover rationale text must be short enough for UI display and must not introduce
  claims stronger than `claim_boundary`.

## Enum Registries

These string registries are part of the contract. New values require an
integration decision.

### `status`

- `approved`
- `warning`
- `refused`
- `needs_clarification`

### `mode`

- `pairwise`
- `leaderboard`
- `regression`
- `diagnostic`

### `claim_scope`

- `confirmatory_model_selection`
- `leaderboard_ranking`
- `regression_non_inferiority`
- `diagnostic_slice`
- `smoke_test_only`

### `primary_metric`

- `trace_effect_pass_rate`
- `pass_at_3`
- `pairwise_delta_pp`
- `non_inferiority_margin_pp`
- `rank_stability`
- `slice_failure_rate`

No final-answer metric is allowed.

### `test_family`

- `paired_bootstrap`
- `two_proportion_wilson`
- `non_inferiority_margin`
- `rank_stability_bootstrap`
- `diagnostic_descriptive`

### `ci_method`

- `wilson_score`
- `paired_bootstrap`
- `stratified_bootstrap`

### `mde_method`

- `normal_approx_two_proportion`
- `paired_bootstrap_heuristic`

### `rank_stability_method`

- `bootstrap_tasks_within_strata`
- `not_applicable`

### `warning_code`

- `underpowered_design`
- `too_few_repeats`
- `task_mix_bias`
- `insufficient_cross_server_coverage`
- `insufficient_long_chain_coverage`
- `insufficient_recovery_coverage`
- `too_many_secondary_slices`
- `public_logs_are_prior_only`
- `smoke_test_only`

### `refusal_code`

- `cannot_support_claim`
- `invalid_distribution`
- `insufficient_budget`
- `unsupported_final_answer_claim`
- `generation_launch_forbidden`
- `missing_required_design_field`

### `validator_status`

- `approved`
- `warning`
- `refused`
- `needs_clarification`

### `rationale_role`

- `intent_mapping`
- `metric_choice`
- `criterion_choice`
- `distribution_choice`
- `budget_power`
- `claim_boundary`
- `ui_explanation`

## Response State Matrix

| status | design | warnings | refusal | clarification | export_config |
|---|---|---|---|---|---|
| `approved` | non-null | zero or more `info` only | null | null | non-null |
| `warning` | non-null | at least one `warning` or `critical` | null | null | non-null |
| `refused` | non-null unless schema parsing failed | zero or more | non-null | null | null |
| `needs_clarification` | null or partial design | zero or more | null | non-null | null |

Refused and clarification responses must not contain an exportable launch action
or generation config. Warning responses may be exported, but warnings must be
preserved inside the export.

## Validator Thresholds

The validator is deterministic. It checks structured objects only and must not
read raw natural language except through explicit design fields such as
`intent_evidence`.

Minimum v1 thresholds:

| check | approved | warning | refused |
|---|---:|---:|---:|
| pairwise `task_budget` | `>= 100` | `60..99` | `< 60` |
| leaderboard `task_budget` | `>= 150` | `80..149` | `< 80` |
| regression `task_budget` | `>= 60` | `30..59` | `< 30` |
| diagnostic `task_budget` | `>= 40` | `20..39` | `< 20` |
| attempts for `pass_at_3` claims | `>= 3` | `2` | `1` for confirmatory claims |
| target detectable effect | `>= planned_mde_pp` | within `25%` below planned MDE | more than `25%` below planned MDE |
| cross-server coverage when claimed | `>= 0.25` | `0.10..0.249` | `< 0.10` |
| long-chain coverage when claimed | `>= 0.30` | `0.15..0.299` | `< 0.15` |
| recovery coverage when claimed | `>= 0.10` | `0.05..0.099` | `< 0.05` |
| same-name / near-miss / hard-negative distractor pressure when claimed | `>= 0.25` | `0.10..0.249` | `< 0.10` |

For `same_name`, the distractor-pressure check uses `same_name_fraction`.
For `near_miss` and `hard_negative`, it uses `near_miss_fraction`, because
hard-negative tool pressure is represented by near-miss/confusing alternative
tools in the v1 export knobs.

Secondary slice limit:

- `max_confirmatory_slices = max(1, floor(task_budget / 40))`
- `max_diagnostic_slices = max(1, floor(task_budget / 25))`
- Exceeding the applicable limit is a warning.
- Exceeding twice the applicable limit is a refusal for confirmatory claims.

Distribution checks:

- `short_chain + medium_chain + long_chain` must equal `1.0` within tolerance
  `0.001`.
- `same_name_fraction + near_miss_fraction` must be `<= 1.0`.
- `stateful_write_ratio > 0` is allowed only when the export explicitly marks
  `sandbox_required: true`.

## Shared Types

### StatisticalGuideReference

Required fields:

- `guide_version`: literal `"statistical_guide.v1"`.
- `rule_id`: non-empty string matching a rule id in `STATISTICAL_GUIDE.md`.
- `section`: non-empty guide section name, e.g. `"G5 - Criterion Selection"`.
- `role`: one `rationale_role` enum value.

The validator may warn or refuse if required rule references are absent or if a
rule id is unknown.

### AdvisorRequest

Required fields:

- `schema_version`: literal `"benchmark_advisor.v1"`.
- `intent`: non-empty string.
- `mode`: one `mode` enum value.
- `task_budget`: integer `>= 1`.
- `attempts_per_task`: integer `>= 1`.

Optional fields:

- `candidate_models`: list of non-empty strings. Required and non-empty for
  `pairwise`, `leaderboard`, and `regression`; optional for `diagnostic`.
- `target_detectable_effect_pp`: nullable float in `(0, 100]`.
- `alpha`: float in `(0, 1)`, default `0.05`.
- `beta`: float in `(0, 1)`, default `0.2`.
- `deployment_context`: nullable object with deployment notes, private-server
  constraints, and unavailable servers. These fields are advisory only.
- `user_overrides`: object containing only fields that also exist on
  `TaskDistribution`, `AnalysisPlan`, or `ExportGenerationKnobs`.

Example:

```json
{
  "schema_version": "benchmark_advisor.v1",
  "intent": "Compare two local agents on long finance workflows.",
  "mode": "pairwise",
  "candidate_models": ["qwen3.7-max", "glm-5.1"],
  "task_budget": 120,
  "attempts_per_task": 3,
  "target_detectable_effect_pp": 5.0,
  "alpha": 0.05,
  "beta": 0.2,
  "deployment_context": null,
  "user_overrides": {}
}
```

### AdvisorValidationRequest

`POST /api/advisor/validate` uses this wrapper so edited designs carry enough
metadata for deterministic validation.

Required fields:

- `schema_version`: literal `"benchmark_advisor.v1"`.
- `design`: `AdvisorDesign`.

Optional fields:

- `original_request`: nullable `AdvisorRequest`.
- `edited_fields`: list of field paths edited by the user, e.g.
  `["task_budget", "task_distribution.cross_server_ratio"]`.

### AdvisorDesign

Required fields:

- `evaluation_question`: non-empty string.
- `mode`: one `mode` enum value.
- `claim_scope`: one `claim_scope` enum value.
- `candidate_models`: list of non-empty strings. May be empty only for
  `diagnostic` or `smoke_test_only` designs.
- `task_budget`: integer `>= 1`.
- `attempts_per_task`: integer `>= 1`.
- `target_detectable_effect_pp`: nullable percentage-point float.
- `estimand`: non-empty string.
- `hypotheses`: `HypothesisPlan`.
- `criteria`: non-empty list of `Criterion`.
- `task_distribution`: `TaskDistribution`.
- `analysis_plan`: `AnalysisPlan`.
- `claim_boundary`: non-empty string.
- `intent_evidence`: list of non-empty strings. Empty evidence is allowed only
  when `status` will be `needs_clarification`.
- `statistical_guide_version`: literal `"statistical_guide.v1"`.

### HypothesisPlan

Required fields:

- `null`: non-empty string.
- `alternative`: non-empty string.
- `non_inferiority_margin_pp`: nullable percentage-point float. Required for
  `regression` mode, otherwise null.

### Criterion

Required fields:

- `criterion_id`: stable dotted id, e.g. `criterion.primary_power`.
- `purpose`: non-empty string.
- `estimand`: non-empty string.
- `null_hypothesis`: non-empty string.
- `alternative_hypothesis`: non-empty string.
- `primary_metric`: one `primary_metric` enum value.
- `test_family`: one `test_family` enum value.
- `alpha`: float in `(0, 1)`.
- `beta_or_target_power`: float in `(0, 1)`.
- `minimum_detectable_effect_pp`: nullable percentage-point float.
- `required_data`: list of required outcome fields or task properties.
- `decision_rule`: non-empty string that names the pass/fail threshold.
- `allowed_claim`: non-empty string scoped to the planned evidence.
- `failure_modes`: list of non-empty strings.
- `confirmatory`: boolean.
- `guide_references`: non-empty list of `StatisticalGuideReference`.
- `selection_rationale`: non-empty string explaining why this criterion was
  selected from the guide.

### TaskDistribution

Required fields:

- `short_chain`
- `medium_chain`
- `long_chain`
- `cross_server_ratio`
- `recovery_required_ratio`
- `prerequisite_strict_ratio`
- `stateful_write_ratio`
- `categories`: non-empty list of category labels.
- `distractors`: `DistractorPolicy`.
- `diagnostic_slices`: list of `DiagnosticSlice`.

Chain-length fractions must sum to `1.0` within tolerance `0.001`.

### DistractorPolicy

Required fields:

- `same_name_fraction`
- `near_miss_fraction`
- `cross_domain_fraction`
- `random_fraction`

The four distractor fractions must sum to `<= 1.0`. Unallocated probability is
interpreted as no extra distractor pressure.

### DiagnosticSlice

Required fields:

- `slice_id`: stable dotted id.
- `label`: non-empty string.
- `ratio`: float in `[0, 1]`.
- `confirmatory`: boolean.

### AnalysisPlan

Required fields:

- `ci_method`: one `ci_method` enum value.
- `mde_method`: one `mde_method` enum value.
- `rank_stability_method`: one `rank_stability_method` enum value.
- `pairwise_test`: one `test_family` enum value or `null`.
- `alpha`: float in `(0, 1)`.
- `beta`: float in `(0, 1)`.
- `planning_assumptions`: non-empty list of strings.
- `heuristic_label`: literal `"planning_heuristic"`.

### WarningCard

Required fields:

- `severity`: one of `info`, `warning`, `critical`.
- `code`: one `warning_code` enum value.
- `message`: non-empty string.
- `failed_criterion_id`: nullable string.
- `statistical_reason`: nullable non-empty string.
- `repair_suggestion`: non-empty string.

Example:

```json
{
  "severity": "warning",
  "code": "underpowered_design",
  "message": "The planned task count is too small for the requested model-selection claim.",
  "failed_criterion_id": "criterion.primary_power",
  "statistical_reason": "The planned MDE is above the requested detectable effect.",
  "repair_suggestion": "Increase task_budget or frame this as a smoke test."
}
```

### Refusal

Required fields:

- `code`: one `refusal_code` enum value.
- `reason`: non-empty string.
- `statistical_reason`: non-empty string.
- `failed_criterion_id`: non-empty string.
- `repair_options`: non-empty list of strings.

### ClarificationRequest

Required fields:

- `missing_fields`: non-empty list of field names or design concepts.
- `questions`: non-empty list of user-facing questions.
- `why_needed`: non-empty string.

### EvidenceLedgerEntry

Required fields:

- `parameter`: non-empty field path.
- `value`: JSON scalar, list, object, or null.
- `intent_evidence`: non-empty string or null when the value is a default.
- `statistical_rationale`: non-empty string.
- `guide_references`: non-empty list of `StatisticalGuideReference`.
- `hover_text`: non-empty user-visible explanation for a tooltip/popover.
- `judge_validation_hint`: nullable string describing what a future judge-based
  validator should check in this rationale.
- `validator_status`: one `validator_status` enum value.
- `repair_suggestion`: nullable string.

`hover_text` should be concrete and short. It should answer: "Why did the
advisor choose this value or criterion?" without restating unsupported claims.

### ExportGenerationKnobs

These knobs are the v1 bridge to the existing generation pipeline. The export
validator checks the shape only; it must not launch generation.

Required fields:

- `handoff_target`: literal `"scripts/build_corpus.py"`.
- `dry_run_only`: literal `true` in v1.
- `goal_strategy`: one of `deployment_slice`, `leaderboard_mix`,
  `regression_replay`, `diagnostic_slice`.
- `max_tool_calls_per_task`: integer `>= 1`; default recommendation is `6`.
- `server_scope`: list of server ids, or empty list when not yet chosen.
- `sandbox_required`: boolean. Must be true when `stateful_write_ratio > 0`.
- `generation_notes`: list of strings.

Mapping to current pipeline terms:

| export field | pipeline meaning |
|---|---|
| `tasks` | target number of generated TaskSpecs, not a task list |
| `attempts_per_task` | planned candidate evaluation repeats, not generation repeats |
| `task_distribution.categories` | desired goal/category mix for future corpus generation |
| `task_distribution.*_ratio` | coverage targets for generated TaskSpecs |
| `distractors` | future tool-pool pressure policy; no scoring change |
| `generation_knobs.server_scope` | candidate server ids for future goal generation |
| `generation_knobs.dry_run_only` | v1 guard that prevents generation launch |

### ExportConfig

`ExportConfig` is JSON-only in v1 and must not launch generation.

Required fields:

- `schema_version`: literal `"benchmark_advisor.v1"`.
- `mode`: one `mode` enum value.
- `candidate_models`: list of strings. May be empty only for `diagnostic` or
  `smoke_test_only` designs.
- `evaluation_question`
- `estimand`
- `hypotheses`
- `criteria`
- `tasks`: integer `>= 1`.
- `attempts_per_task`: integer `>= 1`.
- `task_distribution`
- `distractors`: must equal `task_distribution.distractors`; duplicated here so
  export consumers can find distractor policy without traversing the full design.
- `analysis_plan`
- `warnings`: list of `WarningCard`.
- `claim_boundary`
- `generation_knobs`: `ExportGenerationKnobs`.

### ValidationReportStub

Stage-2 interface placeholder. It must be present in `AdvisorResponse`, but
`implemented` must be `false` in v1.

Required fields:

- `schema_version`: literal `"benchmark_advisor.report.v1"`.
- `implemented`: literal `false`.
- `outcome_tensor`: `OutcomeTensorContract`.
- `supported_future_questions`: list containing only:
  - `models_above_success_threshold`
  - `pairwise_win_probability`
  - `rank_stability`
  - `slice_failure_diagnostics`

### OutcomeTensorContract

Required fields:

- `shape`: literal `"X[task, model, attempt, metric, slice]"`.
- `task_axis`: task id, spec schema version, complexity profile, and slice labels.
- `model_axis`: candidate model label and provider family.
- `attempt_axis`: zero-based attempt index and deterministic replay seed if used.
- `metric_axis`: allowed metric labels from `primary_metric`.
- `slice_axis`: `all` plus diagnostic slice ids.
- `missingness_policy`: literal `"explicit_null_with_reason"`.
- `stage_2_only`: literal `true`.

### AdvisorResponse

Required fields:

- `schema_version`: literal `"benchmark_advisor.v1"`.
- `status`: one `status` enum value.
- `design`: nullable `AdvisorDesign`.
- `warnings`: list of `WarningCard`.
- `refusal`: nullable `Refusal`.
- `clarification`: nullable `ClarificationRequest`.
- `evidence_ledger`: list of `EvidenceLedgerEntry`.
- `export_config`: nullable `ExportConfig`.
- `validation_report_stub`: `ValidationReportStub`.

Example:

```json
{
  "schema_version": "benchmark_advisor.v1",
  "status": "warning",
  "design": {},
  "warnings": [],
  "refusal": null,
  "clarification": null,
  "evidence_ledger": [],
  "export_config": {},
  "validation_report_stub": {}
}
```

## V2 Statistical Advisor Types

These contracts are implemented by T11-T18. Field names are normative, but v2
implementation may add non-breaking optional fields after tests and docs are
updated.

T11 defines the base v2 schema surface. T14 extends that base with typed
Statistical Engine objects. Until T14 is implemented, existing T11 fixtures may
omit `engine_decision`; after T14, `POST /api/advisor/v2/design` must return a
`StatisticalPlan` whose recommendation is derived from an `EngineDecision`.

### StatisticalIssue

Required fields:

- `severity`: one of `info`, `warning`, `critical`.
- `code`: stable snake-case issue code.
- `message`: non-empty user-visible message.
- `failed_field`: nullable field path.
- `failed_criterion_id`: nullable criterion id.
- `statistical_reason`: non-empty explanation.
- `repair_options`: list of non-empty user actions.
- `guide_references`: list of `StatisticalGuideReference`.

V2 validation returns all applicable issues. Status precedence remains
`refused > needs_clarification > warning > approved`.

### AssumptionLedger

Required fields:

- `baseline_rate`: nullable float in `[0, 1]`.
- `paired_design`: boolean.
- `independence_assumption`: non-empty string.
- `repeated_attempts_policy`: non-empty string.
- `missingness_policy`: non-empty string.
- `multiplicity_policy`: non-empty string.
- `sensitivity_notes`: list of strings.
- `guide_references`: list of `StatisticalGuideReference`.

### PowerAnalysis

Required fields:

- `alpha`: float in `(0, 1)`.
- `target_power`: float in `(0, 1)`.
- `planned_mde_pp`: percentage-point float.
- `ci_width_pp`: percentage-point float.
- `method`: one `mde_method` or non-empty method label.
- `power_curve`: list of objects with `task_budget`, `mde_pp`, and
  `ci_width_pp`.
- `budget_alternatives`: list of objects with `task_budget`, `detectable_effect_pp`,
  and `claim_status`.
- `assumptions`: `AssumptionLedger`.

### ParameterSearchSpace

Required fields:

- `task_budget_grid`: list of integer task budgets.
- `attempts_grid`: list of integer attempt counts.
- `effect_target_grid_pp`: list of percentage-point effects.
- `distribution_candidates`: list of task-distribution candidates.
- `confirmatory_slice_limit`: integer `>= 1`.
- `method_families`: list of method labels.
- `server_scope_options`: list of server-scope lists.

### ParameterCandidate

Required fields:

- `candidate_id`: stable id.
- `design`: `AdvisorDesign` or v2-compatible successor.
- `power_analysis`: `PowerAnalysis`.
- `assumption_ledger`: `AssumptionLedger`.
- `issues`: list of `StatisticalIssue`.
- `score`: numeric score used only for deterministic candidate ordering.
- `status`: one advisor `status`.
- `rejection_reasons`: list of strings.
- `repair_actions`: list of strings.

### EngineComputationTrace

Required fields:

- `engine_version`: non-empty string.
- `guide_version`: literal `"statistical_guide.v1"`.
- `guide_snapshot_id`: nullable string.
- `random_seed`: nullable integer.
- `candidate_count`: integer `>= 1`.
- `formula_versions`: list of method/formula labels.
- `empirical_prior_sources`: list of local source ids.
- `validator_rule_ids`: list of guide rule ids or validator rule ids.
- `selected_reason`: non-empty string.

### EngineDecision

Required fields:

- `schema_version`: literal `"benchmark_advisor.engine_decision.v2"`.
- `recommended_candidate_id`: stable id.
- `recommended_design`: `AdvisorDesign` or v2-compatible successor.
- `parameter_search_space`: `ParameterSearchSpace`.
- `parameter_candidates`: non-empty list of `ParameterCandidate`.
- `design_alternatives`: list of `DesignAlternative`.
- `power_analysis`: `PowerAnalysis`.
- `assumption_ledger`: `AssumptionLedger`.
- `claim_card`: object with `allowed_claims`, `not_allowed_claims`, and
  `plain_language_summary`.
- `issues`: list of `StatisticalIssue`.
- `citations`: list of local statistical-knowledge citations.
- `computation_trace`: `EngineComputationTrace`.

### DesignAlternative

Required fields:

- `alternative_id`: stable id.
- `label`: non-empty user-facing label.
- `task_budget`: integer `>= 1`.
- `attempts_per_task`: integer `>= 1`.
- `target_detectable_effect_pp`: nullable percentage-point float.
- `status`: one advisor `status`.
- `tradeoff`: non-empty explanation.
- `repair_actions`: list of strings.

### StatisticalPlan

Required fields:

- `schema_version`: literal `"benchmark_advisor.statistical_plan.v2"`.
- `design`: `AdvisorDesign` or v2-compatible successor.
- `engine_decision`: `EngineDecision` once T14 lands; omitted only by the
  T11-base contract before Statistical Engine implementation.
- `power_analysis`: `PowerAnalysis`.
- `design_alternatives`: list of `DesignAlternative`.
- `assumption_ledger`: `AssumptionLedger`.
- `issues`: list of `StatisticalIssue`.
- `citations`: list of local statistical-knowledge citations.
- `claim_card`: object with `allowed_claims`, `not_allowed_claims`, and
  `plain_language_summary`.

### OutcomeTensor

Required fields:

- `schema_version`: literal `"benchmark_advisor.outcome_tensor.v2"`.
- `shape`: literal `"X[task, model, attempt, metric, slice]"`.
- `tasks`: task-axis metadata.
- `models`: model-axis metadata.
- `attempts`: attempt-axis metadata.
- `metrics`: metric-axis metadata.
- `slices`: slice-axis metadata.
- `values`: outcome values with explicit missingness reason when absent.

### StatisticalReport

Required fields:

- `schema_version`: literal `"benchmark_advisor.report.v2"`.
- `mode`: one `mode`.
- `status`: one advisor `status`.
- `effect_sizes`: list of effect-size records.
- `confidence_intervals`: list of CI records.
- `rank_stability`: nullable rank-stability result.
- `slice_diagnostics`: list of diagnostic slice results.
- `missingness`: missingness summary.
- `multiplicity`: multiplicity summary.
- `allowed_claims`: list of strings.
- `not_allowed_claims`: list of strings.
- `issues`: list of `StatisticalIssue`.

### LaunchRequest and LaunchJob

Required `LaunchRequest` fields:

- `schema_version`: literal `"benchmark_advisor.launch.v2"`.
- `export_config`: approved or warning advisor export.
- `confirmation`: literal `true`.
- `dry_run`: boolean.
- `requested_by_ui`: boolean.

Required `LaunchJob` fields:

- `schema_version`: literal `"benchmark_advisor.launch_job.v2"`.
- `job_id`: stable id.
- `status`: one of `queued`, `running`, `succeeded`, `failed`, `cancelled`.
- `command_preview`: list of command argv strings.
- `logs`: list of log lines.
- `artifacts`: object with nullable `goals`, `specs`, `traces`, and `coverage`
  paths.

The first v2 launch target is corpus/specs/traces through
`scripts/build_corpus.py`. Leaderboard and eval launch are out of scope.

## Public API

### POST /api/advisor/design

Input: `AdvisorRequest`.

Output: `AdvisorResponse`.

Behavior:

- runs planner adapter;
- runs deterministic validator;
- includes export preview only when design is not refused or clarification-only;
- does not launch generation or evaluation.

### POST /api/advisor/validate

Input: `AdvisorValidationRequest`.

Output: `AdvisorResponse`.

Behavior:

- validates user-edited structured design;
- may use `original_request` only for explicit metadata such as mode, candidate
  models, budget, and user-approved overrides;
- does not call planner unless explicitly supplied by API caller in a future
  version;
- does not launch generation or evaluation.

### POST /api/advisor/v2/design

Input: v2-compatible advisor request.

Output: v2 statistical design response containing `StatisticalPlan`, issue list,
citations, alternatives, and v1-compatible design/export data where applicable.

Behavior:

- uses `STATISTICAL_GUIDE.md` rule ids/source keys as the default knowledge
  source;
- may use local RAG/stat-agent proposal only as an optional future enhancement;
- must run deterministic validation before returning;
- must keep the route side-effect free.

### POST /api/advisor/v2/validate

Input: edited v2 design or statistical plan.

Output: v2 validation response with all `StatisticalIssue` objects.

Behavior:

- validates structured edits;
- preserves status precedence;
- returns no export or launch action for refused or clarification states.

### POST /api/advisor/v2/report

Input: `OutcomeTensor`.

Output: `StatisticalReport`.

Behavior:

- computes post-run statistical summaries;
- states allowed and not-allowed claims;
- does not run generation or evaluation.

### POST /api/advisor/v2/launch

Input: `LaunchRequest`.

Output: `LaunchJob`.

Behavior:

- requires explicit confirmation;
- accepts only approved or warning export configs;
- validates sandbox and stateful-write guards;
- launches only the corpus/specs/traces path through `scripts/build_corpus.py`;
- never runs leaderboard/eval in the first handoff.

## File And Fixture Formats

Golden fixtures live under `docs_benchmark_advisor/fixtures/`.

Each fixture is one JSON file with:

- `id`
- `description`
- `request`: `AdvisorRequest`
- `expected_status`: one `status` enum value
- `expected_warning_codes`: list of `warning_code`
- `expected_refusal_code`: nullable `refusal_code`
- `expected_clarification_missing_fields`: list of strings
- `expected_export_subset`: object; omitted only when export is expected to be
  null

Fixture ids must be stable, lowercase, and hyphen-separated.

## Error Conventions

- Schema errors are validation errors.
- Unsupported/ambiguous intent maps to `needs_clarification`.
- Statistically indefensible designs map to `refused`.
- Usable but weak designs map to `warning`.
- Approved designs may still include `info` warnings.
- Requests for final-answer grading map to `refused` with
  `unsupported_final_answer_claim`.
- Requests to launch generation or evaluation from advisor routes map to
  `refused` with `generation_launch_forbidden`.

## Must Not Change Without Integration Decision

- Public API route names.
- `schema_version` strings.
- `STATISTICAL_GUIDE.md` rule ids or guide version.
- Required fields in shared types.
- Enum registries.
- Validator thresholds.
- Response state matrix.
- Golden fixture format.
- Export config required fields.
- Rule that Advisor UI must not launch expensive evaluation.
