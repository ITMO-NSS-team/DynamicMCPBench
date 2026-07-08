# T16 - Statistical Advisor UI v2

## Objective

Make Studio present the advisor as a statistical workbench, not just a verdict
card and JSON preview.

## Dependencies

- T11
- T13
- T14
- T15

## Scope

- Render claim card, power curve, method card, assumptions panel, alternatives,
  repair actions, citations, and post-run report view.
- Replace weak frontend advisor schemas with typed v2 zod schemas.
- Support structured edits for budget, attempts, models, server scope, effect
  target, distribution, and sandbox.
- Call v2 validate after edits and show all issues.
- Keep v1 UI behavior working during migration.

## Out Of Scope

- Launching corpus generation; that belongs to T17.
- Redesigning unrelated Studio stages.

## Allowed Files/Directories

- `dmcp-studio/frontend/src/`
- Studio frontend tests
- advisor API schemas used by the frontend

## Required Tests

- v2 design renders typed fields.
- Editing a field calls v2 validate and updates status/issues.
- Refused designs disable export/launch controls.
- Post-run report fixture renders.
- v1 Stage 0 smoke remains valid until retired.

## Acceptance Criteria

- The UI makes the statistical reasoning inspectable and central.
- No advisor `design` or `export_config` field remains `unknown` in the v2
  frontend schema.
