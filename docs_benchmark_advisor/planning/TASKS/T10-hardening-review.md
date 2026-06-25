# T10 - Hardening Review

## Objective

Harden the integrated advisor against overclaiming, invalid exports, invariant
violations, and ambiguous/refused designs.

## Dependencies

- T09

## Parallelization Group

M3.

## Scope

- Add adversarial tests.
- Review claim boundaries and refusal behavior.
- Review statistical-guide grounding and rationale quality.
- Ensure docs explain limitations.
- Make small bug fixes found during hardening.

## Out Of Scope

- New features.
- Schema-breaking changes without human approval.
- Stage-2 validation implementation.
- CLI.

## Allowed Files/Directories

- advisor tests
- Studio API/UI tests
- `docs_benchmark_advisor/planning` updates
- small runtime bug fixes directly required by hardening tests

## Forbidden Files

- benchmark scoring changes
- final-answer grading
- generation/evaluation launch behavior
- major UI redesign

## Interfaces Consumed

- all v1 advisor interfaces
- `STATISTICAL_GUIDE.md`
- task fixtures
- integration smoke result

## Interfaces Produced

- hardening checklist;
- adversarial test coverage;
- final limitation/claim-boundary docs;
- guide-reference and rationale-quality checklist.

## Required Tests

- Invalid designs refuse.
- Unsupported claims refuse.
- Public-log-as-private-proof language is rejected or downgraded.
- Unknown or unsupported statistical guide references are rejected or warned.
- Rationale text does not overclaim beyond cited guide rules.
- State-matrix violations are rejected.
- Validator thresholds are covered at boundary values.
- Legacy advisor route compatibility, if present, cannot bypass v1 validation.
- No final-answer grading is introduced.
- No automatic expensive eval is launched.
- Refused designs cannot export.
- Needs-clarification designs cannot export.

## Acceptance Criteria

- Hardening tests pass.
- Docs list allowed and disallowed claims.
- Docs and fixtures make statistical knowledge sources explicit.
- No Stage-2 behavior is accidentally required for Stage 1.
- No v1 contract field remains defined only by example JSON.

## Integration Notes

This task should be last before demo/release. Any schema-breaking finding should
be escalated for human approval instead of patched silently.

## Risks

- Scope creep into Stage 2.
- Hardening uncovers interface flaws that require coordinated changes.
- Judge-ready rationale fields are present but too vague to validate later.

## Suggested Prompt For Implementation Agent

Harden the integrated Benchmark Advisor against overclaiming, unsupported guide
references, weak rationale, and invariant violations. Add tests and small fixes
only; do not add new features.
