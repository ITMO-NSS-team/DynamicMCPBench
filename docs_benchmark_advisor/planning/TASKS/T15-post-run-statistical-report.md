# T15 - Post-Run Statistical Report

## Objective

Implement the v2 outcome-tensor report that turns completed benchmark results
into scoped statistical claims.

## Dependencies

- T11
- T14

## Scope

- Consume `OutcomeTensor` data for task, model, attempt, metric, and slice axes.
- Produce `StatisticalReport` for pairwise, leaderboard, regression
  non-inferiority, and diagnostic modes.
- Include effect sizes, confidence intervals, paired bootstrap or permutation
  method labels, rank stability, slice diagnostics, missingness, multiplicity
  notes, and allowed/not-allowed claims.
- Preserve claim boundaries and refusal/warning conventions.

## Out Of Scope

- Running benchmark generation or evaluation.
- Changing evaluator scoring.
- Judge-based qualitative scoring of explanations.

## Allowed Files/Directories

- advisor report/statistics modules
- v2 report fixtures
- report tests

## Required Tests

- Pairwise report computes scoped delta and CI.
- Leaderboard report computes rank stability.
- Regression report respects non-inferiority margins.
- Diagnostic report remains descriptive.
- Missing outcomes are explicit and affect report status.
- Multiplicity notes are present when multiple confirmatory slices exist.

## Acceptance Criteria

- Stage 2 is no longer only a stub for v2.
- The report states exactly what the completed benchmark can and cannot claim.
