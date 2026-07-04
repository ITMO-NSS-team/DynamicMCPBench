# Card 04 - Mode-Specific Formulas And Planning Proxies

Status: answered implementation contract.

Scope: deterministic pre-run calculators for BA5.4 Statistical Engine planning.
These formulas populate planning fields and issue decisions before benchmark
generation. They do not perform post-run inference and must not be described as
proof of future outcomes.

## Executive Recommendation

Use one shared no-prior planning core, then interpret it by mode:

- `pairwise`: paired task-level delta is the estimand; no-prior MDE uses unique
  paired tasks as the planning unit; post-run family is paired bootstrap.
- `leaderboard`: pre-run planning estimates rank resolution, not final rank
  stability probability; post-run family is stratified task bootstrap.
- `regression`: `target_detectable_effect_pp` is the predeclared
  non-inferiority margin; missing margin is a critical issue.
- `diagnostic`: default planning is per-slice descriptive precision using
  Wilson interval width; slices are exploratory unless predeclared, budgeted,
  and covered by multiplicity policy.

Preserve the BA5.1-BA5.3 fields and enums. Add new calculators as deterministic
helper functions and new formula-version strings; do not add new schema enums
unless implementation later decides to type richer rank/sensitivity outputs.

## Shared Formula Policy

### Units

`task_budget` means unique benchmark tasks / TaskSpecs.

Do not use:

```text
task_budget * attempts_per_task
```

as iid sample size. Attempts can support reliability and pass@k diagnostics, but
they do not repair model-selection power.

### Effective sample size

Default no-prior policy:

```text
n_eff = task_budget
```

for same-task paired pairwise, same-slice regression, leaderboard rank
resolution, and whole-benchmark diagnostic precision.

If task clustering is known from calibrated logs:

```text
n_eff = floor(task_budget / design_effect)
```

where `design_effect >= 1`. This must be labeled `empirical_prior`. Without
calibrated logs, only emit the caveat `n_eff <= task_budget`; do not apply a
hidden numeric penalty.

### No-prior MDE

Use the existing BA helper as the no-prior planning approximation:

```text
mde_pp = 100 * (z_(1-alpha/2) + z_(1-beta)) * sqrt(2 * p * (1 - p) / n_eff)
```

Defaults from Card 03:

```text
alpha = 0.05
beta = 0.20
target_power = 0.80
p = baseline_rate = 0.5
```

Implementation mapping:

- current helper: `planned_mde_pp(n_eff, baseline=0.5)`;
- proposed BA5.4 wrapper:

```python
planned_mde_pp_for_unique_tasks(
    unique_tasks: int,
    baseline: float = 0.5,
    *,
    effective_sample_size: int | None = None,
) -> float
```

The current name `planned_mde_pp(n_per_group)` is misleading for same-task
paired planning. BA5.4 should treat the argument as `n_eff` in the paired
default wrapper and reserve per-arm interpretation for explicit unpaired
designs.

### Wilson CI width

For single binary rate precision:

```text
ci_width_pp = 100 * (wilson_high - wilson_low)
```

Implementation mapping:

- current helper: `ci_width_pp(n, p=0.5, z=1.96)`;
- use only for single-rate diagnostic/smoke precision or UI intuition;
- do not present Wilson single-rate width as the final paired model-delta CI.

### Source anchors

| Formula family | Guide rule ids | Source keys |
|---|---|---|
| no-prior MDE | `G4.mde.heuristic`, `G4.mde.two_proportion_planning`, `G4.mde.underpowered` | `Colas2018`, `Henderson2018`, `Brown2001` |
| repeated attempts | `G4.repeats.not_independent_tasks`, `G2.metric.pass3` | `TauBench2024`, `HumanEval2021`, `SurveyDesignEffect` |
| paired comparison | `G2.metric.pairwise_delta`, `G5.criterion.paired_bootstrap`, `G5.criterion.randomization_fallback` | `Efron1979`, `Dror2018`, `Yeh2000` |
| rank stability | `G1.leaderboard.ranking`, `G2.metric.rank_stability`, `G5.criterion.rank_stability` | `BenchmarkLottery2021`, `HELM2022`, `Efron1979` |
| non-inferiority | `G1.regression.non_inferiority`, `G2.metric.non_inferiority`, `G5.criterion.non_inferiority` | `CONSORT2010`, `Colas2018`, `Dror2018` |
| diagnostic precision | `G1.diagnostic.slice`, `G2.metric.diagnostic_slice`, `G5.criterion.descriptive_diagnostic`, `G5.criterion.wilson_planning` | `CheckList2020`, `Dynabench2021`, `ToolSandbox2024`, `Brown2001` |
| multiplicity | `G4.slices.limit`, `G5.multiple.primary_vs_exploratory`, `G5.multiple.holm_confirmatory`, `G5.multiple.bh_diagnostic` | `Dror2017`, `Holm1979`, `BH1995` |

## Pairwise Mode

Use case: compare exactly two models/agents on the same planned task
distribution.

| Item | Recommendation |
|---|---|
| default planning estimand | `delta_pp = 100 * mean(success_A_i - success_B_i)` over unique paired tasks |
| no-prior MDE formula | `planned_mde_pp_for_unique_tasks(task_budget, baseline=0.5)` with `n_eff = task_budget`; label `planning_heuristic` |
| paired-prior formula if logs exist | Bootstrap or simulate paired task-level deltas from local logs; estimate budget-to-detectable-delta curve; label `empirical_prior` |
| post-run method label | `paired_bootstrap`; optional fallback/complement `approximate_randomization` in rationale text, not a new enum |
| current schema mapping | `primary_metric = "pairwise_delta_pp"`, `test_family = "paired_bootstrap"`, `ci_method = "paired_bootstrap"`, `mde_method = "paired_bootstrap_heuristic"`, `pairwise_test = "paired_bootstrap"` |
| assumptions to surface | same task ids for A and B; tasks are the resampling unit; attempts do not multiply N; public logs are priors only |
| refusal/warning triggers | candidate count not exactly 2; budget below `BUDGET_BANDS["pairwise"]`; target effect below MDE thresholds; unpaired primary comparison if same-task design exists |
| monotonicity tests | MDE decreases as `task_budget` increases; MDE unchanged when only `attempts_per_task` increases; stronger alternative has lower MDE than recommended |

No-prior algorithm:

```python
def pairwise_no_prior_mde_pp(task_budget: int, baseline: float = 0.5) -> float:
    n_eff = max(1, task_budget)
    return planned_mde_pp(n_eff, baseline)
```

Optional empirical-prior algorithm:

```python
def pairwise_empirical_budget_curve(task_deltas, budgets, seed=0):
    # task_deltas are per-task y_A - y_B values from approved local logs.
    # Resample task deltas, not attempts.
    # Return budget -> detectable delta / bootstrap CI width summary.
```

The empirical curve is allowed only when the source is local, auditable, and
listed in `EngineComputationTrace.empirical_prior_sources`. It can refine
alternatives and caveats, but deterministic validators still decide status.

Implementation notes:

- Keep using `planned_mde_pp(design.task_budget)` for same-task pairwise
  compatibility.
- Do not switch to `budget // 2` for pairwise just because two models are
  evaluated. Both models use the same tasks; the unique paired task is the
  planning unit.
- If a future unpaired mode is introduced, represent per-arm sample size
  explicitly and do not reuse pairwise defaults.

## Leaderboard Mode

Use case: rank three or more models with uncertainty.

A leaderboard cannot know rank stability before outcomes. The no-prior engine
should therefore compute a rank-resolution proxy, not a fake top-k retention
probability.

| Item | Recommendation |
|---|---|
| default planning estimand | per-model trace/effect pass rate and rank over the planned task distribution |
| rank-stability proxy | `rank_resolution_pp = planned_mde_pp_for_unique_tasks(task_budget, baseline=0.5)` plus model-count and multiplicity caveats |
| top-k proxy | top-k claims require post-run bootstrap top-k retention; pre-run output only states whether budget is `exploratory`, `display_with_caveats`, or `stronger_rank_stability_candidate` |
| pairwise claim handling | Pairwise superiority claims inside a leaderboard are not allowed by default; they require a predeclared pairwise family and multiplicity plan |
| multiplicity policy | `single primary rank display; Holm for small confirmatory pairwise families; BH/FDR or descriptive-only for exploratory diagnostics` |
| current schema mapping | `primary_metric = "rank_stability"`, `test_family = "rank_stability_bootstrap"`, `ci_method = "stratified_bootstrap"`, `rank_stability_method = "bootstrap_tasks_within_strata"` |
| assumptions to surface | task bootstrap within strata; rank order is scoped; no universal best-model claim; public logs do not prove private rank |
| warning/refusal triggers | fewer than 3 models; budget below leaderboard bands; point-rank-only claim; confirmatory pairwise claims without multiplicity policy |
| monotonicity tests | `rank_resolution_pp` decreases with task budget; stronger leaderboard alternative has larger budget and lower rank resolution pp; candidate count below 3 refuses |

No-prior proxy:

```python
def leaderboard_rank_resolution_pp(task_budget: int, baseline: float = 0.5) -> float:
    return planned_mde_pp(max(1, task_budget), baseline)
```

Recommended rank planning bands:

| Condition | Planning interpretation |
|---|---|
| `task_budget < 80` | refused for leaderboard ranking under current threshold |
| `80 <= task_budget < 150` | exploratory leaderboard warning |
| `task_budget >= 150` | scoped leaderboard display with rank-stability caveats |
| `task_budget >= 300` | stronger rank-stability candidate |
| `task_budget >= 500` | stronger candidate for medium-effect rank separation |

If actual outcomes or approved logs exist, BA5.4 may compute empirical
rank-stability curves:

```python
bootstrap tasks within strata
for each bootstrap sample:
    compute per-model score
    compute ranks
summaries:
    top_k_retention
    rank_interval_by_model
    pairwise_win_probability
    kendall_tau_to_full_sample
```

Before outcomes, these are method commitments and alternative targets, not
numeric guarantees.

## Regression / Non-Inferiority Mode

Use case: check that a candidate has not regressed beyond a predeclared margin
on a fixed slice.

| Item | Recommendation |
|---|---|
| required input | `target_detectable_effect_pp` must be present and is interpreted as the non-inferiority margin in percentage points |
| margin interpretation | `margin_pp = target_detectable_effect_pp`; it is not an observed delta and must not be chosen after seeing outcomes |
| planning formula/proxy | compare `margin_pp` to `planned_mde_pp_for_unique_tasks(task_budget, baseline=0.5)` |
| one-sided claim wording | "candidate is not worse than baseline by more than `{margin_pp}` pp on the fixed slice" |
| current schema mapping | `primary_metric = "non_inferiority_margin_pp"`, `test_family = "non_inferiority_margin"`, `claim_scope = "regression_non_inferiority"`, `hypotheses.non_inferiority_margin_pp = margin_pp` |
| assumptions to surface | fixed regression slice; predeclared margin; one-sided decision; no superiority claim unless separately powered |
| warning/refusal triggers | missing margin; margin below MDE thresholds; post-hoc margin suspected; missing baseline/candidate identity when candidate models are used |
| monotonicity tests | MDE decreases with task budget; same margin becomes less underpowered as budget increases; missing margin refuses |

No-prior algorithm:

```python
def regression_margin_status(task_budget: int, margin_pp: float, baseline: float = 0.5):
    mde = planned_mde_pp(max(1, task_budget), baseline)
    if margin_pp < 0.75 * mde:
        return "refused"
    if margin_pp < mde:
        return "warning"
    return "approved"
```

BA5.4 should preserve the current v2 behavior:

- missing `target_detectable_effect_pp` in regression emits critical issue
  `missing_non_inferiority_margin`;
- Pydantic invalid range errors remain schema errors, not
  `needs_clarification`;
- `needs_clarification` is for missing user intent fields that are structurally
  valid but semantically incomplete.

Recommended migration:

- Add a regression candidate-count check if `candidate_models` is supplied:
  exactly two logical models, baseline and candidate. This is a new BA5.4
  threshold and should use `unsupported_candidate_model_count`.

## Diagnostic Mode

Use case: understand failure modes such as same-name tools, hard negatives,
wrong-server calls, recovery failures, cross-server workflows, or long-chain
failures.

| Item | Recommendation |
|---|---|
| default planning estimand | descriptive slice failure or success rate within named diagnostic slice |
| precision formula | `slice_ci_width_pp = ci_width_pp(slice_task_count, baseline_or_0_5)` using Wilson interval width |
| confirmatory slice rule | slice can be confirmatory only if predeclared, `slice_task_count >= 40`, and total confirmatory slices stay within `max(1, task_budget // 40)` |
| exploratory default caveat | diagnostic slices are exploratory unless explicitly predeclared and budgeted |
| required generator pressure | same-name uses `distractors.same_name_fraction`; near-miss/hard-negative uses `distractors.near_miss_fraction`; approved pressure is `>= 0.25`, warning is `0.10..0.249`, refused is `< 0.10` when claimed |
| current schema mapping | `primary_metric = "slice_failure_rate"`, `test_family = "diagnostic_descriptive"`, `ci_method = "wilson_score"`, `rank_stability_method = "not_applicable"` |
| warning/refusal triggers | diagnostic-only design used for broad model selection; too many slices; undercovered named slice; missing distractor pressure |
| monotonicity tests | slice CI width decreases as slice task count increases; adding unrelated attempts does not shrink slice CI width; missing pressure emits issue when slice is claimed |

Slice-count algorithm:

```python
def slice_task_count(task_budget: int, slice_ratio: float) -> int:
    return max(1, int(task_budget * slice_ratio))

def diagnostic_slice_ci_width_pp(task_budget: int, slice_ratio: float, p: float = 0.5) -> float:
    return ci_width_pp(slice_task_count(task_budget, slice_ratio), p)
```

Precision interpretation:

| Per-slice unique tasks | Interpretation |
|---:|---|
| `< 20` | too small for confirmatory diagnostic claims; usually warning/refusal depending on claim |
| `20..39` | exploratory diagnostic precision only |
| `>= 40` | minimum confirmatory slice target if predeclared |
| `>= 100` | stronger diagnostic precision alternative |

The engine should expose slice diagnostics as candidate metadata or
`sensitivity_notes` until a typed `SlicePlanningDiagnostic` schema exists.

## Cross-Mode Field Mapping

| Mode | `PowerAnalysis.method` | `ParameterSearchSpace.method_families` | Required `formula_versions` |
|---|---|---|---|
| `pairwise` | `paired_bootstrap_heuristic` | `["paired_bootstrap"]` | `planned_mde_pp.unique_tasks.v1`, `paired_task_delta.v1`, `ci_width_pp.v1`, `validator.v1` |
| `leaderboard` | `rank_stability_resolution_proxy` | `["rank_stability_bootstrap"]` | `leaderboard_rank_resolution_pp.v1`, `planned_mde_pp.unique_tasks.v1`, `validator.v1` |
| `regression` | `non_inferiority_margin_planning` | `["non_inferiority_margin"]` | `planned_mde_pp.unique_tasks.v1`, `non_inferiority_margin_status.v1`, `validator.v1` |
| `diagnostic` | `diagnostic_slice_precision` | `["diagnostic_descriptive"]` | `wilson_slice_ci_width.v1`, `slice_task_count.v1`, `validator.v1` |

Current schema note:

- `PowerAnalysis.method` and `method_families` are non-empty strings/lists, so
  BA5.4 can use the method labels above without enum migration.
- `AnalysisPlan.mde_method` is currently limited to
  `normal_approx_two_proportion` or `paired_bootstrap_heuristic`; if the design
  object itself needs richer method labels, that is a schema migration.

## Budget Alternatives

Every mode should return at least:

| Alternative id | Meaning | Selection rule |
|---|---|---|
| `alt.budget_minimum` | cheapest searched candidate | may be warning/refused/smoke |
| `alt.recommended` | cheapest candidate that supports the best honest claim | selected by deterministic score |
| `alt.stronger` | higher-budget candidate with lower MDE, lower rank-resolution pp, or narrower slice CI | first materially stronger candidate above recommended |
| `alt.narrowed_claim` | keeps budget near request but narrows allowed claim | non-refused candidate closest to user budget |

Material improvement rule for tests:

```text
stronger.power_analysis.planned_mde_pp < recommended.power_analysis.planned_mde_pp
or
stronger.slice_ci_width_pp < recommended.slice_ci_width_pp
or
stronger.rank_resolution_pp < recommended.rank_resolution_pp
```

Do not hide a weak recommended design just because a stronger design exists.

## Proposed Unit Tests

Add tests for:

- pairwise MDE uses unique `task_budget`, not `task_budget // 2`;
- increasing `attempts_per_task` does not reduce pairwise MDE;
- pairwise method fields are `paired_bootstrap` / `paired_bootstrap_heuristic`;
- pairwise candidate count other than 2 refuses with
  `unsupported_candidate_model_count`;
- leaderboard with fewer than 3 candidates refuses;
- leaderboard rank-resolution proxy decreases with budget;
- leaderboard `PowerAnalysis.method` uses a rank-stability proxy label;
- regression missing margin refuses with `missing_non_inferiority_margin`;
- regression margin below `0.75 * planned_mde` refuses and below planned MDE
  warns;
- diagnostic slice CI width uses `floor(task_budget * slice.ratio)` unique
  tasks;
- diagnostic same-name / hard-negative claims require corresponding distractor
  pressure;
- all modes include missingness, multiplicity, repeated-attempt, and
  floor/ceiling caveats in the assumption ledger;
- formula-version strings identify the mode-specific calculator;
- local guide citations use known rule ids from `STATISTICAL_GUIDE.md`;
- changing citation snippet prose does not change deterministic status.

## Final Decision

Implement BA5.4 formulas as deterministic wrappers around existing helpers,
with mode-specific interpretation:

- same-task pairwise and regression: `n_eff = unique task_budget`;
- leaderboard: rank-resolution proxy, not fake pre-run rank probability;
- diagnostic: per-slice Wilson precision;
- attempts never multiply iid N;
- empirical priors may refine curves only when local, auditable, and labeled.
