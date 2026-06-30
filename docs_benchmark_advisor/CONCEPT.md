# Benchmark Advisor concept and implementation catalogue

This file is the advisor-local equivalent of `docs/CONCEPT.md`: it explains why
the module exists, what the v1 system must do, and which scientific boundaries
must stay true while implementation work is split across agents. The executable
claim ledger is `docs_benchmark_advisor/PLAN.md`; detailed contracts live under
`docs_benchmark_advisor/planning/`.

---

## 1. The problem we solve

DynamicMCPBench can generate and evaluate trace-grounded benchmarks, but a user
still has to answer a hard pre-run question: "What benchmark design would
actually test my claim without fooling me?"

Common failure modes:

- A user asks for a model-selection claim with too few tasks or repeats.
- A benchmark claims cross-server behavior but mostly samples single-server
  tasks.
- A diagnostic slice is mistaken for a broad leaderboard result.
- A planner recommends parameters without explaining the statistical reason.
- A UI lets a user launch an expensive generation run before the claim, task
  distribution, and validation gates are explicit.

Benchmark Advisor exists to put a statistically aware planning gate in front of
benchmark generation.

## 2. The v1 thesis

The advisor is a pre-run design assistant, not a new benchmark generator. It
converts user intent into a structured `AdvisorDesign`, validates that design
deterministically, explains the rationale behind major parameters, and exports a
JSON config preview only after user review.

The core design rule is:

```text
LLM/rule planner proposes -> deterministic validator decides -> UI explains
```

The LLM can help map messy user intent into a design, but it is not the source
of statistical authority. Statistical recommendations must be grounded in the
versioned guide at `planning/STATISTICAL_GUIDE.md`, and every important
criterion or user-visible parameter must cite guide rule ids.

## 3. Stage 1 workflow

```text
User intent
  -> AdvisorRequest
  -> Planner Adapter with Statistical Guide references
  -> AdvisorDesign
  -> Deterministic Validator + Planning Statistics
  -> AdvisorResponse
  -> Studio UI cards, warnings/refusals, hover rationale, JSON preview
  -> user edits / approval
  -> ExportConfig preview
```

Stage 1 is complete when Studio can demonstrate the intent-to-export planning
loop without launching `goal-gen`, `explore`, `distill`, `eval`, or any paid
benchmark run.

## 4. Stage 2 boundary

Stage 2 is post-run validation reporting. In v1 it is interface-only:

- outcome tensor contract;
- validation report stub;
- future user questions over benchmark outcomes;
- future judge-based rationale validation hooks.

No Stage 2 analytics implementation is required for v1.

## 4.1. The v2 thesis

V2 turns the advisor into a real statistical workbench. It keeps the v1 safety
rule, but expands the statistical surface:

```text
RAG/stat-agent proposes and explains -> deterministic rules decide
```

The central user value is not just "approved/refused"; it is understanding what
claim a benchmark can support, what budget is needed, which assumptions matter,
and how completed outcomes should be interpreted. V2 therefore adds planning
power curves, design alternatives, assumption ledgers, local statistical
citations, guarded corpus launch, and post-run reports.

## 5. Statistical knowledge model

V1 uses a static curated guide, not RAG:

- `planning/STATISTICAL_GUIDE.md` defines `guide_version:
  statistical_guide.v1`.
- Rule ids cover intent-to-mode mapping, metric selection, task distribution,
  budget/power heuristics, criteria, claim boundaries, and UI rationale.
- Planner output must include `StatisticalGuideReference` entries.
- `Criterion.selection_rationale` explains why a criterion was selected.
- `EvidenceLedgerEntry.hover_text` is the short UI explanation for a parameter.
- `EvidenceLedgerEntry.judge_validation_hint` keeps the door open for a future
  judge-based validator.

The deterministic validator does not grade prose quality in v1. It checks
required fields, known guide rule ids, claim boundaries, thresholds, refusal
conditions, and exportability.

V2 adds a local retrieval corpus built from the guide and human-approved
references. Retrieved text supports explanations and source visibility, but it
does not override deterministic validator decisions.

## 6. Supported planning modes

- **Pairwise selection**: compare two models or agents on the same planned task
  distribution; primary criteria are paired and claim-bounded.
- **Leaderboard**: rank multiple models with explicit rank-stability limits and
  warnings for underpowered designs.
- **Regression**: test whether a new agent regressed or remains non-inferior
  under a declared margin.
- **Diagnostic**: inspect same-name confusion, wrong-server behavior, recovery,
  or cross-server composition without overstating broad model-selection claims.

## 7. Hard invariants

- Never add final-answer grading.
- Never auto-launch expensive generation or evaluation from Advisor UI.
- Never treat public logs as proof of private deployment behavior.
- Never claim universal model superiority from a planned benchmark.
- Never bypass deterministic validation before showing/exporting a design.
- Never relax DynamicMCPBench replay, sandboxing, trace/effect scoring, or
  stateful-write invariants.
- Never make Stage 2 validation reports mandatory for v1.

## 8. Component catalogue

| Component | Role | Primary contracts |
|---|---|---|
| Advisor Core | schemas, enums, serialization | `planning/INTERFACES.md` |
| Statistical Guide | curated rule ids and rationale rules | `planning/STATISTICAL_GUIDE.md` |
| Planner Adapter | intent -> structured design | `planning/TASKS/T03-planner-adapter.md` |
| Deterministic Validator | warnings, refusals, claim boundaries | `planning/TASKS/T02-deterministic-validator.md` |
| Planning Statistics | CI/MDE/power heuristics | `planning/TASKS/T04-planning-statistics.md` |
| Studio API | v1 HTTP routes | `planning/TASKS/T05-studio-api.md` |
| Studio UI | first-stage planning screen | `planning/TASKS/T06-studio-ui-shell.md` |
| Export Handoff | JSON preview shape, no execution | `planning/TASKS/T07-export-handoff.md` |
| Golden Fixtures | shared examples for independent agents | `planning/TASKS/T08-golden-fixtures.md` |
| Local Statistical Knowledge Base | offline RAG citations and background | `planning/TASKS/T12-local-statistical-knowledge-base.md` |
| Dual-Engine Planner | stat-agent/RAG proposer plus deterministic gate | `planning/TASKS/T13-dual-engine-planner.md` |
| Statistical Report | post-run outcome-tensor analytics | `planning/TASKS/T15-post-run-statistical-report.md` |
| Guarded Handoff | confirmed corpus/specs/traces launch jobs | `planning/TASKS/T17-guarded-corpus-handoff.md` |

## 9. Source documents

- `planning/MODULE_SPEC.md` - v1 module spec and definition of done.
- `planning/ARCHITECTURE.md` - architecture, data flow, dependency direction.
- `planning/INTERFACES.md` - frozen wire/schema contracts.
- `planning/STATISTICAL_GUIDE.md` - v1 statistical knowledge pack.
- `planning/TASK_GRAPH.md` - dependency graph and integration checkpoints.
- `planning/TEST_STRATEGY.md` - unit, integration, smoke, and manual checks.
- `planning/ADVISOR_GAPS.md` - durable memo of v1 gaps targeted by BA5-BA7.
- `planning/TASKS/*.md` - PR-sized task packets.
