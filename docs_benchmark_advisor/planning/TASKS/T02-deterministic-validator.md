# T02 - Deterministic Validator

## Objective

Validate structured advisor designs without using an LLM.

## Dependencies

- T01
- T03a
- T08

## Parallelization Group

M1-B.

## Scope

- Implement validation over `AdvisorDesign` and related structured fields.
- Emit approval, warning, refused, or needs-clarification status.
- Emit deterministic `WarningCard` and `Refusal` objects.
- Enforce claim-boundary rules.
- Enforce the validator thresholds and response state matrix from
  `INTERFACES.md`.
- Enforce required statistical-guide references for criteria and rationale
  entries.
- Enforce distractor-pressure thresholds when structured categories claim
  same-name, near-miss, or hard-negative pressure.

## Out Of Scope

- Raw natural-language intent interpretation.
- Planner prompt or LLM calls.
- Studio UI/API.
- Generation/evaluation launch.

## Allowed Files/Directories

- advisor validator module
- `tests/test_benchmark_advisor_validator.py`
- golden fixture reads

## Forbidden Files

- `dmcp-studio/frontend/**`
- `dmcp-studio/backend/app.py`
- planner adapter files
- generation/evaluation pipeline files

## Interfaces Consumed

- `AdvisorDesign`
- `Criterion`
- `TaskDistribution`
- `AnalysisPlan`
- `WarningCard`
- `Refusal`
- `ClarificationRequest`
- `StatisticalGuideReference`
- `STATISTICAL_GUIDE.md` rule ids
- response state matrix
- validator threshold table
- golden fixtures

## Interfaces Produced

- Validator function or class returning `AdvisorResponse` validation fields.
- Deterministic warning/refusal code set.

## Required Tests

- Valid design is approved.
- Underpowered design warns/refuses.
- Too few repeats warns.
- Low cross-server coverage warns/refuses for cross-server intent/design.
- Long-workflow design with low long-chain coverage warns.
- Recovery design with low recovery coverage warns/refuses.
- Same-name / near-miss / hard-negative category claims with default-low
  distractor fractions warn or refuse.
- Threshold boundary cases match `INTERFACES.md`.
- `needs_clarification` returns clarification fields and no export config.
- Overbroad claim is refused.
- Missing guide references warn/refuse according to response state rules.
- Unknown guide rule ids warn/refuse.
- Refusal includes reason, statistical reason, failed criterion, and repair
  options.

## Acceptance Criteria

- Validator never calls an LLM.
- Validator does not inspect raw `intent` except structured fields carried into
  the design.
- Same input always produces same output.
- Refused and clarification responses do not include export config or exportable
  launch action.
- Warning responses preserve warnings inside export config.
- Validator does not judge free-form rationale quality, but it verifies required
  guide-reference presence and consistency.
- Validator does not silently approve a design whose structured distractor
  categories are unsupported by its distractor fractions.

## Integration Notes

T05 must call this validator before returning API responses. T10 hardening will
add adversarial tests against overclaiming and unsupported guide references.

## Risks

- Treating semantic intent validation as deterministic when it is not.
- Drifting from the public thresholds in `INTERFACES.md`.
- Treating guide references as decorative instead of validator-visible fields.

## Suggested Prompt For Implementation Agent

Build deterministic validation over structured AdvisorDesign only. Return
warnings/refusals with repair suggestions. Never call an LLM and never launch
generation or evaluation.
