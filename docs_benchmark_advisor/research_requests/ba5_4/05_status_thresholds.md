# Card 05 - Status Thresholds For BA5.4

Status: answered implementation contract.

Scope: deterministic approval, warning, refusal, and clarification thresholds
for the BA5.4 Statistical Engine. These thresholds turn mode-specific planning
diagnostics into `StatisticalIssue` objects and response status.

## Executive Recommendation

Preserve current BA5.1-BA5.3 validator thresholds as the compatibility baseline.
Add BA5.4 thresholds only where the current contract has no rule: rank
resolution caveats, diagnostic overclaim, per-slice coverage, missingness rate,
floor/ceiling risk, and repeated-attempt misuse.

Status precedence remains:

```text
refused > needs_clarification > warning > approved
```

Any `StatisticalIssue.severity == "critical"` makes the v2 engine decision
`refused`. Any warning issue makes it `warning` unless a critical issue exists.

## Threshold Classification Matrix

| Family | Decision | Classification |
|---|---|---|
| Unique task budget bands | Keep current `BUDGET_BANDS` | preserves current threshold |
| Target effect vs planned MDE | Keep `target < planned_mde` warning and `target < 0.75 * planned_mde` refusal | preserves current threshold |
| Coverage thresholds | Keep `cross_server`, `long_chain`, `recovery` thresholds | preserves current threshold |
| Distractor pressure | Keep `>= 0.25` approved, `0.10..0.249` warning, `< 0.10` refused when claimed | preserves current threshold |
| Confirmatory slices | Keep `max(1, task_budget // 40)` and `2x` refusal rule | preserves current threshold |
| Diagnostic slices | Keep `max(1, task_budget // 25)` warning rule | preserves current threshold |
| pass@3 attempts | Keep current `>=3` approved, `2` warning, `<2` refusal for confirmatory | preserves current threshold |
| Regression missing margin | Keep critical `missing_non_inferiority_margin` | preserves current v2 threshold |
| Leaderboard rank resolution | Add rank-resolution warning language around current budget bands | new BA5.4 threshold |
| Diagnostic overclaim | Add explicit v2 issue code for diagnostic-only broad selection claims | new BA5.4 threshold |
| Per-slice undercoverage | Add per-slice count checks based on `20`, `25`, `40` task targets | new BA5.4 threshold |
| Missingness | Add typed expected-missingness thresholds once input exists | new BA5.4 threshold |
| Floor/ceiling | Add prior-based warning/refusal conditions | new BA5.4 threshold |
| Attempts used as iid N | Add explicit critical/warning issue depending on claim impact | new BA5.4 threshold |

## Underpowered MDE / Effect Target

Apply this rule to pairwise target effects, regression non-inferiority margins,
and any explicitly powered confirmatory diagnostic delta. Do not apply it to
default exploratory diagnostics or plain leaderboard display unless a specific
effect target is declared.

| Condition | Approved | Warning | Refused | Repair action |
|---|---|---|---|---|
| requested effect vs planned MDE | `target_detectable_effect_pp >= planned_mde_pp` | `0.75 * planned_mde_pp <= target_detectable_effect_pp < planned_mde_pp` | `target_detectable_effect_pp < 0.75 * planned_mde_pp` | Increase `task_budget` to `required_tasks_for_mde(target)`, accept `target_detectable_effect_pp = planned_mde_pp`, narrow claim, or downgrade to smoke/exploratory |

Implementation:

```python
if target < 0.75 * planned_mde:
    critical("insufficient_budget")
elif target < planned_mde:
    warning("underpowered_design")
else:
    approved
```

Classification: preserves current threshold.

Guide/source anchors: `G4.mde.underpowered`, `G4.mde.heuristic`,
`G4.mde.two_proportion_planning`; `Colas2018`, `Henderson2018`, `Brown2001`,
`ProjectInterfaces2026`.

## Unique Task Budget

Attempts per task never repair low unique-task budget for model-selection,
leaderboard, regression, or confirmatory diagnostic power.

| Mode | Approved | Warning | Refused | Smoke-only condition |
|---|---:|---:|---:|---|
| `pairwise` | `task_budget >= 100` | `60..99` | `< 60` | if claim scope is downgraded to `smoke_test_only`, tiny budgets may return warning/export with no confirmatory claim |
| `leaderboard` | `task_budget >= 150` | `80..149` | `< 80` | low-budget leaderboard can be exploratory only if claim card forbids rank superiority |
| `regression` | `task_budget >= 60` | `30..59` | `< 30` | low-budget regression can be a smoke regression check only without non-inferiority claim |
| `diagnostic` | `task_budget >= 40` | `20..39` | `< 20` | low-budget diagnostic can be smoke/exploratory only if no confirmatory slice is claimed |

Classification: preserves current threshold.

Repair actions:

- set `task_budget` to the mode approved floor;
- or set `claim_scope = "smoke_test_only"` and rewrite claim card;
- or narrow the claim to the slice actually covered.

## Repeated Attempts Misuse

| Condition | Status | Repair action | Claim impact |
|---|---|---|---|
| attempts are used as iid tasks in MDE/CI formula or rationale | `refused` for confirmatory claims; `warning` for exploratory outputs | Recompute with `task_budget` unique tasks; keep attempts only for reliability/pass@k fields | No confirmatory claim until nominal N is corrected |
| `pass_at_3` requested with `attempts_per_task >= 3` | `approved` if other checks pass | none | pass@3/reliability claim allowed within scope |
| `pass_at_3` requested with `attempts_per_task == 2` | `warning` with existing `too_few_repeats` | Set `attempts_per_task = 3` or change metric to single-run effect pass | Reliability claim is weak |
| `pass_at_3` requested with `attempts_per_task < 2` | `refused` for confirmatory scopes; `warning` for non-confirmatory scopes | Set `attempts_per_task = 3` or remove pass@3 claim | Confirmatory pass@3 claim not allowed |
| `attempts_per_task > 1` without reliability/pass@k claim | no downgrade; assumption note | State attempts do not increase iid power | Model-selection claim still depends on unique tasks |

Issue code:

- existing: `too_few_repeats`;
- new v2: `attempts_not_independent_tasks` for formulas/rationale that multiply
  tasks by attempts.

Guide/source anchors: `G4.repeats.not_independent_tasks`, `G4.repeats.pass3`,
`G2.metric.pass3`; `TauBench2024`, `HumanEval2021`, `SurveyDesignEffect`.

## Leaderboard Rank Stability

Leaderboard status has two layers:

1. Current hard eligibility: model count and task-budget bands.
2. BA5.4 rank-resolution caveat: whether the plan is only exploratory or a
   stronger rank-stability candidate.

| Condition | Approved | Warning | Refused | Repair action |
|---|---|---|---|---|
| model count | `len(candidate_models) >= 3` | not applicable | `< 3` with `unsupported_candidate_model_count` | Add at least 3 candidate models or switch to `pairwise` |
| unique task budget | `>= 150` | `80..149` | `< 80` | Increase `task_budget` to `150`, or `300/500` for stronger rank stability |
| rank-resolution proxy | `rank_resolution_pp <= target_gap_pp` when a target gap is supplied; otherwise approved budget carries caveat | `rank_resolution_pp > target_gap_pp` or no target gap and budget `< 300` | no refusal solely from no-prior rank proxy if budget/model count pass | Add empirical prior, increase budget, or narrow to display-only leaderboard |
| pairwise superiority claims inside leaderboard | allowed only with predeclared pairwise family and multiplicity policy | warning if vague pairwise language appears without family | refused if claim card asserts pairwise superiority with no multiplicity/targets | Split into pairwise tests or add Holm-style plan |
| top-k claim | top-k display with caveat when `task_budget >= 150`; stronger at `>= 300` | top-k claim is exploratory at `80..149` | exact final top-k proof refused without post-run bootstrap | Increase budget and require bootstrap top-k retention in post-run report |

New v2 codes:

- `rank_stability_uncertain`: warning for point-rank-only or low-budget
  leaderboard caveat.
- `missing_multiplicity_policy`: warning or critical depending on whether a
  confirmatory pairwise family is claimed.

Guide/source anchors: `G1.leaderboard.ranking`, `G2.metric.rank_stability`,
`G5.criterion.rank_stability`, `G5.multiple.holm_confirmatory`;
`BenchmarkLottery2021`, `HELM2022`, `Efron1979`, `Holm1979`.

## Regression / Non-Inferiority

| Condition | Status | Repair action | Allowed claim |
|---|---|---|---|
| missing margin | `refused` with `missing_non_inferiority_margin` | Set `target_detectable_effect_pp` as the predeclared non-inferiority margin | No non-inferiority claim |
| margin `>= planned_mde_pp` | `approved` if other checks pass | none | Candidate is not worse than baseline by more than margin on fixed slice, after post-run analysis |
| `0.75 * planned_mde_pp <= margin < planned_mde_pp` | `warning` with `underpowered_design` | Increase budget or choose a defensible larger margin before evaluation | Weak non-inferiority planning claim only |
| `margin < 0.75 * planned_mde_pp` | `refused` with `insufficient_budget` | Increase budget to support the margin or downgrade to smoke regression check | No confirmatory non-inferiority claim |
| post-hoc margin suspected from edits | `refused` with new `post_hoc_margin_not_allowed` | Restore predeclared margin or mark result exploratory | No confirmatory non-inferiority claim |
| wrong candidate count when models supplied | `refused` with `unsupported_candidate_model_count` | Provide baseline and candidate model only | No regression comparison claim |

Classification:

- missing margin preserves current v2 threshold;
- margin/MDE ratio preserves current threshold;
- post-hoc margin and regression candidate-count checks are new BA5.4
  thresholds.

Guide/source anchors: `G1.regression.non_inferiority`,
`G2.metric.non_inferiority`, `G5.criterion.non_inferiority`; `CONSORT2010`,
`Colas2018`, `Dror2018`.

## Diagnostic Overclaim

| Condition | Approved | Warning | Refused | Repair action |
|---|---|---|---|---|
| diagnostic-only broad model-selection claim | never approved as broad selection | warning if claim card clearly narrows to diagnostic slice | refused with `diagnostic_overclaim` if it asks "best overall" or model selection from only diagnostic slice | Add representative task distribution and pairwise/leaderboard mode, or narrow claim to diagnostic finding |
| exploratory named slice per-slice tasks | `>= 25` preferred | `20..24` or wide CI caveat | `< 20` if slice is central to requested claim | Increase slice ratio/task budget or drop low-priority slice |
| confirmatory diagnostic slice | `slice_task_count >= 40` and within confirmatory slice limit | `20..39` with `insufficient_slice_coverage` | `< 20` or exceeds `2 * max_confirmatory_slices` for confirmatory claims | Increase budget, reduce confirmatory slices, or mark slice exploratory |
| too many confirmatory slices | within `max(1, task_budget // 40)` | exceeds limit | exceeds `2 * limit` for confirmatory scopes | Move extra slices to exploratory or increase budget |
| missing hard-negative pressure | distractor pressure `>= 0.25` | `0.10..0.249` | `< 0.10` when claimed | Set `near_miss_fraction >= 0.25` and include diagnostic slice |
| missing same-name pressure | same-name pressure `>= 0.25` | `0.10..0.249` | `< 0.10` when claimed | Set `same_name_fraction >= 0.25` and include same-name slice |

Issue codes:

- existing compatible: `cannot_support_claim`, `too_many_secondary_slices`;
- new v2: `diagnostic_overclaim`, `insufficient_slice_coverage`,
  `missing_diagnostic_pressure`.

Guide/source anchors: `G1.diagnostic.slice`, `G2.metric.diagnostic_slice`,
`G3.distractor.claim_requires_pressure`, `G5.criterion.descriptive_diagnostic`,
`G6.claim.diagnostic_not_selection`; `CheckList2020`, `Dynabench2021`,
`ToolSandbox2024`, `Raji2021`.

## Multiplicity

| Condition | Status | Required policy | Repair action |
|---|---|---|---|
| one primary comparison | `approved` if other checks pass | state "single primary criterion" | none |
| multiple confirmatory slices within budget | `warning` unless Holm-style policy is present | Holm-style family-wise control or equivalent | Add multiplicity policy or mark extras exploratory |
| many diagnostics | `warning` if significance language is used; otherwise note | BH/FDR-style or descriptive-only reporting | Use descriptive diagnostics or add FDR policy |
| no multiplicity policy in `AssumptionLedger` | `refused` with `missing_multiplicity_policy` because schema/engine output is incomplete | non-empty `multiplicity_policy` | Fill assumption ledger |
| user wants all slices confirmatory | warning/refusal by slice limit | limit confirmatory family by `task_budget // 40` | Move low-priority slices to exploratory |

BA5.4 can enforce policy text immediately because `AssumptionLedger` already has
`multiplicity_policy`.

Guide/source anchors: `G5.multiple.primary_vs_exploratory`,
`G5.multiple.holm_confirmatory`, `G5.multiple.bh_diagnostic`,
`G6.claim.confirmatory_vs_exploratory`; `Dror2017`, `Holm1979`, `BH1995`.

## Missingness

The missingness rate thresholds require a typed expected-missingness input. Until
that field exists, only enforce that `AssumptionLedger.missingness_policy` is
present and non-empty.

| Missingness condition | Status | Claim impact | Repair action |
|---|---|---|---|
| explicit policy present | no downgrade | claims may proceed if other checks pass | none |
| missing policy absent | `refused` with `missingness_policy_required` | no exportable plan because assumptions are incomplete | Fill `AssumptionLedger.missingness_policy` |
| no expected rate supplied | info note only | do not claim zero missingness risk | ask for expected missingness only if claim is sensitive |
| expected `< 0.05` | no downgrade | confirmatory claims allowed if other checks pass | record explicit-null policy |
| expected `0.05..0.15` | `warning` for confirmatory claims | confirmatory claim carries missingness caveat | increase budget, add missingness handling, or narrow claim |
| expected `0.15..0.20` | `warning`; may become critical for narrow-margin claims in Card 04/05 formula composition | weak confirmatory claim | reduce missingness risk or increase budget |
| expected `> 0.20` | `refused` for confirmatory pairwise/leaderboard/regression; `warning` for exploratory diagnostic | no confirmatory claim | reduce missingness risk or downgrade to exploratory diagnostic |

New v2 codes:

- `missingness_policy_required`;
- `expected_missingness_warning`;
- `expected_missingness_too_high`.

Guide/source anchors: `G7.doc.parameter_status_label`,
`G6.claim.confirmatory_vs_exploratory`; `Datasheets2018`, `ModelCards2019`,
`DataCards2022`.

## Floor / Ceiling Risk

| Baseline/pass-rate condition | Status | Caveat | Repair action |
|---|---|---|---|
| no prior baseline supplied | no downgrade | use `0.2 / 0.5 / 0.8` sensitivity notes | inspect sensitivity before launch |
| prior `0.10..0.90` | no floor/ceiling issue | ordinary baseline caveat | none |
| near floor `< 0.10` | `warning` with `floor_ceiling_risk` | primary metric may be too hard to discriminate useful differences | rebalance task difficulty, add easier slice, or frame as diagnostic |
| near ceiling `> 0.90` | `warning` with `floor_ceiling_risk` | primary metric may be too easy to discriminate useful differences | rebalance task difficulty, add harder slice, or frame as diagnostic |
| saturated prior `<= 0.05` or `>= 0.95` and requested small confirmatory effect | `refused` if requested delta is not plausible within metric bounds; otherwise warning | MDE/CI planning is dominated by saturation | rebalance benchmark difficulty before model-selection claim |

New v2 code: `floor_ceiling_risk`.

Guide/source anchors: `G2.metric.floor_ceiling_sensitivity`,
`G4.floor_ceiling.power_warning`, `G6.warning.floor_ceiling`; `BowmanDahl2021`,
`Bragg2021`, `Northcutt2021`.

## Issue Code Recommendations

| Issue family | Proposed code | Severity | failed_field | failed_criterion_id | Status in current code |
|---|---|---|---|---|---|
| underpowered target | `underpowered_design` | `warning` | `target_detectable_effect_pp` | `criterion.primary` | existing v1 warning |
| target far below MDE | `insufficient_budget` | `critical` | `task_budget` or `target_detectable_effect_pp` | `criterion.primary` | existing v1 refusal |
| mode budget below floor | `insufficient_budget` | `critical` | `task_budget` | `criterion.primary` | existing v1 refusal |
| pass@3 too few repeats | `too_few_repeats` | `warning` or `critical` through refusal wrapper | `attempts_per_task` | `criterion.primary` | existing v1 warning / refusal behavior |
| attempts used as iid | `attempts_not_independent_tasks` | `critical` for confirmatory, `warning` otherwise | `attempts_per_task` | `criterion.primary` | new v2 code |
| wrong candidate count | `unsupported_candidate_model_count` | `critical` | `candidate_models` | `criterion.primary` | existing v2 code |
| missing regression margin | `missing_non_inferiority_margin` | `critical` | `target_detectable_effect_pp` | `criterion.primary` | existing v2 code |
| post-hoc margin | `post_hoc_margin_not_allowed` | `critical` | `target_detectable_effect_pp` | `criterion.primary` | new v2 code |
| rank instability | `rank_stability_uncertain` | `warning` | `task_budget` | `criterion.primary` | new v2 code |
| missing multiplicity | `missing_multiplicity_policy` | `warning` or `critical` if ledger absent | `assumption_ledger.multiplicity_policy` | `criterion.primary` | new v2 code |
| diagnostic overclaim | `diagnostic_overclaim` | `critical` | `claim_scope` | `criterion.primary` | new v2 code |
| insufficient slice coverage | `insufficient_slice_coverage` | `warning` or `critical` | `task_distribution.diagnostic_slices` | `criterion.primary` | new v2 code |
| too many slices | `too_many_secondary_slices` | `warning` | `task_distribution.diagnostic_slices` | `criterion.primary` | existing v1 warning |
| missing diagnostic pressure | `missing_diagnostic_pressure` | `warning` or `critical` | `task_distribution.distractors` | `criterion.primary` | new v2 code |
| missingness policy absent | `missingness_policy_required` | `critical` | `assumption_ledger.missingness_policy` | `criterion.primary` | new v2 code |
| moderate missingness | `expected_missingness_warning` | `warning` | `expected_missingness_rate` | `criterion.primary` | new v2 code |
| high missingness | `expected_missingness_too_high` | `critical` for confirmatory | `expected_missingness_rate` | `criterion.primary` | new v2 code |
| floor/ceiling | `floor_ceiling_risk` | `warning` or `critical` if impossible target | `assumption_ledger.baseline_rate` | `criterion.primary` | new v2 code |

## Repair Action Mapping

| Problem | Concrete repair |
|---|---|
| underpowered MDE | Set `task_budget >= required_tasks_for_mde(target_detectable_effect_pp)` or set `target_detectable_effect_pp = planned_mde_pp` |
| low budget | Set `task_budget` to the approved floor for the mode or set `claim_scope = "smoke_test_only"` |
| attempts misuse | Recompute MDE/CI from unique `task_budget`; keep attempts only for reliability/pass@k |
| pass@3 too few repeats | Set `attempts_per_task = 3` or change primary metric away from `pass_at_3` |
| leaderboard too few models | Add candidates until `len(candidate_models) >= 3` or switch to `pairwise` |
| regression missing margin | Set `target_detectable_effect_pp` before evaluation |
| diagnostic overclaim | Change mode to `pairwise`/`leaderboard` with representative distribution, or narrow claim to diagnostic slice |
| undercovered diagnostic slice | Increase `task_budget`, increase slice ratio, or remove confirmatory flag |
| missing hard-negative pressure | Set `task_distribution.distractors.near_miss_fraction >= 0.25` |
| missing same-name pressure | Set `task_distribution.distractors.same_name_fraction >= 0.25` |
| missing multiplicity | Fill `multiplicity_policy` with Holm for confirmatory family or BH/descriptive-only for diagnostics |
| high missingness | Reduce expected missingness, increase budget with explicit missingness model, or downgrade to exploratory |
| floor/ceiling | Rebalance task difficulty or choose a diagnostic/coverage claim instead of small-effect selection |

## Claims Allowed By Status

| Status | Allowed claims | Not allowed |
|---|---|---|
| `approved` | scoped claim shown in `ClaimCard.allowed_claims` under stated task distribution, method, assumptions, and caveats | universal best model, private-deployment guarantee, post-run proof before outcomes |
| `warning` | narrowed/scoped claim with warning caveat, or exploratory/display claim | unqualified confirmatory language; hiding warning from export/UI |
| `refused` | no confirmatory claim until critical repairs are made; optional diagnostic/smoke alternative may be shown if explicitly marked | export/launch as confirmatory benchmark; model selection; universal ranking |
| `needs_clarification` | no statistical claim; ask for missing primary objective or candidate set | inventing missing candidates/mode/margin |

## Proposed Unit Tests

Add tests for:

- all current `BUDGET_BANDS` remain unchanged;
- target/MDE warning/refusal ratios preserve current behavior;
- attempts do not multiply iid N and misuse emits `attempts_not_independent_tasks`;
- pass@3 attempt thresholds preserve current behavior;
- leaderboard `<3` candidates refuses with `unsupported_candidate_model_count`;
- leaderboard warning band emits `rank_stability_uncertain` or equivalent caveat;
- regression missing margin refuses with `missing_non_inferiority_margin`;
- regression margin below MDE warns/refuses by the ratio table;
- diagnostic-only broad model-selection claim emits `diagnostic_overclaim`;
- same-name/hard-negative intent without pressure emits `missing_diagnostic_pressure`;
- confirmatory slice count uses `task_budget // 40` and `2x` refusal rule;
- diagnostic slice count uses `task_budget // 25`;
- `AssumptionLedger.multiplicity_policy` and `missingness_policy` are always non-empty;
- expected missingness thresholds are enforced only after typed input exists;
- floor/ceiling prior rates emit `floor_ceiling_risk`;
- all warning/refusal issues include concrete repair options;
- local guide references use known rule ids.

## Final Decision

BA5.4 should be stricter about overclaims, not stricter about ordinary entry
budgets. Preserve current floors, then add issue cards and repair actions for
the statistical risks that current BA5.3 only mentions indirectly.
