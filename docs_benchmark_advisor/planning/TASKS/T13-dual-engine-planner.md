# T13 - Guide-First V2 Planner Composition

## Objective

Add the v2 planner/service composition layer that normalizes intent, selects
claim/method constraints from `STATISTICAL_GUIDE.md`, calls the Statistical
Engine, and returns a rule-gated `StatisticalPlan`.

## Dependencies

- T11
- T14
- T02
- T03

## Scope

- Implement a v2 planner interface that returns claim/method constraints, guide
  citations, and a composed `StatisticalPlan`.
- Always route candidate parameter search through the T14 Statistical Engine
  rather than hardcoding final task budget, attempts, distribution, and effect
  targets in the planner.
- Return the engine-selected recommended design plus alternatives, assumptions,
  citations, and repair suggestions.
- Keep deterministic fallback behavior for replay/offline operation.
- Run deterministic validation after every proposal.
- Clamp or refuse unsupported suggestions before returning them.
- Include plain-language explanations suitable for the Studio UI.
- Optionally support an LLM/stat-agent later by feeding it the full guide or
  selected guide sections, but keep that outside the MVP critical path.

## Implementation

- `benchmark_advisor/v2_engine.py` is the deterministic MVP engine/composition
  layer used by T13. It builds a finite task-budget/attempt grid, uses the v1
  deterministic planner as a structured `AdvisorDesign` factory, validates every
  candidate, converts validator output into v2 `StatisticalIssue` objects, and
  selects a recommended `EngineDecision`.
- `benchmark_advisor/v2_service.py` wraps that decision into a v2
  `StatisticalPlan`, preserves local guide citations/source keys from
  `guide_citations.py`, attaches an export preview only for approved/warning
  outputs, and keeps v2 validation side-effect free.
- `dmcp-studio/backend/app.py` exposes `/api/advisor/v2/design` and
  `/api/advisor/v2/validate`.
- This closes the T13 guide-first planner/API composition MVP. The broader
  BA5.4/T14 engine work remains the follow-up for richer calculators,
  sensitivity branches, and full candidate-search/report depth.

## Out Of Scope

- Launching generation.
- Post-run report computation.
- Letting LLM/RAG decide final status.
- Letting LLM/RAG choose launchable parameters without engine scoring and
  deterministic validation.
- Requiring vector retrieval or a separate RAG corpus for MVP operation.

## Allowed Files/Directories

- advisor planner/service modules
- v2 fixtures and tests
- Studio API route composition as needed

## Required Tests

- Same deterministic input gives the same v2 fallback output.
- Guide citations appear in explanations and map to known rule ids/source keys.
- Unsupported claims are downgraded/refused.
- The planner delegates final parameter recommendation to the Statistical Engine
  and does not silently return unscored defaults.
- The planner works when only `STATISTICAL_GUIDE.md` is available.
- v1 planner tests still pass.

## Acceptance Criteria

- v2 design output contains alternatives, assumptions, citations, and repair
  actions.
- Task budget, attempts, target effect, distribution, and confirmatory slice
  choices are present because the Statistical Engine scored them, not because
  the planner filled defaults after method selection.
- Every returned v2 design is rule-validated before the API returns it.
