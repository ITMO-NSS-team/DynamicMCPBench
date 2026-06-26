# T03 - Planner Adapter

## Objective

Convert user intent into a structured advisor proposal that matches the frozen
schemas.

## Dependencies

- T01
- T03a
- T08

## Parallelization Group

M1-B.

## Scope

- Implement planner adapter interface.
- Add prompt/rule template for intent-to-design.
- Return structured `AdvisorDesign` candidates.
- Support pairwise, leaderboard, regression, and diagnostic intents.
- Extract domain/category, workflow-length, and distractor-pressure signals from
  user intent when these are explicit.
- Ground every criterion and major user-visible parameter in
  `STATISTICAL_GUIDE.md` rule ids.
- Populate rationale fields for future UI hover/popover display.

## Out Of Scope

- Deterministic validation gates.
- Studio API/UI.
- Planning statistics calculations.
- Generation/evaluation launch.

## Allowed Files/Directories

- advisor planner module
- planner prompt/template files
- statistical guide reads
- `tests/test_benchmark_advisor_planner.py`
- golden fixture reads

## Forbidden Files

- validator module except imported public interface
- Studio frontend/backend route files
- `dmcp/evaluator.py`
- generation pipeline files

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorDesign`
- enum registries
- `Criterion`
- `TaskDistribution`
- `StatisticalGuideReference`
- `STATISTICAL_GUIDE.md`
- golden intent fixtures

## Interfaces Produced

- Planner adapter callable that maps `AdvisorRequest` to `AdvisorDesign`.
- Versioned prompt/rule template.
- Guide-backed rationale entries for criteria and major parameters.

## Required Tests

- 10-20 golden intent prompts produce schema-valid designs.
- Ambiguous intent produces clarification-ready design/status path.
- Regression intent maps to regression-testing criteria.
- Diagnostic intent maps to diagnostic claim boundary.
- Planner output contains no unsupported final claim language in fixtures.
- Planner output uses only enum values from `INTERFACES.md`.
- Planner output cites known guide rule ids for every criterion.
- Planner output includes hover-ready rationale text for primary metric, task
  budget, attempts, task distribution, and selected criteria.
- Exact demo query for short finance workflows with hard negative tools and
  similar names produces raised short-chain and distractor pressure instead of
  falling back to `general` defaults.

## Acceptance Criteria

- Planner output requires no manual schema repair for golden prompts.
- Validator remains authoritative and is not bypassed.
- Planner fills `intent_evidence`; defaults without evidence are marked as such
  in the evidence ledger downstream.
- Planner maps explicit short workflow, finance/domain, hard-negative, near-miss,
  and same-name intent to structured categories/distribution fields.
- Planner does not rely on unstated "LLM statistical intuition"; choices are
  traceable to guide rules.
- LLM/network behavior, if present, is abstracted so tests can run with mocked
  responses.

## Integration Notes

T05 composes planner + validator. T02 may reject planner output, including
missing or inconsistent guide references; that is expected and should surface as
warnings/refusals.

## Risks

- Prompt overclaims statistical validity.
- Planner fills fields based on defaults rather than user intent evidence.
- Planner cites guide rules mechanically without explaining the actual choice.

## Suggested Prompt For Implementation Agent

Implement the intent-to-structured-design adapter. It may use a rule/LLM
boundary, but it must consume `STATISTICAL_GUIDE.md`, cite rule ids, and produce
hover-ready rationale fields. Tests must use deterministic fixtures/mocks. The
validator remains the only authority for approval or refusal.
