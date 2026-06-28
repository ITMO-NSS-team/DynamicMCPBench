# Benchmark Advisor Statistical Guide

Status: v1 planning knowledge pack; research refresh integrated 2026-06-27.
Purpose: provide the curated statistical rules that the planner must use when
turning user intent into benchmark-design proposals.

This guide is intentionally static and versioned. It is not RAG in v1. The
planner may use an LLM, but it must ground its choices in the rule ids below and
must surface those rule ids through the rationale/evidence ledger.

This refresh preserves the existing G1-G7 structure and rule-id style. It adds
columns for validator behavior, evidence status, repair suggestions, and source
keys. Numeric thresholds that are already normative in `INTERFACES.md` remain
normative. New numeric thresholds introduced here should be treated as
conservative defaults until calibrated on DynamicMCPBench logs.

## Guide Contract

- `guide_version`: `statistical_guide.v1`
- `research_refresh`: `2026-06-27`
- Stage 1 is pre-run planning only. Stage 2 post-run inference is represented by
  interfaces but not implemented in v1.
- Every planner-produced criterion and major distribution parameter must cite at
  least one `rule_id`.
- Every user-visible rationale tooltip must be derivable from a cited rule.
- The deterministic validator may reject or warn when required guide references
  are missing, malformed, or inconsistent with the proposed design.
- The LLM planner may propose and explain, but deterministic validation has final
  authority over approval, warning, refusal, and repair suggestions.
- Public benchmark logs may be used as calibration priors for planning, but not
  as proof for private-server behavior.
- Defaults must be labeled as defaults. Heuristics must be labeled as heuristics.
  Literature-backed procedures must be distinguishable from empirical priors and
  engineering safeguards.

### Evidence Status Vocabulary

| evidence_status | Meaning | Validator interpretation |
|---|---|---|
| `normative` | Standard statistical or project-level invariant that should be enforced unless explicitly out of scope. | May refuse invalid designs. |
| `methodological` | Strongly supported by benchmark/statistical methodology, but exact thresholds may be project-specific. | Usually warn or require explicit rationale. |
| `agent_specific_preliminary` | Supported by recent agent/tool-use benchmark literature, often arXiv or young venues. | Use as rule rationale, but avoid pretending numeric thresholds are universal. |
| `empirical_prior` | Calibrated from public logs or previous runs. | Must be labeled as prior, never as private-deployment proof. |
| `engineering_safeguard` | Conservative implementation rule used to prevent misleading designs. | May warn/refuse, but rationale must say it is a safeguard. |

### Source Keys

Use these short source keys in the `source_keys` column. Full references are in
`## Source Reference Map`.

- `Dror2017`, `Dror2018`, `Yeh2000`, `Efron1979`, `Brown2001`, `Holm1979`,
  `BH1995`, `Henderson2018`, `Colas2018`, `Bragg2021`, `BenchmarkLottery2021`,
  `HELM2022`, `Dynabench2021`, `CheckList2020`, `Ethayarajh2020`, `Raji2021`,
  `Datasheets2018`, `ModelCards2019`, `DataCards2022`, `Northcutt2021`,
  `Sainz2023`, `Gururangan2018`, `Geirhos2020`, `Recht2019`, `ToolSandbox2024`,
  `TauBench2024`, `OSWorld2024`, `WebArena2023`, `ToolTalk2023`, `BowmanDahl2021`,
  `HumanEval2021`, `McNemar1947`, `CONSORT2010`, `SurveyDesignEffect`,
  `ProjectInterfaces2026`, `DynamicMCPBench2026`.

## Rule Families

### G1 - Intent To Mode

| rule_id | User intent signal | Mode | Claim scope | Validator behavior | Evidence status | Source keys |
|---|---|---|---|---|---|---|
| `G1.pairwise.selection` | compare A vs B; choose better model; select a production candidate | `pairwise` | `confirmatory_model_selection` for the declared deployment slice only | Require exactly two candidate models, a primary metric, paired task plan, null/alternative hypotheses, and claim boundary. Warn if user asks for universal superiority. | `methodological` | `Dror2017`; `Dror2018`; `Ethayarajh2020`; `HELM2022` |
| `G1.leaderboard.ranking` | rank several models; leaderboard; top-k models | `leaderboard` | `leaderboard_ranking` with uncertainty and rank-stability caveats | Require model set size >= 3, rank-stability plan, multiplicity plan for pairwise claims, and no point-rank-only claims. | `methodological` | `BenchmarkLottery2021`; `HELM2022`; `Ethayarajh2020` |
| `G1.regression.non_inferiority` | did new agent regress; production regression; is new model not worse | `regression` | `regression_non_inferiority` or paired regression check on fixed slice | Require baseline model, candidate model, fixed regression slice, non-inferiority margin or regression threshold, and one-sided claim language. | `normative` | `Colas2018`; `Henderson2018`; `Dror2018` |
| `G1.diagnostic.slice` | why failure; same-name tools; wrong-server calls; recovery diagnostic; cross-server failure mode | `diagnostic` | `diagnostic_slice`; descriptive or exploratory unless powered as confirmatory | Mark slice results as diagnostic. Refuse broad model-selection claim if design only covers a narrow failure-mode slice. | `methodological` | `CheckList2020`; `Dynabench2021`; `ToolSandbox2024`; `Raji2021` |
| `G1.smoke.budget` | tiny budget; quick check; sanity check; exploratory preview | request mode may remain, but claim scope must downgrade | `smoke_test_only` | Downgrade claim if task count or repeats fall below mode thresholds. Export allowed only with warning state, not confirmatory claim. | `engineering_safeguard` | `Colas2018`; `Bragg2021`; `Henderson2018` |
| `G1.intent.primary_question_required` | user asks multiple goals at once without priority | `needs_clarification` | no claim until primary question is selected | Ask for primary objective or pick a safe diagnostic/smoke framing only if user explicitly accepts weaker claims. | `normative` | `HELM2022`; `Ethayarajh2020`; `Datasheets2018` |
| `G1.intent.claim_scope_first` | intent contains broad words: best, reliable, robust, production-ready, safe | selected mode depends on concrete question | claim scope must be made explicit before budget and task mix are approved | Require `allowed_claim` and `claim_boundary` fields before export. Refuse if user-visible rationale implies external validity beyond design. | `normative` | `Ethayarajh2020`; `Raji2021`; `HELM2022`; `ModelCards2019` |

Planner requirement: if intent signals conflict, prefer `needs_clarification`
unless the user explicitly chooses a primary question. If budget is too small
for the requested mode, preserve the user's requested mode in the proposal but
downgrade `claim_scope` to `smoke_test_only` and emit a repair suggestion.

### G2 - Estimand And Metric Selection

| rule_id | Condition | Recommended estimand / metric | Validator behavior | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G2.metric.effect_pass` | any DynamicMCPBench or MCP-agent evaluation with executable trace/effect scoring | Trace/effect pass rate. Do not use final-answer matching as primary metric. | Refuse `final_answer_accuracy` or answer-only primary metrics when trace/effect scoring is available. | `normative` | `DynamicMCPBench2026`; `ToolSandbox2024`; `OSWorld2024`; `TauBench2024` |
| `G2.metric.execution_primary` | environment has world-state, tool-call, trace, milestone, or effect checks | Primary metric should be execution-grounded: effect pass, milestone pass, final state validity, or trace-validated success. | Require outcome definition that names the checked state/effect/trace. Warn if only natural-language judge text is specified. | `agent_specific_preliminary` | `ToolSandbox2024`; `OSWorld2024`; `WebArena2023`; `TauBench2024` |
| `G2.metric.pass3` | user asks reliability, repeated attempts, pass@k, pass^k, robustness, or model selection with repeats | `pass_at_3` or explicit repeated-attempt reliability metric | Require `attempts_per_task >= 3` for `pass_at_3`. Distinguish repeated attempts from independent tasks. | `engineering_safeguard` | `TauBench2024`; `HumanEval2021`; `Colas2018` |
| `G2.metric.reliability_requires_k` | reliability/consistency claim is made | Explicit repeated-attempt metric with stated `k`, attempt policy, randomness policy, and aggregation rule | Warn if reliability intent has `k=1`; refuse confirmatory reliability claims without explicit `k`. | `methodological` | `TauBench2024`; `HumanEval2021`; `Henderson2018` |
| `G2.metric.pairwise_delta` | pairwise model selection on the same planned task distribution | Paired difference in effect pass rate: delta = mean(success_A - success_B) over tasks | Require paired task IDs or equivalent paired task-generation contract. Warn/refuse if unpaired comparison is proposed for shared-task evaluation. | `normative` | `Dror2018`; `Yeh2000`; `Efron1979` |
| `G2.metric.non_inferiority` | regression check; production candidate should not be worse than baseline | Non-inferiority margin in percentage points, defined before evaluation | Require a margin. Refuse regression/non-inferiority mode if margin is missing or selected post hoc. | `normative` | `Colas2018`; `Dror2018`; `CONSORT2010` |
| `G2.metric.rank_stability` | leaderboard claim; top-k claim; multi-model ranking | Rank stability under task resampling: Kendall tau, top-k retention, pairwise win probability, rank intervals if available | Require at least one rank-stability summary for leaderboard mode. Warn on point-rank-only output. | `methodological` | `BenchmarkLottery2021`; `HELM2022`; `Efron1979` |
| `G2.metric.diagnostic_slice` | same-name, wrong-server, recovery, cross-server, distractor or failure-mode diagnostic | Descriptive diagnostic rate; optionally paired slice delta if powered and predeclared | Mark diagnostic metrics as exploratory unless declared as confirmatory with enough budget and multiplicity plan. | `methodological` | `CheckList2020`; `Dynabench2021`; `ToolSandbox2024` |
| `G2.metric.floor_ceiling_sensitivity` | historical or pilot rates suggest pass rate near 0 or 1 | Use metric only with floor/ceiling warning; prefer a difficulty-balanced slice if model comparison is the goal | Warn if primary metric is expected to saturate and requested effect is smaller than expected CI/MDE resolution. | `methodological` | `BowmanDahl2021`; `Bragg2021`; `Henderson2018` |

Planner requirement: choose one primary metric before secondary diagnostics.
Secondary metrics must be marked exploratory unless the design has enough task
budget for confirmatory slices and a multiplicity plan. Never recommend
final-answer matching as the primary metric for MCP/tool-use benchmarks when
trace/effect scoring is available.

### G3 - Task Distribution

| rule_id | Intent signal | Distribution implication | Validator behavior | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G3.distribution.target_mix_explicit` | confirmatory selection, leaderboard, regression, or any deployment-shaped claim | Declare target task distribution over relevant strata before generation | Require explicit target mix or mark design exploratory. Refuse strong deployment claims without target mix. | `methodological` | `BenchmarkLottery2021`; `Bragg2021`; `HELM2022` |
| `G3.distribution.stratified_generation` | user names multiple capabilities, domains, task types, or workflow lengths | Generate and analyze tasks by strata such as domain, chain length, cross-server, recovery, stateful, and distractor family | Require stratum keys and weights. Warn if distribution is collapsed to `general` despite explicit intent evidence. | `methodological` | `Bragg2021`; `BenchmarkLottery2021`; `HELM2022` |
| `G3.audit.coverage_distance` | user gives target deployment mix or the planner infers one | Compute per-stratum deviations and optional total variation distance as a coverage heuristic | Warn if primary stratum is under-covered or proposed mix diverges from target mix above project threshold. Label threshold as heuristic unless calibrated. | `engineering_safeguard` | `BenchmarkLottery2021`; `SurveyDesignEffect`; `HELM2022` |
| `G3.coverage.short_workflows` | short, low-step, quick workflows | Short-chain ratio should be raised above balanced default, but not used to claim long-workflow competence | Approve short-workflow slice if claim boundary is short-slice only. Warn if short-only design is used for broad production workflow claim. | `engineering_safeguard` | `Bragg2021`; `BenchmarkLottery2021` |
| `G3.coverage.medium_workflows` | medium-length workflows, ordinary multi-tool workflows, mixed short/long coverage | Medium-chain ratio is the bridge/default coverage for mixed workflow claims; do not let medium coverage disappear when optimizing for only short or long tasks. | Warn if a mixed workflow claim collapses to only short or only long tasks without a claim-boundary caveat. | `engineering_safeguard` | `Bragg2021`; `BenchmarkLottery2021`; `ProjectInterfaces2026` |
| `G3.coverage.long_workflows` | long, multi-step, production workflows | Long-chain ratio should be at least validator approved threshold; include medium-chain bridge tasks if possible | Warn/refuse according to `INTERFACES.md` thresholds if long-chain claim is made but long-chain coverage is low. | `engineering_safeguard` | `OSWorld2024`; `ToolSandbox2024`; `BenchmarkLottery2021` |
| `G3.coverage.cross_server` | cross-server composition, orchestration, wrong-server risk | Cross-server ratio should be at least validator approved threshold for orchestration claims | Warn/refuse if cross-server claim is made with low cross-server coverage. | `engineering_safeguard` | `DynamicMCPBench2026`; `ToolSandbox2024`; `OSWorld2024` |
| `G3.coverage.recovery` | recovery, failure handling, robustness, retries, error repair | Recovery-required ratio should be at least validator approved threshold for recovery/robustness claims | Warn/refuse if recovery claim is made without planned recovery-required tasks. | `engineering_safeguard` | `ToolSandbox2024`; `CheckList2020`; `Dynabench2021` |
| `G3.coverage.same_name` | same-name, homonym, wrong-server diagnostic | Include same-name diagnostic slice and distractor pressure | Warn/refuse if same-name claim has no same-name slice or distractor metadata. | `agent_specific_preliminary` | `CheckList2020`; `ToolSandbox2024`; `ToolTalk2023` |
| `G3.distractor.hard_negative` | hard negatives, similar tools, confusing alternatives | Increase near-miss and hard-negative distractor pressure above default-low level | If hard-negative pressure is claimed, require corresponding distractor fractions and diagnostic labels. | `agent_specific_preliminary` | `CheckList2020`; `Dynabench2021`; `ToolSandbox2024` |
| `G3.distractor.near_miss` | similar names, near-name collisions, near-miss tools | Increase near-miss distractor pressure | Warn if near-miss intent is present but near-miss fraction remains default/zero. | `agent_specific_preliminary` | `CheckList2020`; `ToolTalk2023`; `ToolSandbox2024` |
| `G3.distractor.claim_requires_pressure` | same-name / near-miss / hard-negative slice appears in claim scope | Diagnostic pressure must be present in generation knobs, not only in rationale text | Refuse unsupported diagnostic claim if slice label is present but generator knobs cannot create the pressure. | `engineering_safeguard` | `CheckList2020`; `ToolSandbox2024`; `DynamicMCPBench2026` |
| `G3.domain.finance` | finance workflows, market data, financial analysis | Include finance as a planned task category and limit claim to finance or mixed-domain design | Warn if finance intent falls back to general task pool. | `engineering_safeguard` | `HELM2022`; `Datasheets2018` |
| `G3.domain.user_named` | user explicitly names any domain not already enumerated | Add that domain as a planned category or ask clarification if unsupported | Warn if named domain is lost. Refuse if user requires unsupported private-domain capability and no task source exists. | `engineering_safeguard` | `HELM2022`; `Datasheets2018`; `DataCards2022` |
| `G3.coverage.stateful` | stateful-write tasks, external side effects, irreversible tool calls | Require sandbox flag and state-reset/replay policy in export knobs | Refuse export if stateful-write tasks lack sandbox or reset policy. | `normative` | `DynamicMCPBench2026`; `ToolSandbox2024`; `ToolTalk2023` |
| `G3.distribution.min_per_primary_stratum` | confirmatory claim uses multiple primary strata | Allocate enough tasks per primary stratum for descriptive stability; exact threshold comes from `INTERFACES.md` or calibrated logs | Warn if many strata make per-stratum counts too small. Suggest reducing confirmatory slice count. | `engineering_safeguard` | `Bragg2021`; `Colas2018`; `BenchmarkLottery2021` |

Planner requirement: when a user intent explicitly names a capability, the
distribution must allocate coverage to that capability or explain why it cannot.
Domain and distractor signals are first-class intent signals: they should not
fall back to `general` when explicitly present. Numeric coverage thresholds are
validator thresholds, not universal statistical laws; if not in `INTERFACES.md`,
mark them as `engineering_safeguard` or `empirical_prior`.

### G4 - Budget, Power, And Repeats

| rule_id | Planning rule | Validator behavior | Repair suggestion | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G4.budget.mode_thresholds` | Use validator thresholds from `INTERFACES.md` for approved/warning/refused task-budget status. | Check task budget against mode-specific thresholds before export. | Increase tasks, narrow claim scope, or downgrade to smoke test. | `normative` | `Colas2018`; `Bragg2021`; `ProjectInterfaces2026` |
| `G4.repeats.pass3` | `pass_at_3` claims require at least 3 attempts per task. | Warn/refuse if `pass_at_3` is selected but attempts per task < 3. | Set attempts per task to 3 or change metric to single-run effect pass. | `engineering_safeguard` | `TauBench2024`; `HumanEval2021` |
| `G4.repeats.not_independent_tasks` | Repeated attempts on the same task are not independent new tasks. | Keep `tasks` and `attempts_per_task` separate. Do not compute nominal N as tasks times attempts for iid CI/MDE. | Increase unique tasks if model-selection power is the goal; keep repeats for reliability diagnostics. | `methodological` | `TauBench2024`; `Colas2018`; `SurveyDesignEffect` |
| `G4.mde.heuristic` | Stage 1 MDE is a planning heuristic, not final inference. | Require MDE fields to carry `planning_heuristic` label. Warn if UI text implies a guarantee. | Relabel MDE wording; add caveat about assumptions and pilot/public-log variance. | `normative` | `Colas2018`; `Henderson2018`; `DynamicMCPBench2026` |
| `G4.mde.underpowered` | If requested detectable effect is below planned MDE, warn or refuse according to thresholds. | Compare user-requested effect or implied claim to planned MDE. | Increase tasks, accept larger detectable effect, reduce confirmatory slices, or smoke-test only. | `methodological` | `Colas2018`; `Henderson2018`; `Bragg2021` |
| `G4.mde.two_proportion_planning` | For rough pre-run planning, use a two-proportion MDE approximation with conservative effective sample size. | Allow only as planning estimate; prefer paired bootstrap/permutation for actual paired post-run comparison. | Use historical paired deltas or pilot logs when available. | `methodological` | `Colas2018`; `Brown2001`; `Dror2018` |
| `G4.power.empirical_curves` | When public logs are available, prefer empirical budget-to-MDE or budget-to-rank-stability curves over pure parametric guesses. | Require `empirical_prior` label if public logs calibrate curves. | State that private-server variance may differ; avoid proof language. | `empirical_prior` | `BenchmarkLottery2021`; `Henderson2018`; `DynamicMCPBench2026` |
| `G4.slices.limit` | Confirmatory slice count must be limited by task budget. Extra slices are exploratory. | Warn/refuse if too many slices are marked confirmatory for available budget. | Move low-priority slices to exploratory diagnostics or increase task budget. | `methodological` | `Dror2017`; `BH1995`; `Holm1979` |
| `G4.floor_ceiling.power_warning` | Expected near-floor or near-ceiling scores reduce ability to detect useful differences. | Use historical/pilot priors if available. Warn if expected pass rate is too close to 0 or 1 for requested delta. | Rebalance difficulty, select more discriminative strata, or change claim to diagnostic. | `methodological` | `BowmanDahl2021`; `Bragg2021`; `Northcutt2021` |
| `G4.clustered_tasks.neff_caveat` | Correlated tasks, repeated attempts, same server clusters, or same template families reduce effective sample size. | Add `n_eff_caveat` when tasks share templates, servers, trajectories, or repeated attempts. | Increase unique templates/servers/tasks or use stratified/cluster-aware bootstrap in Stage 2. | `engineering_safeguard` | `Efron1979`; `SurveyDesignEffect`; `TauBench2024` |

Planner requirement: when budget is too small, propose a repair: more tasks,
larger detectable effect, fewer confirmatory claims, more unique task templates,
or smoke-test framing. Never present MDE or power as a final inferential
guarantee in Stage 1.

### G5 - Criterion Selection

| rule_id | Mode / claim | Criterion family | Validator behavior | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G5.criterion.paired_bootstrap` | pairwise model selection | Paired bootstrap over tasks | Require paired task outcomes and task-level resampling unit. Warn if bootstrap resamples attempts instead of tasks. | `normative` | `Efron1979`; `Dror2018`; `Yeh2000` |
| `G5.criterion.paired_default` | same tasks used for A and B | Paired methods are default; unpaired independent-sample tests are not appropriate as primary criterion | Refuse unpaired confirmatory comparison when shared task IDs exist. | `normative` | `Dror2018`; `Yeh2000` |
| `G5.criterion.randomization_fallback` | paired comparison where a robust nonparametric p-value style check is desired | Approximate randomization / permutation test over paired task-level outcomes | Allow as fallback or complement to paired bootstrap. Require paired outcomes and exchangeability under the null. | `methodological` | `Yeh2000`; `Dror2018` |
| `G5.criterion.wilson_planning` | rough pass-rate planning or single-model pass-rate interval | Wilson interval for single binary proportion; avoid naive Wald interval as default | Warn if Wald interval is selected as primary CI near 0/1 or at small n. | `normative` | `Brown2001` |
| `G5.criterion.bootstrap_score_ci` | scalar benchmark score uncertainty | Nonparametric bootstrap CI over tasks | Require task-level resampling. Warn if task count is too small for stable bootstrap. | `methodological` | `Efron1979`; `BenchmarkLottery2021` |
| `G5.criterion.stratified_bootstrap` | benchmark generated by strata or user claims coverage over slices | Bootstrap tasks within strata and aggregate using planned weights | Warn if stratified design uses unstratified analysis plan. | `methodological` | `Bragg2021`; `BenchmarkLottery2021`; `HELM2022` |
| `G5.criterion.non_inferiority` | regression | Non-inferiority margin check with predeclared margin | Require margin and one-sided decision rule. Refuse if margin is chosen after seeing outcomes. | `normative` | `CONSORT2010`; `Dror2018` |
| `G5.criterion.rank_stability` | leaderboard | Bootstrap tasks within strata; report Kendall tau, top-k retention, pairwise win probability, rank interval if available | Require at least one stability metric in leaderboard mode. Warn on point-rank-only plan. | `methodological` | `BenchmarkLottery2021`; `HELM2022`; `Efron1979` |
| `G5.criterion.descriptive_diagnostic` | diagnostics | Descriptive diagnostic rate with claim boundary; paired slice delta only if powered and predeclared | Mark as exploratory by default. Refuse if diagnostic-only result is used for broad selection claim. | `methodological` | `CheckList2020`; `Dynabench2021`; `ToolSandbox2024` |
| `G5.multiple.primary_vs_exploratory` | any design with multiple pairwise comparisons, metrics, or slices | Separate primary confirmatory family from exploratory diagnostics | Require `family` label for each hypothesis or slice. Warn if all slices are marked confirmatory. | `normative` | `Dror2017`; `Holm1979`; `BH1995` |
| `G5.multiple.holm_confirmatory` | small predeclared confirmatory family | Holm correction or equivalent FWER control | Require correction plan when multiple confirmatory tests exist. | `normative` | `Holm1979`; `Dror2017` |
| `G5.multiple.bh_diagnostic` | larger exploratory diagnostic family | Benjamini-Hochberg / FDR-style control or descriptive-only reporting | Warn if many diagnostic slices report raw significance without FDR/descriptive framing. | `normative` | `BH1995`; `Dror2017` |
| `G5.criterion.mcnemar_narrow` | two models, same tasks, single binary outcome, no repeated attempts, no rich stratification | McNemar-style paired binary comparison as narrow special case | Allow only when assumptions are met. Warn when discordant count is too small. | `methodological` | `McNemar1947`; `Dror2018` |

Planner requirement: every criterion must have a `decision_rule`, an
`allowed_claim`, and at least one guide reference. Pairwise comparisons on the
same tasks should be paired by default. Leaderboard mode must not present a
point ranking without uncertainty or rank-stability information.

### G6 - Claim Boundaries

| rule_id | Forbidden or required behavior | Validator behavior | Repair suggestion | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G6.claim.no_universal_best` | Never claim one model is universally better. | Refuse or rewrite universal-best claims to slice-specific claims. | Replace with: better on declared task distribution under stated metric and uncertainty plan. | `normative` | `Ethayarajh2020`; `Raji2021`; `HELM2022` |
| `G6.claim.no_external_validity` | Never claim the benchmark fully represents unseen private deployments. | Require external-validity caveat for any deployment claim. | Add target-distribution assumptions and out-of-scope domains. | `normative` | `Raji2021`; `Datasheets2018`; `ModelCards2019` |
| `G6.claim.public_logs_prior` | Public logs are calibration priors, not proof for private-server behavior. | If public logs calibrate MDE, variance, difficulty, or task mix, inject `empirical_prior` label and caveat. | Run private-server benchmark or downgrade claim. | `normative` | `DynamicMCPBench2026`; `BenchmarkLottery2021`; `Raji2021` |
| `G6.claim.no_final_answer` | Final-answer matching is not an allowed primary metric for MCP/tool-use benchmarks when trace/effect scoring exists. | Refuse final-answer primary metric. | Use trace/effect pass, milestone success, or state-validity metric. | `normative` | `ToolSandbox2024`; `OSWorld2024`; `DynamicMCPBench2026` |
| `G6.claim.diagnostic_not_selection` | Diagnostic slices do not by themselves justify broad model-selection claims. | Refuse broad selection claim if benchmark contains only narrow diagnostic slices. | Add representative task distribution or narrow claim to diagnostic finding. | `normative` | `CheckList2020`; `Ethayarajh2020`; `Raji2021` |
| `G6.warning.floor_ceiling` | Warn when primary slice is expected to be too easy or too hard to discriminate models. | Use pilot/public-log priors if available. Label caveat as planning heuristic. | Rebalance difficulty or frame as diagnostic. | `methodological` | `BowmanDahl2021`; `Bragg2021`; `Northcutt2021` |
| `G6.warning.contamination_artifacts` | Strong claims on reused public tasks require contamination, artifact, and shortcut-learning caveats. | Require contamination/artifact metadata for public or reused task pools. | Refresh task pool, use private tasks, or downgrade claim. | `methodological` | `Sainz2023`; `Gururangan2018`; `Geirhos2020`; `Recht2019` |
| `G6.warning.label_noise` | Noisy labels, weak judges, or unstable effect checks can destabilize rankings and small deltas. | Warn if outcome source is weak, judge-based, or label-quality unknown. | Add deterministic effect checks, adjudication, or claim boundary around noisy labels. | `methodological` | `Northcutt2021`; `Datasheets2018` |
| `G6.claim.private_transfer_limit` | Calibration on public benchmark logs does not establish private deployment performance. | Automatically include private-transfer limitation when target is private deployment. | Run private benchmark or present public result as calibration only. | `normative` | `DynamicMCPBench2026`; `Raji2021`; `Ethayarajh2020` |
| `G6.claim.confirmatory_vs_exploratory` | Confirmatory claims must be predeclared; exploratory diagnostics must not be promoted to confirmatory after inspection. | Require explicit `confirmatory` vs `exploratory` label. | Reclassify slices or add multiplicity plan and adequate budget. | `normative` | `Dror2017`; `BH1995`; `Holm1979` |

Planner requirement: the `claim_boundary` field must explicitly limit what the
planned benchmark can and cannot support. Claim boundaries should be generated
even for approved designs, not only warnings/refusals.

### G7 - Rationale And UI Explanation

| rule_id | Requirement | Validator behavior | Repair suggestion | Evidence status | Source keys |
|---|---|---|---|---|---|
| `G7.rationale.parameter` | Every major proposed parameter needs a short user-visible rationale. | Warn if task count, repeats, metric, distribution, or criterion lacks rationale. | Add one-sentence rationale tied to user intent and rule IDs. | `normative` | `Datasheets2018`; `ModelCards2019`; `DataCards2022` |
| `G7.rationale.criterion` | Every criterion needs a rationale tied to guide rules and user intent evidence. | Warn if criterion rationale only restates the method name. | Explain why criterion matches paired/leaderboard/regression/diagnostic structure. | `normative` | `Dror2018`; `ModelCards2019`; `HELM2022` |
| `G7.rationale.default` | Defaults without intent evidence must be labeled as defaults. | Warn if default values are presented as user-specific or statistically guaranteed. | Add `default` or `engineering_safeguard` provenance label. | `normative` | `Datasheets2018`; `DataCards2022` |
| `G7.rationale.hover` | UI hover text should be short, concrete, and cite the statistical reason. | Require hover-ready text for major fields. | Rewrite long literature explanations into actionable UI rationale. | `engineering_safeguard` | `ModelCards2019`; `DataCards2022` |
| `G7.rationale.future_judge` | Rationale entries should be structured so a future judge-based validator can score them. | Require fields: `rule_ids`, `intent_evidence`, `parameter`, `rationale`, `provenance`. | Add missing structured fields. | `engineering_safeguard` | `ModelCards2019`; `Datasheets2018` |
| `G7.doc.parameter_status_label` | Every major parameter must have provenance: `literature_backed`, `empirical_prior`, `default`, or `engineering_safeguard`. | Warn if provenance is missing or inconsistent with rule evidence status. | Add provenance field and caveat text. | `normative` | `Datasheets2018`; `ModelCards2019`; `DataCards2022` |
| `G7.doc.benchmark_card` | Advisor output should include benchmark-card style documentation: intended use, out-of-scope claims, assumptions, data quality, and known limitations. | Warn if export preview lacks documentation block. | Add benchmark-card block to export preview. | `methodological` | `Datasheets2018`; `ModelCards2019`; `DataCards2022`; `Raji2021` |
| `G7.rationale.repair_actionable` | Every warning/refusal must include an actionable repair suggestion. | Refuse invalid design only with failed criterion, statistical reason, and repair suggestion. | Add more tasks, change metric, narrow claim, add strata, add repeats, or downgrade to smoke test. | `normative` | `ProjectInterfaces2026`; `ModelCards2019`; `DataCards2022` |

Planner requirement: rationale text should explain why the choice follows from
the guide, not merely restate the chosen value. UI rationale should distinguish
what is known from literature, what is inferred from user intent, and what is an
engineering safeguard.

## Formula And Procedure Notes

These notes are intentionally short because the guide is consumed by a planner
and validator, not by a human statistics textbook. Stage 1 uses these formulas
for planning and warning thresholds. Stage 2 may later implement formal post-run
inference.

### Single pass-rate planning

Use only for rough single-score planning or UI intuition:

```text
SE(p_hat) = sqrt(p_hat * (1 - p_hat) / n)
```

Validator warning: do not use this as the primary final CI when `n` is small,
when `p_hat` is near 0 or 1, when tasks are clustered, or when the estimand is a
paired model delta.

### Wilson interval for a single success rate

For single binary success rate planning/reporting, prefer Wilson-style intervals
over naive Wald intervals:

```text
center = (p_hat + z^2 / (2n)) / (1 + z^2 / n)
half_width = z * sqrt(p_hat*(1-p_hat)/n + z^2/(4n^2)) / (1 + z^2/n)
CI = [center - half_width, center + half_width]
```

Validator warning: Wilson interval is for a single proportion, not a paired model
delta. For pairwise model selection, use paired task-level procedures.

### Paired bootstrap over tasks

Use for pairwise model selection when the same tasks are evaluated by both
models.

Procedure:

1. Store paired task-level outcomes `(y_A_i, y_B_i)`.
2. Resample task indices with replacement.
3. Recompute `delta = mean(y_A - y_B)` for each bootstrap sample.
4. Use bootstrap quantiles as a planning/reporting CI.

Validator warning: resample tasks, not attempts. If attempts are repeated on the
same task, preserve task grouping or use conservative effective-sample caveats.

### Stratified bootstrap

Use when the benchmark was generated by planned strata, such as category, chain
length, domain, cross-server, recovery, or distractor class.

Procedure:

1. Resample tasks within each declared stratum.
2. Preserve planned stratum weights or planned stratum counts.
3. Recompute score, deltas, ranks, and diagnostic rates.
4. Report aggregate uncertainty and relevant slice-level uncertainty.

Validator warning: if generation is stratified but analysis is unstratified, warn
that the analysis may not respect the design.

### Approximate randomization / permutation test

Use as a robust paired fallback when a p-value style decision rule is needed.

Procedure:

1. Compute observed paired delta.
2. Repeatedly flip model labels within each task under the null.
3. Recompute deltas under random flips.
4. Compare observed delta to the null randomization distribution.

Validator warning: only valid for paired outcomes with exchangeability under the
null.

### Rough MDE heuristic

For pre-run UI planning only:

```text
MDE ~= (z_(1-alpha/2) + z_(1-beta)) * sqrt(2 * p_hat * (1 - p_hat) / n_eff)
```

Validator warning: this is not a final inferential guarantee. It is approximate,
often conservative, and should be labeled `planning_heuristic`. When paired logs
exist, empirical bootstrap power curves are preferred.

### Effective sample size caveat

Repeated attempts, shared templates, shared servers, and correlated task clusters
reduce independent information. Do not treat `tasks * attempts_per_task` as iid
sample size.

Conservative planning cue:

```text
n_eff <= number_of_unique_tasks
```

If cluster correlation estimates exist, a design-effect style approximation may
be used as an empirical prior:

```text
n_eff ~= n / deff
```

Validator warning: label this as a heuristic unless calibrated on logs.

### Coverage distance

If a target deployment mix `Q` and proposed benchmark mix `P` are both available,
use per-stratum gaps and optionally total variation distance:

```text
TV(P, Q) = 0.5 * sum_i abs(P_i - Q_i)
```

Validator warning: TV thresholds are engineering safeguards unless calibrated.
The strongest warning is not the scalar distance itself, but undercoverage of a
user-declared primary stratum.

### Multiple comparisons

- Small, predeclared confirmatory family: use Holm-style family-wise control.
- Larger diagnostic/exploratory family: use Benjamini-Hochberg / FDR-style
  control or descriptive-only diagnostic reporting.
- Many slices without a family plan should trigger a warning.

Validator warning: never let all diagnostics become confirmatory by default.

## Good Rationale Examples

- Parameter: `task_distribution.cross_server_ratio = 0.35`
  - Rule ids: `G3.coverage.cross_server`, `G7.rationale.parameter`
  - Provenance: `engineering_safeguard`, or `empirical_prior` if calibrated.
  - Tooltip: "The request emphasizes cross-server composition, so the design
    allocates a substantial cross-server slice instead of ranking models only on
    single-server tasks. This supports an orchestration-specific claim, not a
    universal model claim."

- Criterion: `paired_bootstrap`
  - Rule ids: `G5.criterion.paired_bootstrap`, `G2.metric.pairwise_delta`
  - Provenance: `literature_backed`
  - Tooltip: "The primary question compares two models on the same planned task
    distribution, so task-level paired resampling is the planned comparison
    family."

- Warning: underpowered model-selection design
  - Rule ids: `G4.mde.underpowered`, `G4.mde.heuristic`, `G6.claim.confirmatory_vs_exploratory`
  - Tooltip: "With this budget, the design is unlikely to distinguish the small
    effect you asked for. Increase unique tasks, reduce confirmatory slices, or
    frame the run as a smoke test."

- Diagnostic slice: same-name tools
  - Rule ids: `G3.coverage.same_name`, `G3.distractor.claim_requires_pressure`, `G5.criterion.descriptive_diagnostic`
  - Tooltip: "Because the request asks about same-name tool confusion, the
    benchmark needs explicit same-name or near-miss distractors. Otherwise the
    design would not test the stated failure mode."

## Bad Rationale Examples

- "This is statistically valid because the advisor says so."
- "Model A will be better after this benchmark."
- "Public logs prove this private workflow result."
- "We use final answer accuracy as the primary metric."
- "The benchmark has 40 tasks and 3 attempts, so it has 120 independent samples."
- "The top-ranked model is universally best."
- "All diagnostic slices are confirmatory because they are interesting."

## Source Reference Map

These references are source anchors for the rule IDs above. Citation counts are
not encoded in this guide because they are unstable and should not be consumed by
the planner. If citation count is needed for a paper or report, compute it in a
separate human-facing literature review.

| source_key | Reference | Main use in guide | Status |
|---|---|---|---|
| `Dror2017` | Dror, Baumer, Shlomov, Reichart. 2017. Replicability Analysis for Natural Language Processing: Testing Significance with Multiple Datasets. TACL / arXiv:1709.09500. | Replicability, multiple datasets/slices, significance discipline. | peer-reviewed / methodological |
| `Dror2018` | Dror, Baumer, Bogomolov, Reichart. 2018. The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing. ACL / arXiv:1809.01448. | Choosing statistical tests for NLP/ML evaluation. | peer-reviewed / methodological |
| `Yeh2000` | Yeh. 2000. More Accurate Tests for the Statistical Significance of Result Differences. arXiv:cs/0008005. | Approximate randomization for paired system comparisons. | methodological |
| `Efron1979` | Efron. 1979. Bootstrap Methods: Another Look at the Jackknife. Annals of Statistics. | Bootstrap foundations. | peer-reviewed / foundational |
| `Brown2001` | Brown, Cai, DasGupta. 2001. Interval Estimation for a Binomial Proportion. Statistical Science. | Wilson and safer binomial intervals; avoid naive Wald default. | peer-reviewed / foundational |
| `Holm1979` | Holm. 1979. A Simple Sequentially Rejective Multiple Test Procedure. Scandinavian Journal of Statistics. | Multiple-comparison control for confirmatory families. | peer-reviewed / foundational |
| `BH1995` | Benjamini, Hochberg. 1995. Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing. JRSS B. | FDR control for larger diagnostic families. | peer-reviewed / foundational |
| `Henderson2018` | Henderson et al. 2018. Deep Reinforcement Learning that Matters. AAAI / arXiv:1709.06560. | Variance, power, reproducibility and reporting discipline. | peer-reviewed / methodological |
| `Colas2018` | Colas, Sigaud, Oudeyer. 2018. How Many Random Seeds? Statistical Power Analysis in Deep RL Experiments. arXiv:1806.08295. | Power/MDE planning intuition under expensive experiments. | preprint / methodological |
| `Bragg2021` | Bragg, Cohan, Lo, Beltagy. 2021. FLEX: Unifying Evaluation for Few-Shot NLP. NeurIPS Datasets and Benchmarks / arXiv:2107.07170. | Sample-size-aware evaluation and task heterogeneity. | peer-reviewed / methodological |
| `BenchmarkLottery2021` | Dehghani et al. 2021. The Benchmark Lottery. arXiv:2107.07002. | Benchmark as a sample from broader task distribution; rank instability. | preprint / methodological |
| `HELM2022` | Liang et al. 2022. Holistic Evaluation of Language Models. arXiv:2211.09110. | Scenario coverage, multi-metric evaluation, transparency. | widely used / methodological |
| `Dynabench2021` | Kiela et al. 2021. Dynabench: Rethinking Benchmarking in NLP. NAACL / arXiv:2104.14337. | Dynamic benchmark construction and adversarial/diagnostic challenge sets. | peer-reviewed / methodological |
| `CheckList2020` | Ribeiro, Wu, Guestrin, Singh. 2020. Beyond Accuracy: Behavioral Testing of NLP Models with CheckList. ACL / arXiv:2005.04118. | Diagnostic slices and behavioral failure-mode tests. | peer-reviewed / methodological |
| `Ethayarajh2020` | Ethayarajh, Jurafsky. 2020. Utility is in the Eye of the User: A Critique of NLP Leaderboards. EMNLP / arXiv:2009.13888. | User utility and limits of universal leaderboard claims. | peer-reviewed / governance |
| `Raji2021` | Raji et al. 2021. AI and the Everything in the Whole Wide World Benchmark. NeurIPS Datasets and Benchmarks / arXiv:2111.15366. | Construct validity, benchmark governance, overclaiming. | peer-reviewed / governance |
| `Datasheets2018` | Gebru et al. 2018. Datasheets for Datasets. arXiv:1803.09010. | Documentation of intended use, caveats, data provenance. | foundational / governance |
| `ModelCards2019` | Mitchell et al. 2019. Model Cards for Model Reporting. FAT* / arXiv:1810.03993. | User-facing reporting, intended use, limitations. | peer-reviewed / governance |
| `DataCards2022` | Pushkarna et al. 2022. Data Cards: Purposeful and Transparent Dataset Documentation. arXiv:2204.01075. | Structured documentation and decision provenance. | methodological / governance |
| `Northcutt2021` | Northcutt, Athalye, Mueller. 2021. Pervasive Label Errors in Test Sets Destabilize Machine Learning Benchmarks. NeurIPS / arXiv:2103.14749. | Label noise, benchmark ranking instability. | peer-reviewed / methodological |
| `Sainz2023` | Sainz et al. 2023. NLP Evaluation in Trouble: On the Need to Measure LLM Data Contamination for Each Benchmark. arXiv:2310.18018. | LLM benchmark contamination caveats. | preprint / governance |
| `Gururangan2018` | Gururangan et al. 2018. Annotation Artifacts in Natural Language Inference Data. NAACL / arXiv:1803.02324. | Dataset artifacts and shortcut warnings. | peer-reviewed / methodological |
| `Geirhos2020` | Geirhos et al. 2020. Shortcut Learning in Deep Neural Networks. Nature Machine Intelligence / arXiv:2004.07780. | Shortcut learning and overclaiming risks. | peer-reviewed / methodological |
| `Recht2019` | Recht, Roelofs, Schmidt, Shankar. 2019. Do ImageNet Classifiers Generalize to ImageNet? ICML / arXiv:1902.10811. | Test-set reuse, generalization under new test sets. | peer-reviewed / methodological |
| `ToolSandbox2024` | Lu et al. 2024. ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities. arXiv:2408.04682. | Stateful tool-use evaluation, intermediate milestones, executable effects. | recent preprint / agent-specific |
| `TauBench2024` | Yao et al. 2024. tau-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains. arXiv:2406.12045. | Repeated-trial reliability and pass^k-style agent evaluation. | recent preprint / agent-specific |
| `OSWorld2024` | Xie et al. 2024. OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments. arXiv:2404.07972. | Long-horizon real-environment execution evaluation. | recent preprint / agent-specific |
| `HumanEval2021` | Chen et al. 2021. Evaluating Large Language Models Trained on Code. arXiv:2107.03374. | pass@k repeated-sampling intuition. | preprint / methodological |
| `WebArena2023` | Zhou et al. 2023. WebArena: A Realistic Web Environment for Building Autonomous Agents. arXiv:2307.13854. | Functional correctness in multi-step web tasks. | recent preprint / agent-specific |
| `ToolTalk2023` | Farn, Shin. 2023. ToolTalk: Evaluating Tool-Usage in a Conversational Setting. arXiv:2311.10775. | Conversational tool use and external-effect tools. | recent preprint / agent-specific |
| `BowmanDahl2021` | Bowman, Dahl. 2021. What Will It Take to Fix Benchmarking in Natural Language Understanding? NAACL. | Benchmark saturation, floor/ceiling and validity critique. | peer-reviewed / governance |
| `McNemar1947` | McNemar. 1947. Note on the sampling error of the difference between correlated proportions or percentages. Psychometrika. | Paired binary comparison special case. | peer-reviewed / foundational |
| `CONSORT2010` | CONSORT 2010 statement and extensions for non-inferiority/equivalence trials. | Non-inferiority framing, predeclared margin, transparent reporting. | reporting standard / methodological |
| `SurveyDesignEffect` | Kish-style survey sampling design-effect methodology. | Effective sample size caveats for clustered or repeated observations. | foundational / methodological |
| `ProjectInterfaces2026` | `docs_benchmark_advisor/planning/INTERFACES.md`. | Project-level validator thresholds, response states, repair requirements, and v1 wire contracts. | project source / normative |
| `DynamicMCPBench2026` | DynamicMCPBench manuscript. 2026. Trace-grounded, effect-scored MCP benchmark substrate. | Project-specific invariants: deterministic replay, trace/effect scoring, public-log priors. | project source / domain-specific |

## Implementation Notes For Runtime Registry

- Keep existing rule families G1-G7.
- Add new rule IDs to the guide registry before planner output may cite them.
- Treat unknown rule IDs as validation errors, consistent with existing validator
  behavior.
- If downstream code assumes exact table column counts, use only the first
  original columns for parsing and treat added columns as metadata. A safer
  runtime parser should read rule IDs from the first column and ignore additional
  columns unless it explicitly needs them.
- If `INTERFACES.md` already defines a threshold, that threshold wins over any
  descriptive wording here.
- If a threshold is introduced here but not in `INTERFACES.md`, it must be
  labeled as `engineering_safeguard` or `empirical_prior` until frozen.
