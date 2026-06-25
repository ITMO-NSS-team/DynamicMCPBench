# T01 - Core Schema

## Objective

Implement the typed schema layer matching `docs_benchmark_advisor/planning/INTERFACES.md`.

## Dependencies

- T00

## Parallelization Group

M1-A.

## Scope

- Add the advisor schema module.
- Define Pydantic v2 models for all frozen shared types.
- Add JSON serialization and validation tests.

## Out Of Scope

- Planner adapter.
- Deterministic validator rules.
- Planning statistics.
- Studio API/UI.
- Generation handoff.

## Allowed Files/Directories

- `dmcp/benchmark_advisor/**` or the agreed advisor schema module path
- `tests/test_benchmark_advisor_schema.py`
- advisor fixture loader only if needed for schema tests

## Forbidden Files

- `dmcp-studio/**`
- `dmcp/cli.py`
- `dmcp/evaluator.py`
- `dmcp/goal_gen.py`
- planner/validator/statistics implementation files

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorValidationRequest`
- `AdvisorDesign`
- `HypothesisPlan`
- `Criterion`
- `TaskDistribution`
- `DistractorPolicy`
- `DiagnosticSlice`
- `AnalysisPlan`
- `WarningCard`
- `Refusal`
- `ClarificationRequest`
- `EvidenceLedgerEntry`
- `ExportGenerationKnobs`
- `ExportConfig`
- `AdvisorResponse`
- `ValidationReportStub`
- `OutcomeTensorContract`
- `StatisticalGuideReference`
- guide-backed rationale fields on `Criterion` and `EvidenceLedgerEntry`

## Interfaces Produced

- Importable schema classes.
- Version constants for advisor schema/report schema.

## Required Tests

- Valid fixture parses.
- Unknown top-level field fails.
- Unknown nested field fails.
- Required fields are enforced.
- Enum registries reject unknown values.
- Response state matrix is enforceable by schema-level or helper-level tests.
- Export config round-trips through JSON.
- Guide references and evidence-ledger hover rationale fields round-trip through
  JSON.
- `ValidationReportStub` is present but does not imply Stage-2 implementation.

## Acceptance Criteria

- All schema models use `ConfigDict(extra="forbid")`.
- Model names and JSON field names match `INTERFACES.md`.
- Version constants equal `benchmark_advisor.v1` and
  `benchmark_advisor.report.v1`.
- Schema supports `statistical_guide.v1` references without implementing guide
  logic.
- Nullable fields match the response state matrix.
- No runtime behavior beyond validation/serialization is implemented.

## Integration Notes

T02-T07 consume this module. Schema-breaking changes after this task require an
integration decision.

## Risks

- Drift from `INTERFACES.md`.
- Sneaking validator/planner logic into schema classes.

## Suggested Prompt For Implementation Agent

Implement only the Benchmark Advisor schema layer from `docs_benchmark_advisor/planning/INTERFACES.md`.
Use Pydantic v2 with `extra="forbid"`. Do not implement planner, validator, API,
UI, or generation handoff.
