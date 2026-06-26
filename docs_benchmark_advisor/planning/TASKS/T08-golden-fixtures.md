# T08 - Golden Fixtures

## Objective

Create shared golden fixtures for schema, planner, validator, API, UI, and
integration tests.

## Dependencies

- T00
- T03a

## Parallelization Group

M1-A.

## Scope

- Add `docs_benchmark_advisor/fixtures/` for advisor requests/responses.
- Cover valid, warning-heavy, refused, smoke-test-only, and clarification
  scenarios.
- Include guide-backed rationale/evidence ledger examples for UI and validator
  tests.
- Keep fixtures realistic and demo-friendly.

## Out Of Scope

- Runtime implementation.
- Planner/validator/statistics logic.
- UI/API code.

## Allowed Files/Directories

- `docs_benchmark_advisor/fixtures/**`
- fixture README
- fixture loading tests if schema exists

## Forbidden Files

- runtime modules except fixture tests
- Studio frontend/backend
- generation/evaluation files

## Interfaces Consumed

- `INTERFACES.md` fixture format
- `AdvisorRequest`
- `AdvisorResponse`
- `StatisticalGuideReference`
- `STATISTICAL_GUIDE.md` rule ids
- enum registries and response state matrix

## Interfaces Produced

- At least 10 golden fixtures.
- Fixture inventory/README.
- Guide-backed rationale entries for non-refused/non-clarification examples.

## Required Tests

- After T01, fixtures parse against schema.
- Before T01, manually validate all required fixture fields exist.
- Every referenced guide rule id exists in `STATISTICAL_GUIDE.md`.

## Acceptance Criteria

Fixtures include:

- pairwise finance valid design;
- leaderboard warning design;
- regression-testing design;
- same-name/wrong-server diagnostic design;
- underpowered refusal;
- too-few-repeats warning;
- low cross-server coverage warning;
- smoke-test-only design;
- ambiguous intent needing clarification;
- edited numeric-field validation.
- final-answer-grading refusal;
- missing-generation-knobs invalid export.
- guide-backed rationale / hover explanation.
- pairwise short finance workflow with hard-negative / similar-name distractor
  pressure, matching the Studio demo regression query.

## Integration Notes

All implementation tasks should use these fixtures instead of inventing local
wire shapes.

## Risks

- Fixtures become too demo-specific.
- Multiple contributors editing one large fixture file may conflict.
- Fixtures accidentally encode the legacy `/api/advisor` response shape.
- Fixture rationale may cite guide ids without explaining the actual parameter
  choice.

## Suggested Prompt For Implementation Agent

Create shared advisor golden fixtures according to `docs_benchmark_advisor/planning/INTERFACES.md`.
Include guide-backed rationale entries from `STATISTICAL_GUIDE.md`. Do not
implement runtime behavior.
