# T11 - Statistical Advisor v2 Contract

## Objective

Define the v2 statistical-advisor schemas and API boundaries without breaking v1.

## Dependencies

- T01
- T10

## Scope

- Add v2 schema contracts for statistical planning and post-run reporting.
- Keep v1 `AdvisorRequest`, `AdvisorResponse`, and routes backward compatible.
- Define `StatisticalPlan`, `PowerAnalysis`, `DesignAlternative`,
  `AssumptionLedger`, `StatisticalIssue`, `OutcomeTensor`, and
  `StatisticalReport`.
- Define the v2 route shapes for design, validate, report, and guarded launch.
- Add a migration note explaining that v2 is additive.

## Out Of Scope

- Implementing the planner, RAG retrieval, report math, launch jobs, or Studio UI.
- Removing or renaming v1 fields or routes.
- Changing benchmark scoring.

## Allowed Files/Directories

- `benchmark_advisor/` schema modules
- `docs_benchmark_advisor/planning/INTERFACES.md`
- schema tests and fixture shape tests

## Interfaces Produced

- `POST /api/advisor/v2/design`
- `POST /api/advisor/v2/validate`
- `POST /api/advisor/v2/report`
- `POST /api/advisor/v2/launch`
- v2 schema-version strings, distinct from v1.

## Required Tests

- v2 schemas parse and reject unknown fields.
- v1 schemas and route tests still pass unchanged.
- v2 response state rules reject export/launch actions for refused and
  clarification states.
- v2 issue lists can carry multiple warnings/refusals.

## Acceptance Criteria

- Implementers can build BA5/BA6 work from typed contracts, not prose guesses.
- v2 explicitly includes effect sizes, confidence intervals, bootstrap or
  permutation method labels, missingness policy, multiplicity policy, claim
  boundary, and assumption ledger.
- v1 compatibility is tested.
