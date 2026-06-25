# Benchmark Advisor Integration Plan

## Integration Strategy

Integrate through stable JSON contracts, not shared mutable implementation
details. Each implementation PR should consume `INTERFACES.md` and golden
fixtures. Planner and validator PRs must also consume `STATISTICAL_GUIDE.md`.
Cross-component integration happens only after core schemas, statistical guide,
fixtures, planner, validator, stats, API, UI, and export handoff are
independently tested.

## Stage 1 Integration Flow

1. UI sends `AdvisorRequest` to Studio API.
2. API runs planner adapter with the versioned statistical guide.
3. API runs deterministic validator.
4. API enriches response with planning statistics and export preview.
5. UI displays response.
6. UI shows hover/popover rationale for parameters and criteria using evidence
   ledger entries.
7. User edits numeric fields.
8. UI sends edited structured design in an `AdvisorValidationRequest` to the
   validation endpoint.
9. API validates edited design.
10. UI exposes JSON export only for approved/warning states.

## What Integration Must Not Do

- Do not launch `goal-gen`, `explore`, `distill`, `eval`, or paid LLM evals.
- Do not change candidate scoring behavior.
- Do not add final-answer grading.
- Do not bypass deterministic validation.
- Do not treat warning-heavy designs as claim-valid without showing warnings.
- Do not treat the legacy `/api/advisor` prototype route as sufficient for v1.
- Do not export configs for `refused` or `needs_clarification` responses.

## Cross-Component Contracts

- Backend and frontend use the same `AdvisorResponse` fixture shape.
- Export handoff validates `ExportConfig`, but does not execute it.
- Planner output must be validated before API returns it to UI.
- Planner output must include guide references and rationale entries for major
  proposed values.
- Validator must flag missing/unknown guide references.
- Validator accepts structured design only; raw intent interpretation belongs to
  planner.
- The validate route accepts `AdvisorValidationRequest`, not a bare design plus
  implicit context.
- The state matrix in `INTERFACES.md` defines when `design`, `refusal`,
  `clarification`, and `export_config` are null or non-null.

## Integration Checkpoints

- Fixture response renders in UI.
- Planner-generated response validates.
- User-edited response re-validates.
- Export preview validates.
- Refused design cannot be exported.
- Clarification response cannot be exported.
- Hover rationale renders for at least criteria, task budget, attempts, task
  distribution, and primary metric.
- Smoke test confirms no benchmark run is launched.

## Rollback Strategy

If integration fails late, keep the UI shell fixture-backed and disable live API
calls behind a visible "Advisor API unavailable" state. Do not remove validator
or schema tests to make UI pass.
