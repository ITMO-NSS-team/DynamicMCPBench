# T00 - Planning Docs

## Objective

Create and maintain the canonical advisor planning tree under
`docs_benchmark_advisor/`. Convert the draft root `SPEC.md` into
implementation-ready documents and freeze the first interface contract.

## Dependencies

None.

## Parallelization Group

M0 blocking task. No implementation task should begin until this task lands.

## Scope

- Own all `docs_benchmark_advisor/**` planning files.
- Define the advisor-local `CONCEPT.md`, `AUTONOMY.md`, and `PLAN.md` files that
  mirror the structure of the main DMCP planning docs.
- Define module spec, architecture, interfaces, task graph, integration plan,
  test strategy, and task packets.
- Keep the plan agent-neutral and PR-sized.

## Out Of Scope

- Runtime implementation.
- Tests outside documentation checks.
- Editing core `dmcp`, Studio backend/frontend, or root `SPEC.md`.

## Allowed Files/Directories

- `docs_benchmark_advisor/**`

## Forbidden Files

- `dmcp/**`
- `dmcp-studio/**`
- `tests/**`
- `scripts/**`
- root `SPEC.md` except as read-only source material

## Interfaces Consumed

- Draft root `SPEC.md`
- `AGENTS.md`

## Interfaces Produced

- `docs_benchmark_advisor/CONCEPT.md`
- `docs_benchmark_advisor/AUTONOMY.md`
- `docs_benchmark_advisor/PLAN.md`
- `docs_benchmark_advisor/planning/MODULE_SPEC.md`
- `docs_benchmark_advisor/planning/ARCHITECTURE.md`
- `docs_benchmark_advisor/planning/INTERFACES.md`
- `docs_benchmark_advisor/planning/TASK_GRAPH.md`
- `docs_benchmark_advisor/planning/INTEGRATION_PLAN.md`
- `docs_benchmark_advisor/planning/TEST_STRATEGY.md`
- `docs_benchmark_advisor/planning/TASKS/*.md`

## Required Tests

- Manual doc inventory: every required planning file exists.
- Manual grep check: every task packet contains Objective, Scope, Out of scope,
  Allowed files, Interfaces consumed, Interfaces produced, Required tests,
  Acceptance criteria, Integration notes, Risks, Suggested prompt.

## Acceptance Criteria

- Advisor-local concept, autonomy, and plan-ledger docs exist and point to the
  detailed planning contracts.
- `INTERFACES.md` is explicit enough for implementation agents.
- `TASK_GRAPH.md` includes Mermaid graph, PR order, shared/frozen files,
  hotspots, and human-approval list.
- Every task packet is independently executable from repo files, `AGENTS.md`,
  `INTERFACES.md`, and its own task file.

## Integration Notes

This task freezes the shared vocabulary. Later schema-breaking changes require
human approval and updates to all affected task packets.

## Risks

- Overly vague documents leave decisions to implementation agents.
- Overly detailed documents create unnecessary merge conflicts.

## Suggested Prompt For Implementation Agent

Create the Benchmark Advisor planning docs under `docs_benchmark_advisor/` from
the draft SPEC and execution plan. Include advisor-local `CONCEPT.md`,
`AUTONOMY.md`, and `PLAN.md` in the style of the main DMCP docs. Do not edit
runtime code.
