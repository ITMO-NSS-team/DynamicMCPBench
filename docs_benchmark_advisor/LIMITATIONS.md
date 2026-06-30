# Benchmark Advisor — limitations, allowed/disallowed claims (BA4.2 / T10)

The advisor is a **pre-run planning gate**, not an inference engine. Everything it
produces is a *planning heuristic* grounded in the versioned guide
`planning/STATISTICAL_GUIDE.md` (`statistical_guide.v1`). This page makes the
boundary explicit; the hardening tests in
`tests/test_benchmark_advisor_hardening.py` enforce it.

## What the advisor MAY claim

- That a planned design is **statistically defensible for the planned task
  distribution**, within the stated `claim_boundary`.
- A **planning MDE / CI width** as a heuristic (labeled `planning_heuristic`), to
  warn when a requested effect is below what the budget can detect.
- That a design needs **more tasks, more repeats, a larger detectable effect, or a
  smoke-test framing** — with the guide rule that motivates each.
- For diagnostics: a **descriptive slice failure rate**, scoped to that slice.

## What the advisor must NEVER claim

- That one model is **universally better** (`G6.claim.no_universal_best`).
- That the benchmark **represents unseen private deployments** or guarantees
  external validity (`G6.claim.no_external_validity`).
- That **public logs prove** private-server behavior — they are calibration
  priors only (`G6.claim.public_logs_prior`).
- That **final-answer matching** is a valid metric — scoring is effect-based, and
  the `primary_metric` enum cannot even express a final-answer metric
  (`G6.claim.no_final_answer`).
- That a **diagnostic slice** justifies a broad model-selection claim
  (`G6.claim.diagnostic_not_selection`).

A request that asks for any of the above is **refused** (final-answer →
`unsupported_final_answer_claim`; over-broad diagnostic → `cannot_support_claim`),
and refused/clarification designs **cannot export**.

## Sources of statistical knowledge (explicit)

- **Rules:** `planning/STATISTICAL_GUIDE.md`, families G1–G7, mirrored at runtime
  in `benchmark_advisor/guide.py` (a sync test keeps them identical).
- **Math:** reused from `dmcp` — `dmcp.curves.proportion_ci` (Wilson interval) and
  `dmcp.ablation.power_n` (two-proportion sample size). The advisor adds only the
  closed-form planning MDE on top, labeled a heuristic.
- The guide is a **static, curated v1** (decision D3), refreshed on 2026-06-27
  with evidence-status labels, source keys, and procedure notes. The guide
  version remains frozen so downstream citations stay stable.

## Known limitations (v1)

- **Planning heuristics, not inference.** The MDE/CI numbers assume a worst-case
  baseline (~0.5) and a two-proportion approximation. They size the gate; they are
  not a final power analysis. Consequence: realistic demo budgets (40–150 tasks)
  detect ~16–31pp, so small target effects are honestly refused.
- **Deterministic rule-based planner by default** (decision D1). It maps intent via
  keyword signals, not deep NL understanding; the LLM planner is a future LIVE-mode
  option behind the same interface. The deterministic validator is always the
  authority, so a weak proposal still gets caught.
- **Stage 2 is interface-only.** Post-run validation reports, outcome-tensor
  analytics, and judge-based rationale scoring are declared (`ValidationReportStub`,
  `implemented=false`, `stage_2_only=true`) but not implemented in v1.
- **No generation/evaluation launch.** The export is a dry-run JSON preview
  (`dry_run_only=true`); the advisor never runs `goal-gen`, `explore`, `distill`,
  or `eval`. A static import test enforces that the package can't reach those
  modules.

## V2 limitations and guardrails

V2 is allowed to close the v1 gaps, but it must keep these boundaries:

- **RAG is not authority.** Local retrieval and stat-agent proposals may explain,
  cite, and suggest alternatives. Deterministic rules still decide status,
  exportability, launchability, and report claim boundaries.
- **Post-run reports are scoped.** A `StatisticalReport` may state evidence for
  the completed outcome tensor only. It still must not claim universal model
  superiority or private-deployment external validity.
- **Guarded launch is corpus-only first.** The first v2 launch path may run
  corpus/specs/traces generation through `scripts/build_corpus.py` after explicit
  confirmation. Leaderboard/eval launch requires a separate approval and task.
- **All issues must be visible.** V2 can preserve the same status precedence as
  v1, but users should see every blocking warning/refusal and repair option.
- **No runtime web retrieval.** Statistical references must be local,
  reproducible, and human-approved before they influence UI explanations.
