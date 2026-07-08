# T18 - Advisor v2 Hardening and Fixups

## Objective

Close the known v1/v2 weaknesses after statistical core and guarded handoff
exist.

## Dependencies

- T13
- T16
- T17

## Scope

- Replace brittle keyword intent parsing with normalized phrase extraction and
  adversarial fixtures.
- Return all blocking issues, while preserving status precedence.
- Ensure server scope is carried from Studio selection into advisor export.
- Add hardening tests for multilingual-ish and reordered intent phrasing.
- Synchronize docs, fixtures, frontend schemas, backend schemas, and tests.
- Update `LIMITATIONS.md` with v2 allowed/disallowed claims.

## Out Of Scope

- New statistical methods beyond BA5 scope.
- Full benchmark leaderboard/eval launch.
- Removing v1 compatibility.

## Allowed Files/Directories

- advisor planner/validator/service modules
- Studio frontend/backend advisor integration
- docs and fixtures
- hardening tests

## Required Tests

- "short finance workflows" and related synonyms trigger short-chain coverage.
- Negative cases do not over-trigger categories.
- All blocking issues are visible in the response.
- Server scope survives Design -> Collect -> Launch.
- Docs and runtime schema versions remain synchronized.

## Acceptance Criteria

- The known gap memo items are either fixed or intentionally deferred with a
  documented reason.
- v2 can be used as the next stable advisor implementation target.
