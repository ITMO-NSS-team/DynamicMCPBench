# Benchmark Advisor Statistical Guide

Status: v1 planning knowledge pack.
Purpose: provide the curated statistical rules that the planner must use when
turning user intent into benchmark-design proposals.

This guide is intentionally static and versioned. It is not RAG in v1. The
planner may use an LLM, but it must ground its choices in the rule ids below and
must surface those rule ids through the rationale/evidence ledger.

## Guide Contract

- `guide_version`: `statistical_guide.v1`
- Every planner-produced criterion and major distribution parameter must cite at
  least one `rule_id`.
- Every user-visible rationale tooltip must be derivable from a cited rule.
- The deterministic validator may reject or warn when required guide references
  are missing, malformed, or inconsistent with the proposed design.
- The guide supports Stage 1 pre-run planning only. Stage 2 post-run inference is
  represented by interfaces but not implemented in v1.

## Rule Families

### G1 - Intent To Mode

| rule_id | User intent signal | Mode | Claim scope |
|---|---|---|---|
| `G1.pairwise.selection` | compare A vs B; choose better model | `pairwise` | `confirmatory_model_selection` |
| `G1.leaderboard.ranking` | rank several models; leaderboard | `leaderboard` | `leaderboard_ranking` |
| `G1.regression.non_inferiority` | did new agent regress; production regression | `regression` | `regression_non_inferiority` |
| `G1.diagnostic.slice` | why failure; same-name; wrong-server; recovery diagnostic | `diagnostic` | `diagnostic_slice` |
| `G1.smoke.budget` | tiny budget or exploratory check | request mode may remain, but claim scope must downgrade | `smoke_test_only` |

Planner requirement: if intent signals conflict, prefer `needs_clarification`
unless the user explicitly chooses a primary question.

### G2 - Estimand And Metric Selection

| rule_id | Condition | Recommended estimand / metric |
|---|---|---|
| `G2.metric.effect_pass` | any DynamicMCPBench evaluation | trace/effect pass rate; never final-answer match |
| `G2.metric.pass3` | user asks reliability or model selection with repeats | `pass_at_3` |
| `G2.metric.pairwise_delta` | pairwise model selection | paired difference in effect pass rate |
| `G2.metric.non_inferiority` | regression check | non-inferiority margin in percentage points |
| `G2.metric.rank_stability` | leaderboard claim | rank stability under task resampling |
| `G2.metric.diagnostic_slice` | same-name/wrong-server/recovery diagnostic | descriptive slice failure rate |

Planner requirement: choose one primary metric before secondary diagnostics.
Secondary metrics must be marked exploratory unless the design has enough task
budget for confirmatory slices.

### G3 - Task Distribution

| rule_id | Intent signal | Distribution implication |
|---|---|---|
| `G3.coverage.long_workflows` | long, multi-step, production workflows | long-chain ratio should be at least validator approved threshold |
| `G3.coverage.short_workflows` | short, low-step, quick workflows | short-chain ratio should be raised above the balanced default |
| `G3.coverage.cross_server` | cross-server composition, orchestration, wrong-server risk | cross-server ratio should be at least validator approved threshold |
| `G3.coverage.recovery` | recovery, failure handling, robustness | recovery-required ratio should be at least validator approved threshold |
| `G3.coverage.same_name` | same-name, homonym, wrong-server diagnostic | include same-name diagnostic slice and distractor pressure |
| `G3.distractor.hard_negative` | hard negatives, similar tools, confusing alternatives | increase near-miss / hard-negative distractor pressure |
| `G3.distractor.near_miss` | similar names, near-name collisions, near-miss tools | increase near-miss distractor pressure |
| `G3.domain.finance` | finance workflows, market data, financial analysis | include finance as a planned task category |
| `G3.coverage.stateful` | stateful-write tasks | require sandbox flag in export knobs |

Planner requirement: when a user intent explicitly names a capability, the
distribution must allocate coverage to that capability or explain why it cannot.
Domain and distractor signals are first-class intent signals: they should not
fall back to `general` when explicitly present.

### G4 - Budget, Power, And Repeats

| rule_id | Planning rule |
|---|---|
| `G4.budget.mode_thresholds` | Use validator thresholds from `INTERFACES.md` for approved/warning/refused task-budget status. |
| `G4.repeats.pass3` | `pass_at_3` claims require at least 3 attempts per task. |
| `G4.mde.heuristic` | Stage 1 MDE is a planning heuristic, not final inference. |
| `G4.mde.underpowered` | If requested detectable effect is below planned MDE, warn or refuse according to thresholds. |
| `G4.slices.limit` | Confirmatory slice count must be limited by task budget. Extra slices are exploratory. |

Planner requirement: when budget is too small, propose a repair: more tasks,
larger detectable effect, fewer confirmatory claims, or smoke-test framing.

### G5 - Criterion Selection

| rule_id | Mode / claim | Criterion family |
|---|---|---|
| `G5.criterion.paired_bootstrap` | pairwise model selection | paired bootstrap over tasks |
| `G5.criterion.wilson_planning` | rough pass-rate planning | Wilson / normal-approx proportion interval as heuristic |
| `G5.criterion.non_inferiority` | regression | non-inferiority margin check |
| `G5.criterion.rank_stability` | leaderboard | bootstrap tasks within strata |
| `G5.criterion.descriptive_diagnostic` | diagnostics | descriptive diagnostic rate with claim boundary |

Planner requirement: every criterion must have a `decision_rule`, an
`allowed_claim`, and at least one guide reference.

### G6 - Claim Boundaries

| rule_id | Forbidden or required behavior |
|---|---|
| `G6.claim.no_universal_best` | Never claim one model is universally better. |
| `G6.claim.no_external_validity` | Never claim the benchmark fully represents unseen private deployments. |
| `G6.claim.public_logs_prior` | Public logs are calibration priors, not proof for private-server behavior. |
| `G6.claim.no_final_answer` | Final-answer matching is not an allowed benchmark metric. |
| `G6.claim.diagnostic_not_selection` | Diagnostic slices do not by themselves justify broad model-selection claims. |

Planner requirement: the `claim_boundary` field must explicitly limit what the
planned benchmark can and cannot support.

### G7 - Rationale And UI Explanation

| rule_id | Requirement |
|---|---|
| `G7.rationale.parameter` | Every major proposed parameter needs a short user-visible rationale. |
| `G7.rationale.criterion` | Every criterion needs a rationale tied to guide rules and user intent evidence. |
| `G7.rationale.default` | Defaults without intent evidence must be labeled as defaults. |
| `G7.rationale.hover` | UI hover text should be short, concrete, and cite the statistical reason. |
| `G7.rationale.future_judge` | Rationale entries should be structured so a future judge-based validator can score them. |

Planner requirement: rationale text should explain why the choice follows from
the guide, not merely restate the chosen value.

## Good Rationale Examples

- Parameter: `task_distribution.cross_server_ratio = 0.35`
  - Rule ids: `G3.coverage.cross_server`, `G7.rationale.parameter`
  - Tooltip: "The request emphasizes cross-server composition, so the design
    allocates a substantial cross-server slice instead of ranking models only on
    single-server tasks."

- Criterion: `paired_bootstrap`
  - Rule ids: `G5.criterion.paired_bootstrap`, `G2.metric.pairwise_delta`
  - Tooltip: "The primary question compares two models on the same planned task
    distribution, so paired task-level resampling is the planned comparison
    family."

## Bad Rationale Examples

- "This is statistically valid because the advisor says so."
- "Model A will be better after this benchmark."
- "Public logs prove this private workflow result."
- "We use final answer accuracy as the primary metric."
