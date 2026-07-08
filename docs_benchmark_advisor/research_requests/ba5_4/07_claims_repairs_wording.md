# Card 07 - Claim And Repair Wording For BA5.4

Status: answered implementation contract.

Scope: controlled user-facing wording for BA5.4 claim cards, issue messages,
statistical reasons, repair actions, assumption caveats, and prohibited phrases.
The wording must map to current schema fields and support future validate/edit
UI buttons.

## Wording Principles

BA5.4 text must:

- distinguish planning assumptions from post-run inference;
- state the scoped task distribution and server scope;
- avoid universal best-model language;
- mark diagnostics exploratory by default;
- state non-inferiority as one-sided and margin-bound;
- state repeated attempts as reliability/pass@k evidence, not iid task count;
- state public logs as priors, not proof for private deployments;
- turn every warning/refusal into concrete field edits when possible.

Use local guide rule ids and source keys for rationale. Do not cite live web
text or unresolved citation numbers.

## Controlled Claim Templates

### Pairwise

| Status | Allowed claim template | Not-allowed claim template |
|---|---|---|
| `approved` | `{model_a} and {model_b} can be compared on {task_distribution} using {method_family}; the planned claim is a scoped pairwise difference of at least the detectable effect supported by {task_budget} unique tasks.` | `This benchmark proves {model_a} is universally better than {model_b}.` |
| `warning` | `{model_a} and {model_b} can still be compared on {task_distribution}, but {task_budget} unique tasks only support a weak or large-effect pairwise claim under the current assumptions.` | `This design can reliably detect {target_effect_pp}pp if that target is below the planned MDE.` |
| `refused` | `No confirmatory pairwise claim is supported until the critical issue is repaired.` | `Model selection, universal superiority, or private-deployment guarantee from this plan.` |

Short approved summary:

```text
Scoped pairwise difference on {task_distribution} for {server_scope}; not a universal ranking.
```

### Leaderboard

| Status | Allowed claim template | Not-allowed claim template |
|---|---|---|
| `approved` | `The plan can display a scoped leaderboard for {model_count} models on {task_budget} unique tasks with {rank_stability_method} caveats.` | `The rank order is final or universally valid across deployments.` |
| `warning` | `The plan can be used as an exploratory leaderboard, but rank stability is uncertain at {task_budget} unique tasks.` | `Top-1, top-k, or pairwise superiority is established without bootstrap rank-stability and multiplicity handling.` |
| `refused` | `No leaderboard ranking claim is supported until the candidate set and budget issues are repaired.` | `A leaderboard with fewer than three models or unsupported exact-rank claims.` |

Short approved summary:

```text
Scoped leaderboard display with rank-stability caveats; pairwise superiority requires a separate predeclared family.
```

### Regression / Non-Inferiority

| Status | Allowed claim template | Not-allowed claim template |
|---|---|---|
| `approved` | `{candidate_model} can be evaluated for non-inferiority to {baseline_model} on {fixed_slice} with predeclared margin {margin_pp}pp.` | `{candidate_model} is better than {baseline_model}.` |
| `warning` | `{candidate_model} can be checked against the {margin_pp}pp margin, but {task_budget} unique tasks make the non-inferiority plan weak under current assumptions.` | `The margin is definitively supported when it is below the planned MDE.` |
| `refused` | `No non-inferiority claim is supported until a margin and sufficient budget are provided before evaluation.` | `A post-hoc margin or superiority claim from this regression check.` |

Short approved summary:

```text
Scoped non-inferiority claim within the predeclared {margin_pp}pp margin on {fixed_slice}.
```

### Diagnostic

| Status | Allowed claim template | Not-allowed claim template |
|---|---|---|
| `approved` | `The plan can describe {slice_name} failures as an exploratory diagnostic slice with {slice_count} planned tasks and {diagnostic_pressure} pressure.` | `The diagnostic slice identifies the best overall model.` |
| `warning` | `The plan can inspect {slice_name}, but slice coverage or diagnostic pressure is weak; treat findings as exploratory.` | `The slice supports confirmatory selection without more tasks, pressure, or multiplicity policy.` |
| `refused` | `No broad model-selection claim is supported from a diagnostic-only design.` | `Best overall model, universal ranking, or production guarantee from this narrow diagnostic slice.` |

Short approved summary:

```text
Exploratory diagnostic description of {slice_name}; not a broad model-selection claim.
```

## Repair Action Vocabulary

Recommended structured repair shape for future UI buttons:

```yaml
repair_id:
field_path:
operation: set | increase_to_at_least | remove | append | rewrite_claim
old_value:
new_value:
value_rule:
expected_effect:
ui_text:
rationale:
```

| Repair category | Target field(s) | Template | Example |
|---|---|---|---|
| increase unique task budget | `design.task_budget` | `Set task_budget to at least {new_budget} unique tasks.` | `Set task_budget to at least 100 unique tasks for approved pairwise planning.` |
| accept larger detectable effect | `design.target_detectable_effect_pp` | `Set target_detectable_effect_pp to {planned_mde_pp}pp, or keep the smaller target and increase task_budget.` | `Set target_detectable_effect_pp to 23.7pp for the current 70-task plan.` |
| reduce confirmatory slices | `design.task_distribution.diagnostic_slices[*].confirmatory` | `Keep at most {limit} confirmatory slices for this budget.` | `Keep only the same-name slice confirmatory; move recovery to exploratory.` |
| move slice to exploratory | `design.task_distribution.diagnostic_slices[*].confirmatory` | `Set confirmatory = false for {slice_id}.` | `Set confirmatory = false for slice.near_miss.` |
| narrow claim boundary | `design.claim_boundary`, `claim_card` | `Rewrite the claim to {narrowed_claim}.` | `Limit the claim to short finance workflows with same-name diagnostics.` |
| switch primary metric | `design.criteria[0].primary_metric` | `Set primary_metric to {metric}.` | `Set primary_metric to pairwise_delta_pp for pairwise model selection.` |
| add attempts for pass@k | `design.attempts_per_task` | `Set attempts_per_task to {k} for pass@{k}; do not use attempts as iid tasks.` | `Set attempts_per_task = 3 for pass@3 reliability.` |
| add paired-task contract | `design.analysis_plan.planning_assumptions`, `design.criteria[0].required_data` | `Require paired task ids and task-level outcomes for both models.` | `Add required_data: paired per-task effect-pass outcomes.` |
| add non-inferiority margin | `design.target_detectable_effect_pp`, `design.hypotheses.non_inferiority_margin_pp` | `Set target_detectable_effect_pp to the predeclared non-inferiority margin.` | `Set target_detectable_effect_pp = 20.0 before evaluation.` |
| add sandbox/state reset | `deployment_context`, export sandbox flag, `user_overrides.sandbox_required` | `Set sandbox_required = true for stateful-write tasks.` | `Set user_overrides.sandbox_required = true before export.` |
| select supported server scope | `server_scope` | `Set server_scope to supported servers: {server_scope}.` | `Set server_scope = [finance-tools].` |
| use public logs as priors only | `engine_decision.computation_trace.empirical_prior_sources`, assumption notes | `Label public logs as empirical priors, not private-deployment proof.` | `Add public-log prior caveat to assumption ledger.` |
| downgrade to smoke test | `design.claim_scope`, `claim_card` | `Set claim_scope = smoke_test_only and remove confirmatory claim wording.` | `Downgrade 40-task pairwise plan to smoke_test_only.` |
| add multiplicity policy | `assumption_ledger.multiplicity_policy` | `Add Holm for confirmatory family or BH/descriptive-only for diagnostics.` | `Use Holm-style policy for two confirmatory slices.` |
| add diagnostic pressure | `design.task_distribution.distractors` | `Set {pressure_field} >= 0.25 for claimed diagnostic pressure.` | `Set near_miss_fraction >= 0.25 for hard-negative tools.` |

## Issue Message Templates

| Code | Severity | Registry status | Message template | Statistical reason template | Repair template |
|---|---|---|---|---|---|
| `underpowered_design` | `warning` | v1 warning | `Task budget {task_budget} is below the planned MDE for the requested {target_effect_pp}pp effect.` | `target {target_effect_pp}pp < planned MDE {planned_mde_pp}pp under {method_family}.` | `Increase task_budget to at least {required_budget}, or accept target_detectable_effect_pp = {planned_mde_pp}pp.` |
| `insufficient_budget` | `critical` | v1 refusal | `Task budget {task_budget} is below the {mode} floor of {warning_floor}.` | `{task_budget} < refusal threshold {warning_floor} for {mode}.` | `Increase task_budget to at least {approved_floor}, or downgrade to smoke_test_only.` |
| `unsupported_candidate_model_count` | `critical` | v2 free-form existing | `{mode} planning requires {required_count_text}.` | `{mode} method constraints do not match candidate_models length {model_count}.` | `{candidate_repair}` |
| `missing_non_inferiority_margin` | `critical` | v2 free-form existing | `Regression planning needs a predeclared non-inferiority margin.` | `Post-hoc non-inferiority margins are not statistically defensible.` | `Set target_detectable_effect_pp as the margin before evaluation.` |
| `diagnostic_overclaim` | `critical` | new v2 free-form | `A diagnostic-only design cannot support the requested broad model-selection claim.` | `Diagnostic slices estimate a narrow failure mode and do not represent the full task distribution.` | `Switch to pairwise/leaderboard with representative coverage, or narrow the claim to the diagnostic slice.` |
| `insufficient_slice_coverage` | `warning` or `critical` | new v2 free-form | `Slice {slice_id} has {slice_count} planned tasks, below the {required_count} target.` | `Slice-level CI width is too wide for the requested confirmatory diagnostic claim.` | `Increase task_budget, increase slice ratio, or mark the slice exploratory.` |
| `too_many_secondary_slices` | `warning` | v1 warning | `More confirmatory or diagnostic slices than the task budget supports.` | `{slice_count} slices exceed limit {slice_limit} for {task_budget} tasks.` | `Move extra slices to exploratory or increase task_budget.` |
| `missing_multiplicity_policy` | `warning` or `critical` | new v2 free-form | `Multiple confirmatory claims require a multiplicity policy.` | `Unadjusted multiple comparisons inflate false-positive risk.` | `Add Holm-style policy or mark extra claims exploratory.` |
| `rank_stability_uncertain` | `warning` | new v2 free-form | `Leaderboard rank stability is uncertain at {task_budget} tasks.` | `The rank-resolution proxy is too coarse for strong rank claims before outcomes.` | `Increase task_budget to {stronger_budget}, or present leaderboard as exploratory.` |
| `missingness_policy_required` | `critical` | new v2 free-form | `Missingness policy is required in the assumption ledger.` | `A benchmark plan must specify how missing task outcomes are represented before reporting.` | `Set missingness_policy to explicit_null_with_reason before post-run reporting.` |
| `expected_missingness_warning` | `warning` | new v2 free-form | `Expected missingness {missingness_rate} may weaken confirmatory claims.` | `Moderate missingness can change effective sample size and claim interpretation.` | `Increase budget, add missingness handling, or narrow the claim.` |
| `expected_missingness_too_high` | `critical` | new v2 free-form | `Expected missingness {missingness_rate} is too high for a confirmatory claim.` | `High missingness can invalidate the planned comparison or margin.` | `Reduce missingness risk or downgrade to exploratory diagnostic.` |
| `floor_ceiling_risk` | `warning` or `critical` | new v2 free-form | `Assumed pass rate {baseline_rate} is near a floor or ceiling.` | `Near-saturated metrics make small effect differences hard to detect and interpret.` | `Rebalance task difficulty or narrow the claim to a diagnostic finding.` |
| `attempts_not_independent_tasks` | `critical` for confirmatory, `warning` otherwise | new v2 free-form | `Repeated attempts were treated as independent tasks.` | `Same-task attempts do not multiply iid sample size for MDE or CI planning.` | `Recompute using unique task_budget; keep attempts only for reliability/pass@k.` |
| `missing_diagnostic_pressure` | `warning` or `critical` | new v2 free-form | `{slice_name} is claimed but the matching generator pressure is missing or too low.` | `A diagnostic claim needs generation knobs that actually create the failure pressure.` | `Set {pressure_field} >= 0.25 or remove the diagnostic claim.` |

Do not introduce `too_many_confirmatory_slices` as a separate v1 code unless the
schema is migrated. Use existing `too_many_secondary_slices` and clarify the
message text.

## Assumption Caveat Templates

| Assumption | Short template | Long template |
|---|---|---|
| baseline rate fallback | `Baseline pass rate defaults to 0.5 for no-prior planning.` | `No pilot/private prior was supplied, so MDE and CI-width planning use baseline_rate = 0.5 and sensitivity branches 0.2/0.5/0.8. This is a planning assumption, not evidence about the workload.` |
| repeated attempts | `Attempts do not multiply iid task count.` | `Repeated attempts can support reliability or pass@k summaries, but power and CI planning use unique tasks as the information unit.` |
| paired task-level comparison | `Pairwise comparisons use paired task-level outcomes.` | `Both models must be evaluated on the same planned tasks. Post-run uncertainty should resample tasks, not attempts or model calls.` |
| missingness policy | `Missing outcomes use explicit null with reason.` | `Every missing task outcome must be recorded with an explicit null and reason before post-run reporting; no-missingness is not assumed unless supplied as a prior.` |
| multiplicity policy | `One primary criterion; extra diagnostics are exploratory unless predeclared.` | `Multiple confirmatory claims require a family policy such as Holm. Larger diagnostic families should use BH/FDR-style handling or descriptive-only reporting.` |
| floor/ceiling risk | `Near-floor or near-ceiling rates can hide useful differences.` | `If expected pass rate is close to 0 or 1, the benchmark may be too hard or too easy for model selection. Rebalance difficulty or use a diagnostic claim.` |
| cluster/template dependence | `Correlated tasks may reduce effective sample size.` | `Shared templates, servers, tools, or trajectories can make n_eff smaller than unique task count. Apply numeric design-effect penalties only with calibrated logs.` |
| empirical prior | `Public logs are calibration priors only.` | `Public or pilot logs can calibrate planning curves, but they do not prove behavior on private deployments or future task pools.` |
| private-transfer caveat | `No unseen private-deployment guarantee.` | `The claim is limited to the planned task distribution and server scope. It should not be presented as a guarantee for unseen private workflows.` |

## Prohibited Phrases

| Prohibited phrase pattern | Why prohibited | Safe replacement |
|---|---|---|
| `This benchmark proves model A is better.` | planning and post-run uncertainty are scoped; no universal proof | `This plan can support a scoped pairwise comparison on the planned distribution if post-run evidence meets the criterion.` |
| `The benchmark is statistically valid.` | vague authority claim with no field-level reason | `The plan is approved for the scoped claim because it meets the budget, method, and assumption checks listed here.` |
| `40 tasks and 3 attempts gives 120 independent samples.` | attempts are not iid tasks | `40 unique tasks with 3 attempts support reliability summaries; MDE uses 40 unique tasks.` |
| `All diagnostic slices are confirmatory.` | violates confirmatory/exploratory separation and multiplicity policy | `Only predeclared slices within the task-budget limit are confirmatory; others are exploratory.` |
| `Public logs prove private deployment performance.` | public logs are priors, not external validity proof | `Public logs calibrate planning assumptions; private deployment needs its own scoped benchmark.` |
| `The leaderboard ranking is final.` | ranks are sample-dependent and unstable without post-run uncertainty | `The leaderboard is scoped and should be read with rank-stability intervals or top-k retention.` |
| `The regression passed, so the new model is better.` | non-inferiority is one-sided and margin-bound | `The result can support not-worse-than-margin, not superiority, unless a separate superiority test is planned.` |
| `No missingness was mentioned, so missingness is zero.` | absence of prior is not evidence | `No missingness prior was supplied; outcomes must use explicit null with reason.` |
| `The advisor says this is allowed.` | hides deterministic basis | `The plan meets rule ids {rule_ids} under the stated assumptions.` |

## DynamicMCPBench Examples

### Pairwise finance approved

```text
Allowed: agent-a and agent-b can be compared on short finance workflows using
paired task-level outcomes. The claim is limited to this planned finance task
distribution and server scope.

Not allowed: agent-a is universally better across all MCP workflows.

Repair if weak: Set task_budget to at least 200 for a stronger medium-effect
alternative, or accept the larger detectable effect shown in the MDE panel.
```

### Leaderboard warning

```text
Allowed: show an exploratory leaderboard for the four candidate agents with
rank-stability caveats.

Not allowed: exact final top-1 claim or pairwise superiority for every model
pair.

Repair: Increase task_budget to 300 or add a predeclared pairwise family with a
Holm-style multiplicity policy.
```

### Regression missing margin

```text
Issue: Regression planning needs a predeclared non-inferiority margin.

Reason: Choosing the margin after seeing outcomes would make the claim
post-hoc.

Repair: Set target_detectable_effect_pp to the maximum acceptable regression,
for example 20.0pp, before evaluation.
```

### Same-name diagnostic

```text
Allowed: describe same-name / hard-negative finance tool confusion as an
exploratory diagnostic slice.

Not allowed: choose the best overall model from this diagnostic-only slice.

Repair if pressure is missing: Set same_name_fraction >= 0.25 or
near_miss_fraction >= 0.25, depending on the claimed pressure.
```

## Final Decision

Use these templates as the controlled BA5.4 wording layer. The engine may fill
placeholders from `AdvisorDesign`, `PowerAnalysis`, `AssumptionLedger`,
`StatisticalIssue`, and `ClaimCard`, but it should not generate open-ended claim
language that bypasses the deterministic rule gate.
