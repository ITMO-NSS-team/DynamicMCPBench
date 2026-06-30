# T13 - Dual-Engine Statistical Planner

## Objective

Add a v2 planner in which a stat-agent/RAG proposer can generate richer designs,
but deterministic rules remain the final authority.

## Dependencies

- T11
- T12
- T02
- T03

## Scope

- Implement a v2 planner interface that returns a proposed statistical plan,
  design alternatives, assumptions, citations, and repair suggestions.
- Keep deterministic fallback behavior for replay/offline operation.
- Run deterministic validation after every proposal.
- Clamp or refuse unsupported RAG/agent suggestions before returning them.
- Include plain-language explanations suitable for the Studio UI.

## Out Of Scope

- Launching generation.
- Post-run report computation.
- Letting LLM/RAG decide final status.

## Allowed Files/Directories

- advisor planner/service modules
- v2 fixtures and tests
- Studio API route composition as needed

## Required Tests

- Same deterministic input gives the same v2 fallback output.
- RAG citations appear in explanations but do not bypass validator rules.
- Unsupported claims are downgraded/refused even when proposed by the stat-agent.
- v1 planner tests still pass.

## Acceptance Criteria

- v2 design output contains alternatives, assumptions, citations, and repair
  actions.
- Every returned v2 design is rule-validated before the API returns it.
