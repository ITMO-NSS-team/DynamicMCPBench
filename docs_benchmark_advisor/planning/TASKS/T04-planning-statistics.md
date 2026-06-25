# T04 - Planning Statistics

## Objective

Provide deterministic Stage-1 planning statistics and coverage diagnostics.

## Dependencies

- T01

## Parallelization Group

M1-B.

## Scope

- Implement rough CI width estimates.
- Implement MDE/power planning heuristic.
- Implement task-budget to MDE curve.
- Implement coverage diagnostics for planned task distributions.
- Mark outputs as planning heuristics.

## Out Of Scope

- Stage-2 post-run validation report.
- Outcome tensor analytics.
- Studio UI/API.
- Planner and validator orchestration.

## Allowed Files/Directories

- advisor statistics module
- `tests/test_benchmark_advisor_stats.py`

## Forbidden Files

- Studio frontend/backend
- planner/validator files except imported schemas
- report-generation files

## Interfaces Consumed

- `TaskDistribution`
- `AnalysisPlan`
- `Criterion`

## Interfaces Produced

- Planning-statistics result object or fields consumed by `AdvisorResponse`.
- Deterministic coverage diagnostic outputs.
- Planned MDE values used by the validator threshold table.

## Required Tests

- MDE decreases as task count increases.
- CI width decreases as task count increases.
- Coverage diagnostics warn when planned distribution misses target coverage.
- Same input produces same output.
- Outputs are labeled as planning heuristics.
- Boundary values are stable enough for validator tests to assert exact
  warning/refusal behavior.

## Acceptance Criteria

- No final inference claims.
- No dependence on live benchmark outcomes.
- No expensive network/model calls.
- Outputs do not imply Stage-2 outcome analytics.

## Integration Notes

T05 includes these fields in API responses. Stage-2 analytics remain only
`ValidationReportStub` in v1.

## Risks

- Users may read rough MDE as final inferential guarantee.
- Stats helpers may duplicate existing repo utilities instead of reusing them.

## Suggested Prompt For Implementation Agent

Implement only pre-run planning statistics and coverage diagnostics. Label all
approximate outputs as planning heuristics. Do not implement post-run validation
reports.
