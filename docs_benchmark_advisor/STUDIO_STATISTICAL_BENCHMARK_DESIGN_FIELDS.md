# Statistical benchmark design: explanation of Studio fields

This document explains the fields shown on the **Statistical benchmark design**
page in DMCP Studio.

The page is Stage 0 of Benchmark Advisor v2. Its job is not to run a benchmark.
It turns a user's benchmark question into a statistically scoped design, validates
that design, shows what claim the design can and cannot support, and previews the
shape of the post-run statistical report.

## Mental model

The page has two different layers:

1. **Planning request** is the user's input. These fields describe what the user
   wants the advisor to plan.
2. **Editable statistical plan** is the advisor's structured output. These
   fields describe the actual statistical design that would be validated and
   carried forward.

The distinction matters because the advisor may transform the request. For
example, the user can request 120 tasks, but the engine may recommend a different
budget if the requested claim is underpowered. The request says "what I want";
the plan says "what the statistical engine currently believes is defensible".

## Page header

### Stage 0 - Statistical Advisor v2

Identifies this as the v2 statistical advisor surface. It is a pre-run planning
stage. It is upstream of Collect and of any actual corpus generation.

### Statistical benchmark design

The page title. "Design" means benchmark design, not completed benchmark results.
The page shows claim scope, method choice, power heuristics, assumptions, repairs,
citations, and the report shape before the benchmark moves forward.

## Planning request

This panel is the input sent to `/api/advisor/v2/design`.

### Free-text planning request

Example default:

```text
Compare two local agents on long, multi-step finance workflows and tell me which is better.
```

This is the user's natural-language intent. The planner reads it to infer the
evaluation question, claim scope, task distribution, and statistical mode.

Use this field for the actual benchmark question, not for low-level statistical
parameters. Examples:

- "Compare model A and model B on long finance workflows."
- "Check whether the new agent regressed versus the current production agent."
- "Diagnose failures on same-name tools and wrong-server calls."

### advisor mode

Allowed values:

- `pairwise`
- `leaderboard`
- `regression`
- `diagnostic`

This tells the advisor what family of benchmark question to plan.

`pairwise` compares exactly two candidate models or agents on the same planned
task distribution. It is for "which of these two is better?" questions.

`leaderboard` ranks three or more models. It needs rank-stability caveats because
small benchmark samples can make ranks unstable.

`regression` is for non-inferiority or "did the new version get worse?" checks.
It needs a predeclared margin, represented in the UI as target effect.

`diagnostic` describes a failure mode or slice. It is usually exploratory unless
the slice is predeclared, powered, and handled with a multiplicity plan.

### candidate models

Comma-separated model or agent identifiers. Studio parses this into a list.

For `pairwise`, exactly two models are required. For `leaderboard`, at least
three models are expected. For `regression`, the intended meaning is baseline
then candidate.

### server scope

Comma-separated server or tool-domain identifiers. This constrains the planned
benchmark to the named server scope.

Example:

```text
finance-tools
```

This is separate from candidate models. Candidate models are the systems being
evaluated; server scope is the tool environment or domain they are evaluated on.

### requested task budget

The number of unique tasks the user asks for. In the UI this is a slider.

Important: repeated attempts do not multiply this number for statistical power.
The advisor treats unique tasks as the main inference unit. A design with 120
tasks and 3 attempts per task is not treated as 360 independent tasks.

### requested attempts / task

How many attempts each model gets per task. This is useful for reliability-style
questions, such as pass@3 or consistency, but it does not create independent new
tasks.

If the claim is model selection, increasing unique task budget usually matters
more than increasing attempts per task.

### requested target effect

The minimum effect size the user wants to be able to detect, in percentage
points. In the API this is `target_detectable_effect_pp`.

If the slider is `0`, Studio sends `null`, which means "let the statistical
engine choose/use its default planning heuristic".

Interpretation examples:

- `5 pp` means "I care about detecting a 5 percentage point difference."
- `15 pp` means "a larger difference is acceptable as the practical resolution."
- `engine default` means the advisor estimates the detectable effect from the
  task budget and baseline assumptions.

For `regression`, this field is also the non-inferiority margin. That margin must
be declared before seeing outcomes; otherwise the regression claim is not
statistically defensible.

### sandbox required

Boolean toggle in the planning request.

This means the user says the benchmark requires sandboxed execution. It is
especially important for stateful-write tasks, external side effects, or tool
calls that can modify state.

If stateful-write coverage is planned but sandbox is not required, the validator
can refuse or warn because unsafe side effects would make export/launch
inappropriate.

## Advisor verdict

This panel summarizes the current v2 design response.

### status

The response status. Possible values are:

- `approved`
- `warning`
- `refused`
- `needs_clarification`

`approved` means the design is launchable for the scoped claim.

`warning` means there is a usable design, but caveats or repairs must stay
visible. For example, the benchmark may be underpowered for a small effect.

`refused` means the current request or edited plan cannot support the requested
claim. Critical issues must be repaired before moving forward.

`needs_clarification` means the advisor cannot choose a defensible design until
the user supplies missing information, such as the primary objective.

### issue count

The number of open v2 issues returned by the advisor. These are expanded in
**Issues and repairs**.

### verdict card text

The large verdict card shows the plain-language summary from the claim card when
a statistical plan exists. If no plan exists, it shows the first issue message or
a waiting message.

This is the fastest read of "what the advisor currently thinks this design can
support".

### tasks

The selected plan's `design.task_budget`: number of unique tasks in the current
statistical plan.

This may differ from the requested task budget because the engine searches
candidate budgets and may recommend a defensible alternative.

### attempts

The selected plan's `design.attempts_per_task`.

This is shown next to tasks so the user can see the difference between unique
task count and repeated attempts.

### planned MDE

Minimum detectable effect, in percentage points, estimated for the current plan.

This is a pre-run planning heuristic, not a guarantee about the final benchmark.
It answers: "roughly how large a difference can this design resolve under the
current assumptions?"

### CI width

Estimated confidence interval width, in percentage points, for the current plan.

This is also a planning heuristic. Smaller width means higher precision. It is
driven mostly by unique task budget, baseline rate assumptions, and mode.

### launchable

`yes` if the advisor response says the design can be carried forward; `no` if it
is refused or otherwise not launchable.

The Studio button **Carry this design into Collect** is enabled only when the
response is launchable and not refused.

## Editable statistical plan

This panel appears after the advisor has produced a `StatisticalPlan`.

Every edit calls `/api/advisor/v2/validate`. That means the UI is not just
changing local text; it asks the backend to revalidate the edited plan and update
status, issues, assumptions, power fields, alternatives, and citations.

### Difference from Planning request

The **Planning request** is the user's requested input. The **Editable
statistical plan** is the advisor's current structured design.

The plan can differ from the request because it is engine-selected and
validator-checked. It contains fields that downstream export/reporting can use,
such as task distribution, criteria, power analysis, assumptions, claim
boundaries, and issue repairs.

Editing the plan means "try this changed statistical design and revalidate it".
Editing the request means "ask the advisor to plan again from a different user
request".

### plan models

The candidate models inside the selected plan. Editing this changes
`design.candidate_models`.

The validator checks whether the model count fits the selected mode. For example,
`pairwise` with one or three models is invalid.

### plan server scope

The server scope used when validating the current plan. It is part of the
original request passed alongside the plan during validation.

Changing this does not directly mutate the plan's internal `AdvisorDesign`;
instead, Studio revalidates the current plan against an updated request context.

### plan task budget

The selected plan's unique task budget. Editing it changes
`design.task_budget`.

Increasing this usually improves MDE and CI width. Decreasing it may downgrade
the design to warning or refused if the claim becomes underpowered.

### plan attempts / task

The selected plan's attempts per task. Editing it changes
`design.attempts_per_task`.

This can matter for reliability metrics, but the advisor still treats unique
tasks as the main information unit for model-selection power.

### plan target effect

The selected plan's `design.target_detectable_effect_pp`.

If the value is `0`, Studio writes `null`, meaning "not set". If it is positive,
it is interpreted as percentage points.

For regression/non-inferiority mode, this is the predeclared margin. For other
modes, it is the requested detectable effect that the engine compares against
planned MDE.

### plan sandbox required

Boolean toggle used during validation of the edited plan.

This mirrors the planning-request sandbox flag, but it belongs to the validation
context for the current plan. The distinction is useful because a user may first
ask for a plan, then discover that the plan includes stateful-write work and
toggle sandbox before carrying the design forward.

### task distribution

This section edits the planned mix of task properties. Values are ratios in
`[0, 1]` and the UI displays them as percentages.

These fields are not necessarily mutually exclusive. A task can be long-chain
and cross-server, or recovery-required and stateful-write. So the sliders are
coverage ratios, not a single partition that must sum to 100%.

#### short chain

Planned ratio of short workflow tasks. These cover shorter, simpler tool-use
chains.

High short-chain coverage supports claims about short workflows. It does not by
itself support long-horizon or production workflow claims.

#### medium chain

Planned ratio of medium workflow tasks. This is the bridge/default coverage for
mixed workflow claims.

Removing medium-chain coverage can make a benchmark too narrow if the user wants
general multi-step workflow competence.

#### long chain

Planned ratio of long, multi-step workflow tasks.

This should be high when the user asks about long workflows, production-like
multi-step tasks, or long-horizon tool use. Low long-chain coverage can trigger
warnings for long-workflow claims.

#### cross-server

Planned ratio of tasks requiring cross-server composition or orchestration.

This matters when the user asks about multi-server workflows, wrong-server risks,
or orchestration. Low cross-server coverage weakens orchestration claims.

#### recovery

Planned ratio of tasks requiring recovery from errors, retries, or repair.

This supports robustness/recovery claims. If the user asks about recovery but
this ratio is near zero, the advisor should warn or refuse the claim.

#### prerequisite

Planned ratio of tasks with strict prerequisites.

These are tasks where earlier steps must be done correctly before later steps
make sense. They stress dependency handling and workflow ordering.

#### stateful write

Planned ratio of tasks that write or mutate state.

This is the most safety-sensitive distribution field. Stateful-write tasks
usually require sandboxing, reset/replay policy, and careful launch controls.

## Claim card

The claim card explains what the current plan can and cannot claim.

### claim scope

Shown in the panel subtitle. It comes from `design.claim_scope`.

Common values include:

- `confirmatory_model_selection`
- `leaderboard_ranking`
- `regression_non_inferiority`
- `diagnostic_slice`
- `smoke_test_only`

Claim scope is the statistical boundary of the design. It prevents the UI from
presenting a narrow diagnostic or smoke test as a broad model-selection result.

### plain-language summary

Human-readable summary from `claim_card.plain_language_summary`.

This is the concise explanation of the current plan's status and claim. It is
also reused in the advisor verdict summary.

### Allowed

List of claims the current design is allowed to support.

Example:

```text
Scoped pairwise difference on the planned task distribution using paired task-level outcomes.
```

"Allowed" does not mean the benchmark has already proved the claim. It means
that if the benchmark is run according to this design and produces suitable
outcomes, this is the type of claim the report may make.

### Not allowed

List of claims the design must not support.

Common examples:

- universal best-model claim
- unseen private-deployment guarantee
- exact final ranking
- post-hoc non-inferiority margin

This section is important because many benchmark results are easy to overstate.
The advisor makes the boundary explicit before the benchmark is run.

## Method card

The method card summarizes the statistical method family and engine trace.

### alpha

The significance level from the primary criterion. The default request sends
`0.05`.

It is a planning parameter for confirmatory inference. Lower alpha means a more
stringent false-positive threshold.

### target power

The target power from the primary criterion. The request sends `beta = 0.2`,
which corresponds to target power `0.8`.

Power is the probability of detecting an effect of the target size under the
planning assumptions.

### method

The primary criterion's `test_family`.

Possible method families include:

- `paired_bootstrap`
- `two_proportion_wilson`
- `non_inferiority_margin`
- `rank_stability_bootstrap`
- `diagnostic_descriptive`

This is the intended analysis family, not just a label. It determines what data
shape is needed and what claim is defensible.

### engine candidates

Number of candidate designs the deterministic statistical engine considered.

For the initial design route, this can be multiple budget/attempt candidates.
For edited-plan validation, this may be `1` because the backend refreshes the
single edited design rather than running a full recursive search.

### formula tags

Tags from the engine computation trace, such as:

- `planned_mde_pp.unique_tasks.v1`
- `paired_task_delta.v1`
- `ci_width_pp.v1`
- `validator.v1`
- `v2.validate.refresh`

These identify which internal formula/procedure versions were used. They are
provenance markers for reproducibility and debugging.

## Power curve

The power curve panel shows budget alternatives for unique-task planning.

### task budget

Each row is a possible unique-task budget.

The rows usually include the current budget, lower/higher budgets, and stronger
mode-specific budgets.

### MDE

Minimum detectable effect in percentage points for that task budget.

As task budget increases, MDE usually decreases, meaning the design can resolve
smaller effects.

### CI

Estimated confidence interval width in percentage points for that task budget.

This is a pre-run precision estimate. It is not a final interval from completed
data.

### unique-task planning

The panel subtitle reminds the user that power is planned over unique tasks, not
over attempts multiplied by tasks.

## Assumptions

The assumptions panel shows the assumption ledger used by power and claim
planning.

### paired / unpaired

Shown in the panel subtitle.

`paired` means the design expects the same tasks to be evaluated by the compared
models, enabling paired task-level deltas. Pairwise and regression designs are
paired.

`unpaired` means the mode does not require a two-model paired delta, such as
leaderboard or diagnostic designs.

### baseline rate

Assumed baseline success/pass rate used in MDE and CI planning.

The backend default is a planning prior. It can also come from
`user_overrides.baseline_rate` if supplied through the API. The current Studio UI
does not expose a direct baseline-rate input, so the visible value is usually the
engine default.

This value matters because binary-outcome uncertainty is largest around a 50%
rate and smaller near 0% or 100%. Very low or very high baseline rates can create
floor/ceiling concerns.

### independence

Text describing the independence assumption.

The current engine states that unique tasks are the iid planning unit and that
effective sample size may be smaller for shared templates, servers, tools, or
trajectories.

This is a warning against treating correlated tasks or repeated attempts as
fully independent evidence.

### attempts

Text describing how repeated attempts are handled.

The current policy is that attempts can support reliability metrics but do not
multiply unique-task power.

### missingness

Text describing how missing outcomes must be represented for post-run reporting.

The current policy is explicit null-with-reason reporting: if an outcome is
missing, it should be recorded as `null` with a reason. Missing cells weaken or
can block post-run claims.

### multiplicity

Text describing how multiple tests/slices are handled.

The current policy is single primary criterion by default, Holm-style correction
for small confirmatory families, and exploratory treatment for diagnostics unless
they are predeclared and budgeted.

### sensitivity notes

Additional notes generated by the engine. They can include:

- baseline-rate sensitivity branches
- reminder that attempts do not multiply power
- public logs are priors only
- `n_eff <= unique task_budget`
- leaderboard rank-resolution proxy
- diagnostic slice task counts and CI widths

These notes are there to expose the fragility of the design assumptions.

## Alternatives

This panel shows alternative designs found by the engine.

### options count

Panel subtitle showing how many alternatives are available.

The engine currently emits alternatives such as budget minimum, recommended,
stronger, and narrowed claim.

### status

Status of the alternative: `approved`, `warning`, `refused`, or
`needs_clarification`.

This lets the user see whether a cheaper or stronger option changes claim
defensibility.

### label

Human-readable alternative label, for example:

- Budget minimum
- Recommended
- Stronger
- Narrowed claim

### tradeoff

Short explanation of what the alternative buys or sacrifices.

Example: a stronger alternative may require more tasks but lower the planned MDE.

### task budget x attempts

Shown as:

```text
task_budget x attempts_per_task
```

This compactly displays the run size for the alternative.

## Issues and repairs

This panel lists all current statistical issues.

### severity

Issue severity. Values include:

- `info`
- `warning`
- `critical`

Warnings preserve a launchable design only if the overall status allows it.
Critical issues normally produce `refused`.

### failed field / failed criterion

The UI shows either `failed_field` or `failed_criterion_id`.

`failed_field` points to a structural field such as `candidate_models` or
`target_detectable_effect_pp`.

`failed_criterion_id` points to a statistical criterion, usually the primary
criterion.

### code

Stable machine-readable issue code.

Examples:

- `unsupported_candidate_model_count`
- `missing_non_inferiority_margin`
- `underpowered_design`
- `insufficient_long_chain_coverage`
- `missing_diagnostic_pressure`

Use the code when writing tests or debugging backend behavior. Use the message
for human-facing explanation.

### message

Human-readable description of the problem.

### statistical reason

Why the issue matters statistically.

This is more specific than the message. For example, a pairwise model-count
issue matters because paired task-level comparisons need one A/B candidate pair.

### repair options

Actionable fixes. Examples:

- increase tasks
- narrow the claim
- use exactly two candidate models
- predeclare a non-inferiority margin
- add sandboxing
- add diagnostic pressure

The advisor should not refuse a design without saying how to repair it.

## Citations

This panel shows local statistical-guide citations that support the current
design.

### local guide cards count

Panel subtitle showing how many citation cards are attached to the plan.

These citations come from the local `STATISTICAL_GUIDE.md`, not from runtime web
retrieval.

### source id

Stable citation identifier, usually tied to a guide rule or source card.

### section

The guide section the citation comes from, such as:

- G1 - Intent To Mode
- G2 - Estimand And Metric Selection
- G3 - Task Distribution
- G4 - Budget, Power, And Repeats
- G5 - Criterion Selection
- G6 - Claim Boundaries
- G7 - Rationale And UI Explanation

### snippet

Short quoted or paraphrased guide snippet shown in the citation card.

### source keys

Compact source/provenance tags, such as `Dror2018`, `Efron1979`,
`BenchmarkLottery2021`, `ToolSandbox2024`, or `DynamicMCPBench2026`.

These are evidence anchors. They are not live links and not runtime retrieval.

## Post-run report view

This is the most easily misunderstood panel.

### What it is

The post-run report view previews the shape of the Stage 2 statistical report:
what Studio expects to show after a benchmark has actually been run and outcomes
exist.

It is built from the v2 `StatisticalReport` contract. That report consumes an
`OutcomeTensor`, whose shape is:

```text
X[task, model, attempt, metric, slice]
```

The report turns completed outcomes into scoped statistical claims, effect
sizes, confidence intervals, missingness summaries, multiplicity notes, and
allowed/not-allowed report claims.

### What it is not

On the current Statistical benchmark design page, this panel is not evidence
from a real completed benchmark run.

The frontend currently builds a small fixture outcome tensor from the current
plan and sends it to `/api/advisor/v2/report`. That is why the panel can appear
before Collect has run anything.

So read it as:

```text
"If this plan later has outcomes, this is the kind of report Studio will show."
```

Do not read it as:

```text
"The benchmark has already run and these are real results."
```

### report mode

Panel subtitle showing the report mode, such as `pairwise`, `leaderboard`,
`regression`, or `diagnostic`.

If the report is built with a statistical plan, the mode comes from
`statistical_plan.design.mode`. Without a plan, the backend can infer mode from
the outcome tensor.

### status

Report status after analyzing the outcome tensor.

This is separate from the pre-run design status. A design can be approved before
the run, but the post-run report can still warn or refuse if outcomes are
missing, invalid, or insufficient for the requested claim.

### missing

Number of missing outcome cells.

Missing cells include explicit `null` outcomes and absent expected tensor cells.
Missing outcomes reduce effective information. If all outcomes are missing, no
post-run statistical claim is possible.

### confirmatory

Number of confirmatory tests in the report.

Confirmatory tests are predeclared tests that can support stronger claims if the
design and multiplicity plan allow it.

### exploratory

Number of exploratory tests or slices.

Exploratory diagnostics can be useful, but they should not be promoted to
confirmatory claims after inspecting the results.

### Effect sizes

List of estimated effects.

For `pairwise`, the report computes a paired task-level delta, shown as:

```text
candidate - baseline: N pp (paired_task_delta)
```

For `leaderboard`, it shows model pass rates. For diagnostic mode, there may be
no effect sizes because the report is descriptive by slice.

### Confidence intervals

List of uncertainty intervals.

For pairwise/regression reports, the backend uses paired bootstrap over tasks.
For leaderboard pass rates, it uses Wilson intervals.

The interval is computed from observed post-run outcomes. In the current UI
preview, the observed outcomes are only the fixture tensor.

### rank stability

Shown when the report mode supports leaderboard-style rank stability.

The backend bootstraps tasks and reports how often the top-k set is retained.
This helps avoid overclaiming exact ranks from noisy benchmark samples.

### multiplicity

Text note explaining how multiple confirmatory/exploratory tests are handled.

Examples:

- one primary confirmatory test, no correction needed for the primary claim
- multiple confirmatory slices require Holm-style correction
- no confirmatory tests, diagnostics are descriptive

### Report claims

Claims the completed outcome tensor supports.

These are post-run claims, not pre-run plan claims. They depend on actual
outcomes, missingness, model count, mode, and uncertainty.

### Report boundaries

Claims the completed report must not make.

Examples:

- universal best-model claim
- exact final ranking without uncertainty
- pairwise superiority without a predeclared multiplicity plan
- unseen private-deployment guarantee

This mirrors the pre-run claim-boundary idea, but at report time.

## Export preview

This collapsed panel shows the typed dry-run export configuration when the design
is exportable.

### typed dry-run config

If available, the panel contains JSON from `export_config`.

Important: this is a dry-run config. It previews the handoff target and
generation knobs; it is not itself a completed launch.

### unavailable

If the design is refused or needs clarification, export config is unavailable.

The panel then shows:

```text
- no export (design refused or needs clarification)
```

## Carry this design into Collect

This button moves Studio from Design to Collect.

It is enabled only when:

- `response.launchable` is true
- response status is not `refused`

Moving to Collect does not mean the post-run report is real yet. It only carries
the approved or warning-level design into the next stage.

## Common interpretation mistakes

### Planning MDE is not final proof

Planned MDE and CI width are pre-run heuristics. Final uncertainty comes from
the completed outcome tensor.

### Attempts are not independent tasks

`tasks = 120` and `attempts = 3` does not mean `n = 360` independent samples.
Repeated attempts can support reliability metrics, but unique tasks remain the
main planning unit.

### Diagnostic does not mean confirmatory

Diagnostic slices are useful for understanding failure modes. They should not be
treated as broad model-selection evidence unless they were predeclared, powered,
and handled with multiplicity control.

### Post-run report view is currently a preview

The panel shows the report contract and behavior using a generated fixture from
the current plan. It is not a real benchmark result until Studio wires it to
completed run artifacts/outcomes.

