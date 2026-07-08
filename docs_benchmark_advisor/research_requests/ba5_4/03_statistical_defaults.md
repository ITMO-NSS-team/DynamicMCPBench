# Card 03 - Statistical Defaults For BA5.4

Status: answered implementation contract.

Scope: deterministic no-prior defaults for the BA5.4 Statistical Engine. These
defaults are planning assumptions for pre-run benchmark design. They are not
post-run inferential guarantees and must be surfaced in `AssumptionLedger`,
`PowerAnalysis`, `EngineComputationTrace`, issue cards, and UI caveats.

## Executive Recommendation

Preserve the current BA5.1-BA5.3 status thresholds and default statistical
conventions. Add BA5.4 sensitivity branches, floor/ceiling warnings,
missingness-rate policy, and effective-sample-size caveats as engine outputs,
not as silent replacements for existing validator behavior.

This is the best default for a broad-user benchmark-design advisor: small
practical studies can still receive an honest warning or narrowed claim, while
the advisor shows stronger alternatives for users who need medium-effect or
rank-stable claims.

| Area | BA5.4 decision | Compatibility impact |
|---|---|---|
| Baseline fallback | Keep `baseline_rate = 0.5` | Preserves current `stats.py` and `v2_engine.py` |
| Sensitivity branches | Add `0.2 / 0.5 / 0.8` | New notes and typed planning diagnostics; no current schema break |
| Floor/ceiling warning | Add warning band `< 0.10` or `> 0.90` | New v2 `StatisticalIssue.code`, not v1 enum |
| `alpha` | Keep `0.05` | Preserves request/schema default |
| `beta` / target power | Keep `beta = 0.20`, `target_power = 0.80` | Preserves request default; `PowerAnalysis.target_power` stores `1 - beta` |
| Budget bands | Keep current `BUDGET_BANDS` | Larger values become alternatives, not hard floors |
| Coverage thresholds | Keep current `COVERAGE_THRESHOLDS` | No migration |
| Distractor pressure | Keep `approved >= 0.25`, `warning >= 0.10` | No migration |
| Confirmatory slices | Keep `max(1, task_budget // 40)` for status | Do not migrate to `/25` silently |
| Diagnostic slices | Keep `max(1, task_budget // 25)` for warnings | No migration |
| Repeated attempts | Never multiply iid N by attempts | Preserves guide and engine assumptions |
| Numeric design effect | No default status penalty without calibrated logs | Add caveat and optional sensitivity branch |
| Missingness policy | Keep `explicit_null_with_reason before post-run reporting` | Add rate thresholds only when an explicit numeric expected-missingness value is supplied |

## Source Anchors

Use local guide rule ids and source keys, not unresolved citation numbers.

| Default family | Guide rule ids | Source keys |
|---|---|---|
| Budget and MDE planning | `G4.budget.mode_thresholds`, `G4.mde.heuristic`, `G4.mde.underpowered`, `G4.mde.two_proportion_planning` | `Colas2018`, `Henderson2018`, `Brown2001`, `Bragg2021`, `DynamicMCPBench2026` |
| Repeated attempts and dependence | `G4.repeats.not_independent_tasks`, `G4.clustered_tasks.neff_caveat` | `TauBench2024`, `Colas2018`, `SurveyDesignEffect`, `Efron1979` |
| Wilson precision | `G5.criterion.wilson_planning` | `Brown2001` |
| Pairwise and paired comparisons | `G5.criterion.paired_bootstrap`, `G5.criterion.paired_default`, `G5.criterion.randomization_fallback` | `Efron1979`, `Dror2018`, `Yeh2000` |
| Leaderboard instability | `G1.leaderboard.ranking`, `G2.metric.rank_stability`, `G5.criterion.rank_stability` | `BenchmarkLottery2021`, `HELM2022`, `Efron1979`, `Ethayarajh2020` |
| Diagnostic slices | `G1.diagnostic.slice`, `G2.metric.diagnostic_slice`, `G5.criterion.descriptive_diagnostic` | `CheckList2020`, `Dynabench2021`, `ToolSandbox2024`, `Raji2021` |
| Multiplicity and confirmatory slices | `G4.slices.limit`, `G5.multiple.primary_vs_exploratory`, `G5.multiple.holm_confirmatory`, `G5.multiple.bh_diagnostic` | `Dror2017`, `Holm1979`, `BH1995` |
| Floor/ceiling risk | `G2.metric.floor_ceiling_sensitivity`, `G4.floor_ceiling.power_warning`, `G6.warning.floor_ceiling` | `BowmanDahl2021`, `Bragg2021`, `Northcutt2021` |
| Documentation and caveats | `G6.claim.private_transfer_limit`, `G7.doc.parameter_status_label` | `Datasheets2018`, `ModelCards2019`, `DataCards2022`, `Raji2021` |

## Baseline Rate Defaults

Keep `0.5` as the central fallback because it maximizes binomial variance and
therefore gives a conservative no-prior CI/MDE planning curve for binary success
metrics. The engine must label this as a planning assumption, not as evidence
about the user's private workload.

Use `0.2 / 0.5 / 0.8` rather than narrower branches. `0.3 / 0.5 / 0.7` is less
useful for MCP-agent planning because it hides near-saturation behavior that is
common in too-easy or too-hard benchmark slices. `0.2 / 0.8` are still moderate
stress branches, not extreme floor/ceiling priors.

| Field | Recommended value | Rationale | Source | Implementation note |
|---|---:|---|---|---|
| `default_baseline_rate` | `0.5` | Conservative no-prior variance for binary planning | `G4.mde.two_proportion_planning`; `Brown2001`; `Colas2018` | Store in `AssumptionLedger.baseline_rate` |
| `sensitivity_low` | `0.2` | Tests low-pass-rate behavior without assuming complete floor saturation | `G4.floor_ceiling.power_warning`; `BowmanDahl2021` | Emit in `AssumptionLedger.sensitivity_notes` and `PowerAnalysis.planning_diagnostics` |
| `sensitivity_medium` | `0.5` | Central fallback and maximum-variance branch | `G4.mde.two_proportion_planning`; `Brown2001` | Same |
| `sensitivity_high` | `0.8` | Tests high-pass-rate behavior without assuming complete ceiling saturation | `G4.floor_ceiling.power_warning`; `Bragg2021` | Same |
| `floor_ceiling_warning_band` | `< 0.10` or `> 0.90` | Near-floor/near-ceiling rates make small deltas hard to interpret | `G2.metric.floor_ceiling_sensitivity`; `G6.warning.floor_ceiling` | Add v2 issue `floor_ceiling_risk` when a supplied prior or selected sensitivity branch is in this band |

Policy:

- If no prior exists, do not emit `floor_ceiling_risk` solely because the engine
  has sensitivity branches.
- If a pilot/public prior or user override gives `baseline_rate < 0.10` or
  `> 0.90`, emit warning `floor_ceiling_risk`.
- If the requested detectable effect is physically implausible under the
  assumed direction, for example a 15pp improvement from a `0.90` baseline,
  Card 05 should classify the exact status. Card 03 only defines the default
  warning band.

## Alpha, Power, And Planning Confidence

Keep the familiar planning convention `alpha = 0.05`, `beta = 0.20`, and
`target_power = 0.80` for confirmatory planning. These values are conventions
for budget planning, not guarantees. The wording must always say
`planning_heuristic` unless the curve is calibrated from local empirical priors,
in which case it must say `empirical_prior`.

Diagnostics and leaderboards should not imply that a generic `0.80` target power
proves final rank stability. For those modes, the schema fields may still store
the request defaults, but the user-facing label must be rank-stability proxy or
descriptive precision unless a specific confirmatory family is predeclared.

| Mode | alpha default | target power default | planning label | caveat |
|---|---:|---:|---|---|
| `pairwise` | `0.05` | `0.80` | `planning_heuristic` for no-prior MDE; `empirical_prior` only with calibrated paired logs | Same-task comparisons should use paired task-level post-run methods; no-prior MDE is approximate |
| `leaderboard` | `0.05` only for explicit confirmatory pairwise families | `0.80` only for those families | `rank_stability_proxy` for default leaderboard planning | Point ranks are not confirmatory superiority claims; top-k/rank-stability remains proxy before outcomes |
| `regression` | `0.05` | `0.80` | `planning_heuristic` for non-inferiority margin planning | Margin must be predeclared; do not infer superiority from non-inferiority |
| `diagnostic` | `0.05` only for predeclared confirmatory diagnostic tests | no default power claim for exploratory diagnostics | `descriptive_precision` | Default diagnostic slices are exploratory and should use CI width / per-slice coverage |

Implementation:

- `AdvisorV2DesignRequest.alpha` remains `0.05`.
- `AdvisorV2DesignRequest.beta` remains `0.20`.
- `Criterion.beta_or_target_power` and `PowerAnalysis.target_power` should store
  `1.0 - beta`, currently `0.80`.
- `AnalysisPlan.heuristic_label` stays `planning_heuristic`.
- UI text must not say "80% chance this benchmark will prove the claim"; it
  should say "planned around 80% power under stated assumptions".

## Budget Grid And Task Counts

Keep the current validator floors as compatibility status thresholds. Use
larger budgets as recommended alternatives, stronger alternatives, or split
warnings. This preserves broad usability while still showing when a request only
supports a large-effect or exploratory claim.

`task_budget` means unique benchmark tasks / TaskSpecs. It does not mean model
calls and does not become `task_budget * attempts_per_task`.

| Mode | refused below | warning band | first approved budget | stronger budget | cap |
|---|---:|---:|---:|---:|---:|
| `pairwise` | `60` | `60..99` | `100` | `200`, `500` | hard search cap `5000`; split/expense warning above `2000` |
| `leaderboard` | `80` | `80..149` | `150` | `300`, `500`, `800` | hard search cap `5000`; split/expense warning above `2000` unless explicitly broad |
| `regression` | `30` | `30..59` | `60` | `120`, `240`, `500` | hard search cap `5000`; split/expense warning above `2000` |
| `diagnostic` | `20` | `20..39` | `40` | `100`, `200` | hard search cap `5000`; focused diagnostic split warning above `500` |

Search-grid policy:

- Preserve the current grid seeds:
  - requested `task_budget`;
  - mode warning floor;
  - mode approved floor;
  - `max(approved_floor, request.task_budget * 2)`;
  - `max(approved_floor + 20, round(approved_floor * 1.5))`;
  - `required_tasks_for_mde(target_detectable_effect_pp)` when a target exists;
  - clamp to `1..5000`.
- Add the stronger budgets above as BA5.4 grid candidates when they are not
  already present.
- Do not make stronger budgets hard refusal thresholds.
- `BudgetAlternative.claim_status` should distinguish:
  - first approved current-threshold design;
  - medium-effect stronger design;
  - narrowed-claim design near the requested budget;
  - smoke/exploratory design when below warning floor.

Why these larger budgets are alternatives rather than floors:

- Around `baseline_rate = 0.5`, `100` paired unique tasks gives only a rough
  large-effect planning design, while `200..500` starts to support more useful
  medium-effect planning.
- Requiring `200..500` as the first approved floor would cause many practical
  users to receive refusals instead of a useful warning plus repair path.
- The advisor's goal is not to block all weak requests. It is to label what the
  current budget buys and show the field edits that would support stronger
  claims.

## Confirmatory Slice Defaults

Keep the current status rule:

```text
max_confirmatory_slices = max(1, task_budget // 40)
max_diagnostic_slices = max(1, task_budget // 25)
```

Do not replace `// 40` with `// 25` for confirmatory status logic. `// 25` is
reasonable for exploratory diagnostic coverage, but confirmatory slices need a
smaller family and more tasks per slice because they create multiplicity and
claim-boundary pressure.

| Rule | Recommended value | Reason | Repair action when exceeded |
|---|---:|---|---|
| `min_tasks_per_confirmatory_slice` | `40` unique tasks as the planning target | Matches current confirmatory slice status rule and supports a conservative family size | Move lowest-priority slices to exploratory or increase `task_budget` |
| `confirmatory_slice_limit_formula` | `max(1, task_budget // 40)` | Preserves `INTERFACES.md` and `validator.py` behavior | Keep only the primary claim slice confirmatory by default |
| `diagnostic_slice_default_status` | exploratory | Diagnostic failure-mode slices are useful but should not become confirmatory automatically | Mark extra slices `confirmatory = false`; add multiplicity plan only for predeclared confirmatory families |

Slice prioritization:

1. Preserve slices explicitly named in the user's primary question.
2. Preserve slices required by the claim boundary, for example cross-server for
   cross-server claims or recovery for recovery claims.
3. Preserve generator-pressure slices that make the diagnostic real, for
   example same-name / near-miss / hard-negative pressure for wrong-tool claims.
4. Demote remaining interesting slices to exploratory diagnostics.

## Cluster And Design-Effect Caveats

The default no-prior policy is qualitative caveat plus sensitivity, not a hidden
numeric penalty. A numeric design-effect penalty should be applied only from
calibrated local logs or explicitly supplied priors. Otherwise the advisor would
invent precision it does not have.

| Situation | Default policy | Numeric penalty? | Caveat text | Test expectation |
|---|---|---|---|---|
| repeated attempts | Attempts support reliability/pass@k diagnostics but do not multiply iid task count | No | `attempts can support reliability metrics but do not multiply unique-task power` | Increasing `attempts_per_task` alone must not reduce `planned_mde_pp` |
| shared templates | Treat unique template diversity as a design caveat | No default status penalty | `shared templates may reduce effective sample size; diversify templates or use cluster-aware analysis when logs exist` | Caveat appears when template families are declared or inferred |
| same server/tool cluster | Treat server/tool concentration as a cluster caveat and coverage issue when claimed | No default design-effect penalty | `same-server or same-tool clusters may make n_eff smaller than unique task count` | Caveat appears; coverage thresholds still use current `COVERAGE_THRESHOLDS` |
| no prior logs | Use `n_eff <= unique_tasks` and no-prior sensitivity notes | No | `no calibrated cluster prior is available; MDE and CI width are planning heuristics` | `empirical_prior_sources` remains empty and formula labels remain deterministic |

Allowed optional sensitivity branch:

```text
n_eff_stress = floor(0.5 * unique_tasks)
```

This branch may be shown as a non-status stress scenario, but it must not change
approval/refusal unless the engine has a calibrated design-effect prior or the
project owner explicitly promotes it to a threshold in Card 05.

## Missingness Defaults

Preserve the current policy string:

```text
explicit_null_with_reason before post-run reporting
```

Add missingness-rate thresholds only when BA5.4 has an explicit numeric
expected-missingness input. Current `AdvisorV2DesignRequest` does not have a
first-class field, so the compatibility bridge is
`user_overrides["expected_missingness_rate"]`. Until a supplied numeric value
exists, the engine should always emit the policy text but should not pretend
that "no supplied missingness prior" means zero missingness risk.

Recommended future typed field:

```python
expected_missingness_rate: float | None  # in [0, 1], optional
```

Preferred future location: `DeploymentContext` or a typed engine config object.
Avoid long-term dependence on arbitrary `user_overrides` for a status-driving
field. The BA5.4 implementation may use the override bridge because it keeps the
schema additive and preserves v2 compatibility.

| Missingness condition | Status | Repair action | Allowed claim impact |
|---|---|---|---|
| no missingness assumption supplied | `info` assumption note | Keep `explicit_null_with_reason`; ask for expected missingness only if confirmatory claim is sensitive | Do not downgrade solely for absence, but do not claim zero missingness risk |
| expected `< 5%` | no downgrade | Record policy and keep explicit missingness reasons in outcome tensor/reporting | Confirmatory claim allowed if all other checks pass |
| expected `5%..15%` | `warning` for confirmatory claims; note for exploratory diagnostics | Increase unique-task budget, reduce claim strength, or add missingness handling plan | Confirmatory claim can remain only with caveat and repair visibility |
| expected `> 20%` | `refused` for confirmatory model-selection, leaderboard, and regression claims; `warning` for diagnostic/exploratory framing | Reduce missingness risk, increase budget with explicit missingness model, or downgrade to exploratory diagnostic | No confirmatory claim; exploratory diagnostic claim may remain |

If expected missingness is `15%..20%`, use warning by default and let Card 05
decide whether narrow-margin regression or small-effect pairwise claims should
refuse earlier.

Proposed v2 issue codes:

| Issue concept | Code | Default severity | Existing? |
|---|---|---|---|
| Missingness policy absent from ledger | `missingness_policy_required` | critical | New v2 code; should not trigger if engine fills ledger correctly |
| Moderate expected missingness | `expected_missingness_warning` | warning | New v2 code |
| High expected missingness | `expected_missingness_too_high` | critical for confirmatory claims | New v2 code |

## Proposed Implementation Constants

These are the constants BA5.4 can implement without changing current validator
floors.

```python
DEFAULT_BASELINE_RATE = 0.5
BASELINE_SENSITIVITY_RATES = (0.2, 0.5, 0.8)
FLOOR_CEILING_WARNING_BAND = (0.10, 0.90)

DEFAULT_ALPHA = 0.05
DEFAULT_BETA = 0.20
DEFAULT_TARGET_POWER = 0.80

BUDGET_BANDS = {
    "pairwise": (100, 60),
    "leaderboard": (150, 80),
    "regression": (60, 30),
    "diagnostic": (40, 20),
}

STRONGER_BUDGETS = {
    "pairwise": (200, 500),
    "leaderboard": (300, 500, 800),
    "regression": (120, 240, 500),
    "diagnostic": (100, 200),
}

HARD_BUDGET_SEARCH_CAP = 5000
SOFT_SPLIT_WARNING_CAP = {
    "pairwise": 2000,
    "leaderboard": 2000,
    "regression": 2000,
    "diagnostic": 500,
}

MAX_CONFIRMATORY_SLICES = lambda task_budget: max(1, task_budget // 40)
MAX_DIAGNOSTIC_SLICES = lambda task_budget: max(1, task_budget // 25)
MIN_TASKS_PER_CONFIRMATORY_SLICE = 40
MIN_TASKS_PER_EXPLORATORY_DIAGNOSTIC_SLICE = 25

EXPECTED_MISSINGNESS_WARNING = 0.05
EXPECTED_MISSINGNESS_STRONG_WARNING = 0.15
EXPECTED_MISSINGNESS_REFUSAL = 0.20
```

## Schema And Field Mapping

| Recommendation | Current field | BA5.4 implementation mapping |
|---|---|---|
| central baseline | `AssumptionLedger.baseline_rate` | Store `0.5` unless a prior is supplied |
| low/medium/high sensitivity | `AssumptionLedger.sensitivity_notes`, `PowerAnalysis.planning_diagnostics` | Emit both readable notes and typed diagnostics for UI charts |
| alpha | `AdvisorV2DesignRequest.alpha`, `AnalysisPlan.alpha`, `Criterion.alpha`, `PowerAnalysis.alpha` | Preserve request default and copy through |
| beta / target power | `AdvisorV2DesignRequest.beta`, `Criterion.beta_or_target_power`, `PowerAnalysis.target_power` | Request stores beta; criterion/power fields store target power |
| budget alternatives | `PowerAnalysis.budget_alternatives`, `DesignAlternative` | Include current threshold alternatives plus stronger budgets |
| formula provenance | `EngineComputationTrace.formula_versions` | Include names such as `planned_mde_pp.unique_tasks.v1`, `leaderboard_rank_resolution_pp.v1`, `wilson_slice_ci_width.v1`, and `non_inferiority_margin_status.v1` |
| repeated-attempt caveat | `AssumptionLedger.repeated_attempts_policy` | Preserve existing text and add issue only when attempts are treated as iid |
| missingness policy | `AssumptionLedger.missingness_policy`, `user_overrides["expected_missingness_rate"]` bridge | Preserve policy string; enforce rate thresholds only when the explicit numeric override is supplied, then migrate to a typed field later |
| floor/ceiling caveat | `AssumptionLedger.sensitivity_notes`, `StatisticalIssue` | Add note always when priors are absent; warning issue only when a supplied rate is near floor/ceiling |

## MDE Sample-Size Interpretation

For Card 03 defaults, interpret iid planning sample size as:

```text
n_eff <= unique task_budget
```

Repeated attempts do not increase `n_eff`.

For default paired pairwise or paired regression planning, each unique task is
evaluated by both models, so the no-prior approximation may use
`n_eff = task_budget` as the conservative paired-task planning unit. Do not
divide by number of models merely because two models are evaluated on the same
tasks.

For unpaired or independently sampled arms, use per-arm sample size explicitly.
The current function name `planned_mde_pp(n_per_group)` is therefore too narrow
for BA5.4. Recommended migration:

```python
planned_mde_pp_for_unique_tasks(
    unique_tasks: int,
    baseline: float = 0.5,
    design: Literal["paired_no_prior", "unpaired_per_arm"] = "paired_no_prior",
) -> float
```

This migration belongs primarily to Card 04 formulas, but Card 03 should not
leave the old ambiguity in new defaults.

## Proposed Unit Tests

Add or preserve these tests:

- default `AssumptionLedger.baseline_rate` remains `0.5`;
- sensitivity notes mention `0.2`, `0.5`, and `0.8`;
- supplied prior `0.09` or `0.91` emits warning issue `floor_ceiling_risk`;
- request defaults remain `alpha == 0.05` and `beta == 0.20`;
- `PowerAnalysis.target_power == 0.80` when request beta is `0.20`;
- diagnostic mode labels default planning as descriptive precision, not
  confirmatory power;
- current `BUDGET_BANDS` remain unchanged;
- stronger budget alternatives are present but do not replace hard floors;
- `attempts_per_task` changes from `1` to `3` do not reduce iid
  `planned_mde_pp`;
- `task_budget * attempts_per_task` never appears as the MDE sample size;
- confirmatory slice warning logic still uses `task_budget // 40`;
- diagnostic slice warning logic still uses `task_budget // 25`;
- missingness policy is always present in `AssumptionLedger`;
- expected missingness thresholds are tested when the explicit numeric
  `user_overrides["expected_missingness_rate"]` bridge is supplied;
- guide citation cards use known rule ids and source keys from
  `STATISTICAL_GUIDE.md`;
- changing citation snippet prose cannot change deterministic status.

## Owner Questions

These are now future migration decisions. They should not block the default
BA5.4 implementation above.

1. Where should `expected_missingness_rate` permanently live:
   `DeploymentContext`, a typed engine config object, or a future request field?
   BA5.4 uses the override bridge now; the consequence is less schema churn but
   weaker discoverability for UI forms.
2. Should sensitivity branches stay duplicated in notes and typed diagnostics,
   or should a future schema replace the notes with first-class sensitivity
   result objects? BA5.4 keeps both; the consequence is better UI readiness with
   some redundant text.
3. Should `SOFT_SPLIT_WARNING_CAP` become a real warning issue in BA5.4, or stay
   UI-only guidance while the hard search cap remains `5000`?

## Final Decision

Adopt the compatibility-preserving defaults now:

- preserve `baseline_rate = 0.5`, `alpha = 0.05`, `beta = 0.20`, and
  `target_power = 0.80`;
- preserve current budget, coverage, distractor, and slice thresholds;
- add `0.2 / 0.5 / 0.8` sensitivity branches;
- add `floor_ceiling_risk` when supplied priors are `< 0.10` or `> 0.90`;
- keep repeated attempts separate from iid task count;
- avoid numeric design-effect penalties without calibrated logs;
- keep missingness policy mandatory, but enforce rate thresholds only when an
  explicit numeric `expected_missingness_rate` is supplied through the BA5.4
  override bridge; migrate that bridge to a typed field later;
- use stronger budgets as alternatives and repairs, not as refusal floors.
