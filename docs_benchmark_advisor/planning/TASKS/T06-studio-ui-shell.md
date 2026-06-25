# T06 - Studio UI Shell

## Objective

Add the first-stage Benchmark Advisor UI in DMCP Studio using frozen fixture/API
shape.

## Dependencies

- T01
- T03a
- T08

## Parallelization Group

M1-B.

## Scope

- Add Advisor stage before benchmark execution.
- Add natural-language intent box.
- Add numeric fields for task count, attempts, target detectable effect, and
  relevant distribution knobs.
- Render design cards, warning/refusal state, evidence ledger, and JSON preview.
- Render hover/popover rationale for criteria and major numeric parameters from
  evidence ledger entries.
- Add user approval/export affordance.

## Out Of Scope

- Backend route implementation.
- Advisor core logic.
- Slider controls.
- Launching generation/evaluation.

## Allowed Files/Directories

- `dmcp-studio/frontend/**`
- frontend fixture files if needed
- frontend tests/build config only if needed

## Forbidden Files

- `dmcp-studio/backend/**`
- `dmcp/**`
- generation/evaluation files

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorResponse`
- `EvidenceLedgerEntry`
- response state matrix
- golden fixture response JSON
- API route contract names

## Interfaces Produced

- First-stage Advisor UI.
- Fixture-backed rendering for approved, warning, refused, smoke-test-only
  states, plus needs-clarification state.
- Fixture-backed hover rationale for primary metric, criteria, task budget,
  attempts, and distribution fields.

## Required Tests

- Frontend build/typecheck if toolchain is available.
- UI fixture render smoke if test framework exists.
- Manual check that refused design cannot be exported.
- Manual check that needs-clarification design cannot be exported.
- Manual or fixture check that hover rationale appears for required fields.

## Acceptance Criteria

- UI does not invent fields outside `INTERFACES.md`.
- UI clearly distinguishes approved, warning, refused, needs-clarification, and
  smoke-test-only.
- UI uses numeric fields, not sliders.
- UI renders guide-backed rationale from the response instead of hardcoding
  statistical explanations.
- UI does not start benchmark generation.
- UI calls the v1 route names when live API mode is enabled.

## Integration Notes

Can be developed against fixture JSON before T05 lands. T09 connects it to live
API.

## Risks

- Frontend conflicts are likely because Studio has central entry files.
- UI may imply stronger claims than backend response allows.
- Tooltip text may become stale if it is hardcoded instead of read from the
  response.

## Suggested Prompt For Implementation Agent

Build the Advisor first-stage UI against the frozen fixture JSON and API shape.
Use numeric editable fields, render warnings/refusals and guide-backed hover
rationale, and do not change backend code.
