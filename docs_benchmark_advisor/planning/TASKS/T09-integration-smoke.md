# T09 - Integration Smoke

## Objective

Verify that core schema, planner, validator, statistics, Studio API, UI, and
export preview work together from intent to export.

## Dependencies

- T05
- T06
- T07
- T08

## Parallelization Group

M2.

## Scope

- Add the smallest end-to-end smoke test.
- Verify API/UI/export use the same wire shape.
- Confirm no generation/evaluation launch occurs.

## Out Of Scope

- Broad refactors.
- New feature scope.
- Stage-2 validation report implementation.

## Allowed Files/Directories

- integration tests
- smoke scripts
- minimal docs updates
- narrow bug fixes required for smoke pass

## Forbidden Files

- schema-breaking changes without human approval
- scoring/evaluator behavior changes
- generation algorithm changes

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorValidationRequest`
- `AdvisorResponse`
- `ExportConfig`
- Studio API routes
- UI fixture/API shape

## Interfaces Produced

- End-to-end smoke test or script.
- Integration checklist result.

## Required Tests

- Backend route smoke.
- UI render/build smoke.
- Export config validation.
- Negative smoke: refused design is not exportable.
- Negative smoke: needs-clarification design is not exportable.
- Route smoke calls `/api/advisor/design` and `/api/advisor/validate`.

## Acceptance Criteria

- Demo scenario produces approved or warning `AdvisorResponse`.
- UI can show that response.
- Export preview validates.
- No benchmark run is launched.
- Legacy `/api/advisor`, if present, is not the only advisor route exercised.
- Existing Studio smoke tests still pass.

## Integration Notes

This task is the first place where late interface mismatch should be fixed. Keep
fixes minimal and avoid broad cleanup.

## Risks

- Late mismatch between UI fixture and API response.
- Hidden dependency on unavailable frontend tooling.

## Suggested Prompt For Implementation Agent

Add the smallest integration smoke proving Benchmark Advisor works from intent
to export preview across landed components. Do not add new feature scope.
