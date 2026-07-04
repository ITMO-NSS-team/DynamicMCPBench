# Card 06 - Canonical BA5.4 Fixtures

Status: answered implementation contract.

Scope: proposed golden fixture suite for the full BA5.4 Statistical Engine. The
suite is designed for conversion into JSON examples under
`docs_benchmark_advisor/fixtures/` or Python fixtures under `tests/`.

## Fixture Policy

Use both routes:

- `/api/advisor/v2/design` for engine search and recommended plans;
- `/api/advisor/v2/validate` for edited/locked weak designs.

This distinction matters. The design endpoint is allowed to repair a weak user
budget by recommending a higher-budget candidate. Low-budget warning/refusal
fixtures should therefore use validate/edit scenarios when the expected behavior
is "this exact edited plan is weak or invalid".

All fixture payloads must use current field names from `AdvisorV2DesignRequest`,
`AdvisorV2ValidationRequest`, `StatisticalPlan`, `EngineDecision`, and issue
cards. Proposed issue codes are v2 `StatisticalIssue.code` values unless marked
as existing v1 warning/refusal codes.

## Fixture Matrix

| Fixture id | Route | Mode | Request summary | Expected status | Required issues | Export? | Main test purpose |
|---|---|---|---|---|---|---|---|
| `ba5-4-pairwise-approved-finance` | `/design` | `pairwise` | two agents, short finance workflows, 100 tasks | `approved` | none | yes | normal engine-derived pairwise recommendation |
| `ba5-4-pairwise-underpowered-warning` | `/validate` | `pairwise` | edited to 70 tasks with 20pp target | `warning` | `underpowered_design` | yes | exact weak plan keeps user question but warns |
| `ba5-4-pairwise-small-budget-refused` | `/validate` | `pairwise` | edited to 40 tasks for confirmatory pairwise | `refused` | `insufficient_budget` | no | exact low-budget confirmatory plan is refused |
| `ba5-4-leaderboard-exploratory-warning` | `/validate` | `leaderboard` | three models, 100 tasks | `warning` | `underpowered_design`, `rank_stability_uncertain` | yes | leaderboard is not point-rank proof |
| `ba5-4-leaderboard-stronger-alternative` | `/design` | `leaderboard` | four models, 150 tasks | `approved` | none or rank caveat issue if implemented as warning | yes | stronger alternative improves rank-resolution proxy |
| `ba5-4-regression-missing-margin-refused` | `/design` | `regression` | old vs new agent, no margin | `refused` | `missing_non_inferiority_margin` | no | regression cannot invent non-inferiority margin |
| `ba5-4-regression-approved-margin` | `/design` | `regression` | fixed finance slice, 20pp margin, 120 tasks | `approved` | none | yes | margin maps to non-inferiority planning |
| `ba5-4-diagnostic-same-name-hard-negative` | `/design` | `diagnostic` | same-name and hard-negative finance diagnostics | `approved` | none | yes | diagnostic pressure is represented in knobs/slices |
| `ba5-4-diagnostic-overclaim-refused` | `/design` | `diagnostic` | asks best overall but only same-name diagnostic slice | `refused` | `diagnostic_overclaim` | no | diagnostic-only design cannot support broad selection |
| `ba5-4-edited-plan-candidate-count-refused` | `/validate` | `pairwise` | approved plan edited to add third candidate | `refused` | `unsupported_candidate_model_count` | no | validate refresh recomputes engine decision and issues |

## Common Assertions

Every fixture should assert:

- `task_budget` is unique task count, not `task_budget * attempts_per_task`;
- `statistical_plan.engine_decision` is present for non-preflight v2 outputs;
- `parameter_search_space.task_budget_grid` is finite and non-empty;
- `design_alternatives` contains `alt.budget_minimum`, `alt.recommended`,
  `alt.stronger`, and `alt.narrowed_claim` where route behavior permits;
- `PowerAnalysis.alpha == 0.05`;
- `PowerAnalysis.target_power == 0.80` when request beta is `0.20`;
- `AssumptionLedger.missingness_policy` and `multiplicity_policy` are non-empty;
- local citations use known `STATISTICAL_GUIDE.md` rule ids;
- warnings/refusals include non-empty `repair_options`;
- changing citation snippet prose does not change deterministic status;
- `attempts_per_task` changes alone do not improve iid MDE/CI calculations.

## Fixture Sketches

### 1. `ba5-4-pairwise-approved-finance`

```yaml
fixture_id: ba5-4-pairwise-approved-finance
route: POST /api/advisor/v2/design
purpose: normal two-model pairwise request becomes approved and engine-derived
request:
  schema_version: benchmark_advisor.v2
  intent: Compare agent-a and agent-b on short finance workflows using finance tools.
  mode: pairwise
  task_budget: 100
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
expected:
  status: approved
  exportable: true
  launchable: true
  key_design_fields:
    mode: pairwise
    claim_scope: confirmatory_model_selection
    task_budget: 100
    primary_metric: pairwise_delta_pp
    test_family: paired_bootstrap
    ci_method: paired_bootstrap
    mde_method: paired_bootstrap_heuristic
    paired_design: true
  required_issue_codes: []
  forbidden_issue_codes:
    - unsupported_candidate_model_count
    - insufficient_budget
  claim_card:
    allowed_claims:
      - scoped pairwise difference on the planned finance/short-workflow distribution
    not_allowed_claims:
      - universal best-model claim
      - unseen private-deployment guarantee
  alternatives:
    - alt.budget_minimum
    - alt.recommended
    - alt.stronger
    - alt.narrowed_claim
  required_rule_ids:
    - G1.pairwise.selection
    - G2.metric.pairwise_delta
    - G4.budget.mode_thresholds
    - G5.criterion.paired_bootstrap
    - G6.claim.no_universal_best
  test_assertions:
    - recommended_candidate_id exists in parameter_candidates
    - power_analysis.planned_mde_pp == round(planned_mde_pp(100), 3)
    - export_config.tasks == 100
    - export_config.generation_knobs.server_scope == [finance-tools]
```

### 2. `ba5-4-pairwise-underpowered-warning`

```yaml
fixture_id: ba5-4-pairwise-underpowered-warning
route: POST /api/advisor/v2/validate
purpose: exact edited pairwise plan warns when target effect is below planned MDE
setup_request:
  schema_version: benchmark_advisor.v2
  intent: Compare two local agents on short finance workflows and detect a 20pp difference.
  mode: pairwise
  task_budget: 100
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b]
  target_detectable_effect_pp: 20.0
  server_scope: [finance-tools]
edit:
  design.task_budget: 70
validation_request:
  schema_version: benchmark_advisor.v2
  original_request: use setup_request
  edited_fields: [design.task_budget]
expected:
  status: warning
  exportable: true
  launchable: true
  key_design_fields:
    task_budget: 70
    target_detectable_effect_pp: 20.0
    primary_metric: pairwise_delta_pp
  required_issue_codes:
    - underpowered_design
  forbidden_issue_codes:
    - insufficient_budget
  claim_card:
    allowed_claims:
      - scoped pairwise claim with underpowered-design caveat
    not_allowed_claims:
      - confident small-effect model selection without more tasks
  alternatives:
    - repair task_budget to at least required_tasks_for_mde(20.0)
    - accept target_detectable_effect_pp near planned_mde_pp(70)
  required_rule_ids:
    - G4.mde.underpowered
    - G4.mde.heuristic
  test_assertions:
    - planned_mde_pp(70) > 20.0
    - 20.0 >= 0.75 * planned_mde_pp(70)
    - response.issues contains underpowered_design
    - export_config.tasks == 70
```

### 3. `ba5-4-pairwise-small-budget-refused`

```yaml
fixture_id: ba5-4-pairwise-small-budget-refused
route: POST /api/advisor/v2/validate
purpose: exact edited pairwise design below warning floor refuses confirmatory claim
setup_request:
  schema_version: benchmark_advisor.v2
  intent: Compare two local agents on finance workflows.
  mode: pairwise
  task_budget: 100
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
edit:
  design.task_budget: 40
validation_request:
  schema_version: benchmark_advisor.v2
  original_request: use setup_request
  edited_fields: [design.task_budget]
expected:
  status: refused
  exportable: false
  launchable: false
  key_design_fields:
    task_budget: 40
    claim_scope: confirmatory_model_selection
  required_issue_codes:
    - insufficient_budget
  claim_card:
    allowed_claims:
      - no confirmatory claim until critical issues are repaired
    not_allowed_claims:
      - model selection
      - universal model ranking
  alternatives:
    - increase task_budget to 100
    - downgrade claim_scope to smoke_test_only
  required_rule_ids:
    - G4.budget.mode_thresholds
    - G1.smoke.budget
  test_assertions:
    - response.export_config is null
    - any critical issue has code insufficient_budget
```

### 4. `ba5-4-leaderboard-exploratory-warning`

```yaml
fixture_id: ba5-4-leaderboard-exploratory-warning
route: POST /api/advisor/v2/validate
purpose: exact low-budget leaderboard is exploratory and cannot imply final ranks
setup_request:
  schema_version: benchmark_advisor.v2
  intent: Rank three local agents on finance workflows.
  mode: leaderboard
  task_budget: 150
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b, agent-c]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
edit:
  design.task_budget: 100
validation_request:
  schema_version: benchmark_advisor.v2
  original_request: use setup_request
  edited_fields: [design.task_budget]
expected:
  status: warning
  exportable: true
  launchable: true
  key_design_fields:
    mode: leaderboard
    task_budget: 100
    primary_metric: rank_stability
    test_family: rank_stability_bootstrap
    rank_stability_method: bootstrap_tasks_within_strata
  required_issue_codes:
    - underpowered_design
    - rank_stability_uncertain
  claim_card:
    allowed_claims:
      - exploratory leaderboard display with rank-stability caveats
    not_allowed_claims:
      - exact final ranking
      - pairwise superiority without multiplicity plan
  alternatives:
    - increase task_budget to 150 for first approved leaderboard
    - increase task_budget to 300 or 500 for stronger rank-resolution proxy
  required_rule_ids:
    - G1.leaderboard.ranking
    - G2.metric.rank_stability
    - G5.criterion.rank_stability
    - G5.multiple.holm_confirmatory
  test_assertions:
    - len(candidate_models) == 3
    - rank_resolution_pp at stronger budget is lower than at 100 tasks
```

### 5. `ba5-4-leaderboard-stronger-alternative`

```yaml
fixture_id: ba5-4-leaderboard-stronger-alternative
route: POST /api/advisor/v2/design
purpose: stronger leaderboard alternative materially improves rank-resolution proxy
request:
  schema_version: benchmark_advisor.v2
  intent: Rank four local agents on mixed finance workflows with rank-stability caveats.
  mode: leaderboard
  task_budget: 150
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b, agent-c, agent-d]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
expected:
  status: approved
  exportable: true
  launchable: true
  key_design_fields:
    mode: leaderboard
    primary_metric: rank_stability
    test_family: rank_stability_bootstrap
  required_issue_codes: []
  claim_card:
    allowed_claims:
      - scoped leaderboard display with rank-stability caveats
    not_allowed_claims:
      - universal model ranking
      - pairwise superiority for every pair
  alternatives:
    - alt.stronger has task_budget > alt.recommended.task_budget
    - alt.stronger has lower rank_resolution_pp or planned_mde_pp proxy
  required_rule_ids:
    - G1.leaderboard.ranking
    - G2.metric.rank_stability
    - G5.criterion.rank_stability
  test_assertions:
    - alt.stronger.task_budget >= 300
    - stronger proxy improves monotonically
```

### 6. `ba5-4-regression-missing-margin-refused`

```yaml
fixture_id: ba5-4-regression-missing-margin-refused
route: POST /api/advisor/v2/design
purpose: regression mode refuses missing non-inferiority margin
request:
  schema_version: benchmark_advisor.v2
  intent: Check whether the new finance agent regressed compared with the old agent.
  mode: regression
  task_budget: 120
  attempts_per_task: 1
  candidate_models: [old-agent, new-agent]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
expected:
  status: refused
  exportable: false
  launchable: false
  key_design_fields: null
  required_issue_codes:
    - missing_non_inferiority_margin
  claim_card:
    allowed_claims:
      - no non-inferiority claim until a margin is predeclared
    not_allowed_claims:
      - candidate is non-inferior
      - candidate is better
  alternatives:
    - set target_detectable_effect_pp before evaluation
  required_rule_ids:
    - G1.regression.non_inferiority
    - G2.metric.non_inferiority
    - G5.criterion.non_inferiority
  test_assertions:
    - response.export_config is null
    - issue.failed_field == target_detectable_effect_pp
```

### 7. `ba5-4-regression-approved-margin`

```yaml
fixture_id: ba5-4-regression-approved-margin
route: POST /api/advisor/v2/design
purpose: supplied margin produces scoped non-inferiority plan
request:
  schema_version: benchmark_advisor.v2
  intent: Check that new-agent is not worse than old-agent on fixed finance regression slice.
  mode: regression
  task_budget: 120
  attempts_per_task: 1
  candidate_models: [old-agent, new-agent]
  target_detectable_effect_pp: 20.0
  server_scope: [finance-tools]
expected:
  status: approved
  exportable: true
  launchable: true
  key_design_fields:
    mode: regression
    claim_scope: regression_non_inferiority
    target_detectable_effect_pp: 20.0
    hypotheses.non_inferiority_margin_pp: 20.0
    primary_metric: non_inferiority_margin_pp
    test_family: non_inferiority_margin
  required_issue_codes: []
  claim_card:
    allowed_claims:
      - new-agent is not worse than old-agent by more than 20pp on the fixed slice, subject to post-run analysis
    not_allowed_claims:
      - new-agent is better than old-agent
      - universal production guarantee
  alternatives:
    - alt.stronger with higher task_budget and lower planned MDE
  required_rule_ids:
    - G1.regression.non_inferiority
    - G2.metric.non_inferiority
    - G5.criterion.non_inferiority
  test_assertions:
    - target_detectable_effect_pp >= planned_mde_pp(recommended_task_budget)
    - claim_card.not_allowed_claims contains superiority limitation
```

### 8. `ba5-4-diagnostic-same-name-hard-negative`

```yaml
fixture_id: ba5-4-diagnostic-same-name-hard-negative
route: POST /api/advisor/v2/design
purpose: same-name and hard-negative diagnostics create real slice pressure
request:
  schema_version: benchmark_advisor.v2
  intent: Diagnose same-name and hard-negative finance tool confusion.
  mode: diagnostic
  task_budget: 100
  attempts_per_task: 1
  candidate_models: []
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
expected:
  status: approved
  exportable: true
  launchable: true
  key_design_fields:
    mode: diagnostic
    claim_scope: diagnostic_slice
    primary_metric: slice_failure_rate
    test_family: diagnostic_descriptive
    ci_method: wilson_score
    diagnostic_slices:
      - slice_id: slice.same_name
        confirmatory: false
    distractors.same_name_fraction: ">= 0.25"
    distractors.near_miss_fraction: ">= 0.25"
  required_issue_codes: []
  claim_card:
    allowed_claims:
      - exploratory diagnostic description of same-name / hard-negative failures
    not_allowed_claims:
      - broad model-selection claim
  alternatives:
    - stronger diagnostic alternative at 200 tasks
  required_rule_ids:
    - G1.diagnostic.slice
    - G2.metric.diagnostic_slice
    - G3.coverage.same_name
    - G3.distractor.hard_negative
    - G3.distractor.claim_requires_pressure
    - G5.criterion.descriptive_diagnostic
  test_assertions:
    - diagnostic slice is present
    - generator pressure is present in distractor fractions
    - broad selection is not in allowed_claims
```

### 9. `ba5-4-diagnostic-overclaim-refused`

```yaml
fixture_id: ba5-4-diagnostic-overclaim-refused
route: POST /api/advisor/v2/design
purpose: narrow diagnostic-only plan cannot answer best-overall model-selection question
request:
  schema_version: benchmark_advisor.v2
  intent: Which model is best overall? Only test same-name hard-negative finance tool confusion.
  mode: diagnostic
  task_budget: 100
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
expected:
  status: refused
  exportable: false
  launchable: false
  key_design_fields:
    mode: diagnostic
    diagnostic_slices:
      - same-name / hard-negative
  required_issue_codes:
    - diagnostic_overclaim
  claim_card:
    allowed_claims:
      - diagnostic-only finding after narrowing the claim
    not_allowed_claims:
      - best overall model
      - broad model selection
      - universal ranking
  alternatives:
    - switch mode to pairwise and add representative task distribution
    - keep diagnostic mode and remove best-overall claim
  required_rule_ids:
    - G1.diagnostic.slice
    - G6.claim.diagnostic_not_selection
    - G6.claim.no_universal_best
  test_assertions:
    - response.export_config is null
    - diagnostic_overclaim has repair_options for mode/claim change
```

### 10. `ba5-4-edited-plan-candidate-count-refused`

```yaml
fixture_id: ba5-4-edited-plan-candidate-count-refused
route: POST /api/advisor/v2/validate
purpose: validate refresh recomputes engine decision after user adds third candidate to pairwise plan
setup_request:
  schema_version: benchmark_advisor.v2
  intent: Compare two local agents on short finance workflows.
  mode: pairwise
  task_budget: 100
  attempts_per_task: 1
  candidate_models: [agent-a, agent-b]
  target_detectable_effect_pp: null
  server_scope: [finance-tools]
edit:
  design.candidate_models: [agent-a, agent-b, agent-c]
validation_request:
  schema_version: benchmark_advisor.v2
  original_request: use setup_request
  edited_fields: [design.candidate_models]
expected:
  status: refused
  exportable: false
  launchable: false
  key_design_fields:
    mode: pairwise
    candidate_models: [agent-a, agent-b, agent-c]
  required_issue_codes:
    - unsupported_candidate_model_count
  claim_card:
    allowed_claims:
      - no confirmatory claim until the candidate count is repaired
    not_allowed_claims:
      - pairwise model selection with three candidates
  alternatives:
    - remove one candidate
    - switch mode to leaderboard
  required_rule_ids:
    - G1.pairwise.selection
  test_assertions:
    - refreshed engine_decision is present
    - computation_trace.candidate_count == 1 for validate refresh
    - export_config is null
```

## Conversion Guidance

When converting these sketches to tests:

- Use exact Pydantic schemas for request/response construction.
- Prefer relational numeric assertions over hard-coded floats:
  - `planned_mde_pp(70) > 20.0`;
  - `target >= 0.75 * planned_mde`;
  - stronger alternative has lower MDE or rank-resolution proxy.
- Keep issue-code assertions exact.
- Keep guide rule ids exact and validate them against
  `STATISTICAL_GUIDE.md`.
- Mark proposed BA5.4 codes as v2 free-form `StatisticalIssue.code` until they
  are intentionally promoted to v1 warning/refusal literals.

## Final Decision

Use this 10-fixture suite as the minimum BA5.4 acceptance set. It covers all
modes, every response state, engine alternatives, validate refresh, mode-specific
formula interpretation, overclaim prevention, local citations, and the key MCP
tool-use cases: finance, same-name tools, hard negatives, cross-slice
diagnostics, leaderboard rank uncertainty, and regression non-inferiority.
