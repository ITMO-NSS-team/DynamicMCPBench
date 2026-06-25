# T05 - Studio API

## Objective

Expose Benchmark Advisor design and validation endpoints in DMCP Studio.

## Dependencies

- T01
- T02
- T03
- T04
- T08

## Parallelization Group

M1-C.

## Scope

- Add `POST /api/advisor/design`.
- Add `POST /api/advisor/validate`.
- Compose planner, validator, and planning statistics.
- Return `AdvisorResponse`.
- Treat legacy `/api/advisor`, if retained, as compatibility only.

## Out Of Scope

- Frontend UI.
- Benchmark generation launch.
- Candidate scoring changes.
- CLI.

## Allowed Files/Directories

- `dmcp-studio/backend/**`
- Studio backend route tests
- minimal advisor API adapter if needed

## Forbidden Files

- `dmcp-studio/frontend/**`
- `dmcp/evaluator.py`
- `dmcp/cli.py`
- generation/evaluation orchestration files

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorValidationRequest`
- `AdvisorDesign`
- `AdvisorResponse`
- planner adapter public callable
- validator public callable
- planning-statistics public callable

## Interfaces Produced

- `POST /api/advisor/design`
- `POST /api/advisor/validate`
- backend response contract tests

## Required Tests

- Design route returns schema-valid response for golden request.
- Validate route returns schema-valid response for edited design.
- Tests call `/api/advisor/design` and `/api/advisor/validate` directly.
- Refused response includes refusal object.
- Clarification response includes clarification object and no export config.
- Warning response includes warning cards.
- Routes do not call generation/evaluation functions.

## Acceptance Criteria

- API contract matches `INTERFACES.md`.
- Planner output is always validated before response.
- API does not launch expensive eval or benchmark generation.
- A passing legacy `/api/advisor` test is not sufficient for T05.
- Existing Studio routes still pass.

## Integration Notes

T06 consumes the route. T09 verifies browser/API behavior together.

## Risks

- API bypasses validator.
- API shape drifts from frontend fixtures.
- Validate route receives a bare design and silently invents missing request
  metadata.

## Suggested Prompt For Implementation Agent

Wire Benchmark Advisor core to Studio backend routes. Return schema-valid
AdvisorResponse objects. Do not touch scoring and do not launch benchmark runs.
