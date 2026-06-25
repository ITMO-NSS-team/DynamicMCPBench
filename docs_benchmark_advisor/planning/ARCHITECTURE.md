# Benchmark Advisor Architecture

## Proposed Architecture

```text
User intent
  -> Planner Adapter
  -> Statistical Guide references
  -> AdvisorDesign
  -> Deterministic Validator
  -> AdvisorResponse
  -> Studio UI review / user edits
  -> ExportConfig preview
  -> future generation handoff after explicit approval
```

The LLM/rule planner produces a structured proposal grounded in the versioned
statistical guide. The deterministic validator approves, warns, refuses, or
requests clarification. Studio renders the response and never launches
generation automatically.

The existing prototype `/api/advisor` route, if present, is a legacy adapter and
is not the v1 API boundary. The v1 boundary is the pair of routes documented in
`INTERFACES.md`: `/api/advisor/design` and `/api/advisor/validate`.

## Major Components

- **Advisor Core**: shared schemas, enums, version constants, serialization.
- **Planner Adapter**: intent-to-design adapter. May use LLM or deterministic
  rules, but must output only frozen schemas and cite statistical-guide rules.
- **Statistical Guide**: static curated knowledge pack with rule ids for
  intent-to-mode, metric, criterion, distribution, budget, claim-boundary, and
  rationale choices.
- **Deterministic Validator**: schema/statistical gates, warnings/refusals,
  guide-reference checks, claim-boundary checks, and the normative thresholds
  from `INTERFACES.md`. No LLM calls.
- **Planning Statistics**: pre-run CI/MDE/power heuristics and coverage
  diagnostics. Labels approximations as planning heuristics.
- **Studio API**: HTTP boundary for design and validation.
- **Studio UI**: first-stage advisor screen with numeric editable fields.
- **Export Handoff**: validates export JSON shape for future generation.
- **Fixtures**: golden prompt/design/response examples shared by tasks.

## Data Flow

1. UI sends `AdvisorRequest` to `POST /api/advisor/design`.
2. API calls planner adapter to create `AdvisorDesign` with guide-backed
   rationale entries.
3. API calls deterministic validator and planning-statistics helpers.
4. API returns `AdvisorResponse`.
5. UI renders design cards, evidence ledger hover rationale, warnings/refusal,
   and JSON preview.
6. User edits numeric fields and sends revised design to
   `POST /api/advisor/validate`.
7. API returns updated `AdvisorResponse`.
8. Approved/warning response exposes `ExportConfig` for future generation
   handoff; refused/clarification responses expose no export config.

## Dependency Direction

- `dmcp-studio` may depend on advisor module.
- Advisor module may depend on existing lightweight statistical helpers in
  `dmcp`, but must not depend on Studio.
- Advisor module must not import Studio frontend/backend code.
- Planner depends on schemas and the statistical guide, not validator.
- Validator depends on schemas, stats helpers, and guide rule-id registry, not
  planner.
- API composes planner, validator, and stats.
- UI depends only on API/fixture wire shapes.

## Extension Points

- LLM planner implementation can be swapped behind the planner adapter.
- Statistical guide can be expanded with new rule ids after an integration
  decision and fixture updates.
- Additional criteria can be added as new validator rules without changing UI
  if they use existing `WarningCard`/`Criterion` shapes.
- Stage-2 validation report can consume the documented outcome tensor later.
- Export handoff can connect to `scripts/build_corpus.py` or a future generation
  orchestrator after explicit approval.

## Risks And Alternatives

- **Risk: validator interprets raw natural language.** Mitigation: validator only
  accepts structured `AdvisorDesign`; missing semantic fields produce
  clarification/refusal.
- **Risk: LLM overclaims.** Mitigation: claim-boundary fields and deterministic
  refusal gates plus guide-backed rationale requirements.
- **Risk: statistical knowledge remains implicit.** Mitigation: planner outputs
  must cite `STATISTICAL_GUIDE.md` rule ids and UI renders rationale from those
  citations.
- **Risk: UI/API drift.** Mitigation: golden fixtures and frozen
  `INTERFACES.md`.
- **Risk: prototype drift.** Mitigation: v1 tests call `/api/advisor/design` and
  `/api/advisor/validate`; `/api/advisor` compatibility is optional and cannot
  replace them.
- **Risk: scope creep into Stage 2.** Mitigation: Stage 2 is interface-only until
  Stage 1 integration passes.
- **Alternative: CLI-first implementation.** Rejected for v1; Studio UI is the
  product surface.
