# T07 - Export Handoff

## Objective

Validate export JSON compatibility with future DynamicMCPBench generation
handoff without launching generation.

## Dependencies

- T01
- T05

## Parallelization Group

M1-C.

## Scope

- Add export-config validator.
- Add handoff stub/path documentation.
- Ensure approved/warning designs can produce JSON export preview.
- Ensure refused designs cannot be exported.
- Ensure needs-clarification designs cannot be exported.
- Validate `generation_knobs` and the v1 dry-run guard.

## Out Of Scope

- Running `goal-gen`, `explore`, `distill`, `eval`, or paid calls.
- Changing generation algorithms.
- CLI.

## Allowed Files/Directories

- advisor export module
- export tests
- `docs_benchmark_advisor/planning/INTEGRATION_PLAN.md` updates if needed

## Forbidden Files

- `dmcp/goal_gen.py`
- `scripts/build_corpus.py` behavior changes
- `dmcp/evaluator.py`
- Studio frontend except if T09 later wires export button

## Interfaces Consumed

- `ExportConfig`
- `ExportGenerationKnobs`
- `AdvisorResponse`
- validator status/refusal conventions

## Interfaces Produced

- Export validation function.
- Export handoff documentation.

## Required Tests

- Approved export validates.
- Warning export validates with warnings preserved.
- Refused design export fails.
- Needs-clarification design export fails.
- Missing required export fields fail.
- Missing `generation_knobs` fails.
- `dry_run_only: false` fails in v1.

## Acceptance Criteria

- Export path is JSON-first.
- No benchmark generation is launched.
- Export config contains required generation knobs and claim boundary.
- Export config maps `tasks` to a target TaskSpec count, not an embedded task
  list.

## Integration Notes

T09 verifies export preview in end-to-end smoke. Future work may connect export
to generation after user approval.

## Risks

- Accidental coupling to unfinished generation orchestration.
- Export shape diverges from `INTERFACES.md`.

## Suggested Prompt For Implementation Agent

Implement export validation and handoff shape only. Approved/warning designs may
produce JSON preview; refused designs may not. Do not run generation or eval.
