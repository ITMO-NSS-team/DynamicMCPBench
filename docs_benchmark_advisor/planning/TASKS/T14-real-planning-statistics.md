# T14 - Statistical Engine And Real Planning Statistics

## Objective

Implement the v2 Statistical Engine: a deterministic, rule-gated planning core
that searches, scores, and explains benchmark-design parameters before the v2
planner returns a final recommendation.

## Dependencies

- T04
- T11
- T03a

## Scope

- Add `STATISTICAL_ENGINE_DESIGN.md` as the implementation contract.
- Implement engine-owned candidate search over task budgets, attempts,
  detectable effects, task distributions, confirmatory slices, server scope,
  sandbox requirements, missingness policy, and multiplicity policy.
- Add explicit power curves, CI-width curves, and "what budget buys you"
  alternatives before the final design is selected.
- Add minimum detectable effect calculations by design type, including
  conservative pairwise planning, diagnostic slice precision, leaderboard
  rank-stability planning, and regression/non-inferiority margin planning.
- Surface paired vs unpaired assumptions, repeated-attempt dependence caveats,
  floor/ceiling risks, effective-sample-size caveats, and sensitivity branches.
- Add stratification coverage, per-slice task counts, rank-stability proxies,
  and sensitivity diagnostics.
- Include multiplicity and missingness policy in every planning output.
- Return cheap/recommended/stronger/narrowed-claim alternatives with concrete
  repair actions.
- Keep all assumptions explicit and guide-cited, while deterministic calculators
  and validators remain final authority.

## Out Of Scope

- Post-run inference from actual outcome tensors.
- Changing scoring or generation.
- Letting RAG/stat-agent prose decide approval or refusal.
- Requiring RAG/stat-agent or a separate retrieval corpus for MVP operation.
- Launching corpus generation or evaluation.

## Allowed Files/Directories

- advisor statistics modules
- v2 statistical fixtures
- tests for statistical calculations
- `docs_benchmark_advisor/planning/STATISTICAL_ENGINE_DESIGN.md`

## Required Tests

- Engine output is deterministic for fixed request, guide snapshot, config, and
  random seed.
- Candidate grid is finite, includes required alternatives, and records rejected
  candidate reasons.
- Power/MDE curves are monotonic and reproducible.
- Paired and unpaired planning assumptions are distinguishable.
- Rank-stability and slice-coverage diagnostics are deterministic.
- Sensitivity outputs include assumptions and do not overclaim.
- Attempts per task do not multiply iid sample size for MDE/CI calculations.
- Regression mode refuses missing non-inferiority margin.
- Diagnostic-only designs refuse broad model-selection claims.
- Missingness and multiplicity policies appear in every plan.
- Guide snippet/citation text can change explanations but not deterministic
  status.

## Acceptance Criteria

- `POST /api/advisor/v2/design` can be composed so the Statistical Engine runs
  before the final v2 design is returned.
- Users can inspect why a design was selected, which alternatives were rejected,
  why a design is underpowered, what budget would repair it, and which claim
  remains allowed.
- Outputs are strong enough to be the central advisor feature, not decorative
  numbers: task budget, attempts, target effect, distribution, confirmatory
  slices, method family, assumptions, and repairs are engine-derived and
  rule-gated.
