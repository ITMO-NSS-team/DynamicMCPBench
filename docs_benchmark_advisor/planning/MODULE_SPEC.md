# Benchmark Advisor Module Spec

Status: canonical v1 planning spec plus v2 roadmap anchor.
Source: root `SPEC.md` draft plus advisor execution-plan decisions.
Primary surface: DMCP Studio.
Execution ledger: `docs_benchmark_advisor/PLAN.md`.
Concept and guardrails: `docs_benchmark_advisor/CONCEPT.md`.

## Goal

Build `benchmark_advisor` as a statistically aware pre-run planning module for
DMCP Studio. Given a user's deployment context and evaluation question, it
proposes benchmark parameters, explains why the proposed design can or cannot
test the user's idea, asks for user validation, and exports a JSON config for the
existing DynamicMCPBench generation pipeline.

Stage 1 is required for v1:

1. User enters a natural-language evaluation intent.
2. Advisor converts the intent into a structured benchmark design.
3. Deterministic validation checks whether the design is statistically
   defensible.
4. Advisor records why criteria and parameters were selected, citing the
   statistical guide.
5. UI shows editable numeric cards, warnings/refusals, hover rationale, and JSON
   export preview.
6. User approves or edits the design.
7. Advisor exports config only for approved/warning states. It does not launch
   benchmark generation.

Stage 2 is interface-only in v1:

1. Define the outcome tensor and validation-report contracts.
2. Do not implement post-run validation reports until Stage 1 is integrated.

V2 upgrades Stage 2 from placeholder to implementation target:

1. Build a full statistical plan with alternatives, assumptions, citations, and
   all issue reporting.
2. Use local statistical retrieval and/or a stat-agent only as a proposer and
   explanation layer.
3. Keep deterministic validation as the authority for status, export, launch,
   and report claim boundaries.
4. Add guarded corpus generation handoff after explicit confirmation.
5. Implement post-run statistical reports from outcome tensors.

## Users

- Researchers comparing agent models on deployment-shaped task distributions.
- Practitioners planning internal agent evaluations before spending LLM budget.
- Demo reviewers evaluating whether benchmark design is explicit,
  statistically auditable, and aligned with the stated question.
- Future contributors using task packets to implement independent PRs.

## Core Workflows

### Workflow A: Pairwise Model Selection

User asks which of two models is better for a deployment slice. Advisor produces
an estimand, hypotheses, task mix, budget/repeat policy, MDE/CI planning
heuristics, warnings, and export config.

### Workflow B: Leaderboard Planning

User asks for multi-model comparison. Advisor constrains claims to leaderboard
evidence, includes rank-stability planning fields, and warns against overclaiming
when the task count is too small.

### Workflow C: Regression Testing

User asks whether a new agent regressed. Advisor frames the design as paired
comparison or non-inferiority, not broad model selection.

### Workflow D: Diagnostic Slice

User asks about same-name tools, wrong-server failures, recovery, or cross-server
composition. Advisor marks the design as diagnostic unless it also has sufficient
coverage for model-selection claims.

## Non-Goals

- No automatic expensive LLM evaluation launches.
- No model training.
- No new benchmark pipeline.
- No CLI in v1.
- No final-answer grading.
- No weakening replay determinism, sandboxing, or trace/effect-scored
  DynamicMCPBench invariants.
- No claim that statistical planning guarantees external validity.
- No claim that public logs prove private deployment behavior.
- No Stage-2 post-run validation implementation in v1; v2 implements it only
  through the documented outcome-tensor/report contracts.

## Constraints

- Advisor must be a separate logical module from core `dmcp` pipeline internals.
- Interfaces are JSON-first and schema-first.
- On-disk/API schemas must use Pydantic v2 with `ConfigDict(extra="forbid")`.
- LLM planner may propose and explain; deterministic validator has final
   authority over approval, warning, or refusal.
- Validator checks structured design objects, not raw natural language.
- Planner choices must be grounded in
  `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`.
- Every major criterion and user-visible parameter must include guide references
  and a short rationale suitable for UI hover/popover display.
- All refusal states must include a failed criterion, reason, statistical reason,
   and repair suggestion.
- Response status, nullable fields, warning/refusal codes, and exportability are
  governed by the state matrix in `INTERFACES.md`.
- Validator thresholds in `INTERFACES.md` are normative, not examples.
- Existing prototype routes or schema versions do not satisfy v1 unless wrapped
  by the v1 `/api/advisor/design` and `/api/advisor/validate` contracts.
- User approval is required before any future generation handoff.
- V2 RAG/stat-agent output is advisory only; deterministic rules remain the
  authority.
- The first v2 launch path is corpus/specs/traces generation only.

## Definition Of Done

Stage 1 is done when:

- `docs_benchmark_advisor/planning/INTERFACES.md` contracts are implemented and tested.
- `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md` is present, versioned,
  and cited by planner outputs.
- Studio has a first-stage Advisor UI before benchmark execution.
- API exposes design and validation endpoints matching frozen contracts.
- API tests call `/api/advisor/design` and `/api/advisor/validate` directly.
- Advisor produces strict JSON with primary hypothesis, criteria, task
   distribution, analysis plan, warnings/refusals, guide-backed rationale, and
   export preview.
- Advisor emits required warnings for underpowered design, too few repeats,
   task-mix bias, and insufficient cross-server coverage.
- Advisor can refuse clearly invalid designs.
- Export config validates against the v1 generation-knob mapping but does not
  launch generation.
- Golden fixtures cover pairwise, leaderboard, regression, diagnostic, warning,
   and refusal scenarios.
- Integration smoke proves intent-to-export works without changing benchmark
  scoring or launching expensive evals.

Stage 2 is considered planned, not done, when outcome/report interfaces are
documented in `INTERFACES.md`.

V2 is done when:

- v2 schemas and routes are implemented without breaking v1.
- local statistical retrieval is offline, audited, and citation-backed.
- planning statistics expose power curves, design alternatives, assumptions,
  sensitivity, missingness, and multiplicity policies.
- post-run reports consume outcome tensors and state scoped allowed/not-allowed
  claims.
- Studio persists advisor state into Collect, supports structured edit/validate,
  and renders statistical workbench cards.
- guarded launch requires confirmation and produces corpus/specs/traces artifacts
  only.
