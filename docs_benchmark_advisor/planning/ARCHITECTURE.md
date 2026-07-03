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

## V2 Target Architecture

```text
User intent / edited design
  -> Statistical Guide rule map / citation index
  -> Deterministic intent and method proposer
  -> Statistical Engine parameter search and scoring
  -> StatisticalPlan with alternatives, assumptions, citations
  -> Deterministic rule gate and full issue list
  -> Studio statistical workbench
  -> guarded corpus handoff after explicit confirmation
  -> OutcomeTensor
  -> StatisticalReport with scoped claims
```

V2 keeps the same authority split as v1, but makes the statistical layer central.
The MVP is guide-first and deterministic: `STATISTICAL_GUIDE.md` supplies rule
ids, method constraints, source keys, and rationale snippets; deterministic
rules decide status, exportability, launchability, and report claim boundaries.
RAG/stat-agent support is optional future explanation/proposal machinery, not a
dependency for a high-quality MVP.

The key v2 correction is ordering. The final task budget, attempt count,
distribution, effect target, confirmatory slice set, missingness policy, and
multiplicity policy must be produced by the Statistical Engine before the API
returns a recommended design. The planner may select claim/method constraints,
but it must not treat statistical parameters as defaults that are explained only
after validation.

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
- **Guide Citation Index**: minimal v2 knowledge layer over the guide. Maps rule
  ids to sections, evidence status, source keys, snippets, and repair text. This
  replaces a mandatory RAG corpus in the MVP.
- **Deterministic Validator**: schema/statistical gates, warnings/refusals,
  guide-reference checks, claim-boundary checks, and the normative thresholds
  from `INTERFACES.md`. No LLM calls.
- **Planning Statistics**: pre-run CI/MDE/power heuristics and coverage
  diagnostics. Labels approximations as planning heuristics.
- **Optional Source Pack / Retrieval Layer**: future offline retrieval corpus
  built from approved references. Provides background citations only, never
  final authority.
- **V2 Statistical Planner**: guide-first proposer/composer that normalizes
  intent, selects claim/method constraints from the guide, delegates parameter
  search/scoring to the Statistical Engine, and returns the composed
  `StatisticalPlan`.
- **Statistical Engine**: deterministic planning core that enumerates candidate
  budgets, attempts, task distributions, effect targets, method assumptions,
  missingness/multiplicity policies, and slice plans; computes power/MDE/CI and
  rank-stability diagnostics; scores alternatives; emits repair actions and a
  computation trace.
- **Statistical Report**: post-run outcome-tensor analytics with effect sizes,
  confidence intervals, rank stability, slice diagnostics, missingness,
  multiplicity notes, and scoped allowed/not-allowed claims.
- **Studio API**: HTTP boundary for design and validation.
- **Studio UI**: first-stage advisor screen with numeric editable fields.
- **Guarded Handoff**: validates export JSON shape, shows command preview, and
  launches corpus/specs/traces jobs only after explicit confirmation.
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

## V2 Data Flow

1. UI sends v2 design request to `POST /api/advisor/v2/design`.
2. API normalizes intent, reads guide rules/citations, and selects claim/method
   constraints.
3. Statistical Engine searches candidate parameters, computes planning
   diagnostics, selects the recommended design, and returns alternatives.
4. Deterministic validator returns all issues and clamps unsupported claims.
5. UI renders claim card, method card, power curve, assumptions, alternatives,
   citations, and repair actions.
6. User edits structured fields and UI calls `POST /api/advisor/v2/validate`.
7. Approved/warning state can be carried into Collect with server scope and
   sandbox requirements.
8. Explicit user confirmation calls `POST /api/advisor/v2/launch`.
9. Launch creates a tracked corpus/specs/traces job for `scripts/build_corpus.py`.
10. Completed outcomes can be sent to `POST /api/advisor/v2/report` to produce a
   scoped statistical report.

## Dependency Direction

- `dmcp-studio` may depend on advisor module.
- Advisor module may depend on existing lightweight statistical helpers in
  `dmcp`, but must not depend on Studio.
- Advisor module must not import Studio frontend/backend code.
- Planner depends on schemas and the statistical guide, not validator.
- Validator depends on schemas, stats helpers, and guide rule-id registry, not
  planner.
- Statistical Engine depends on schemas, guide rule ids, guide citations, and
  statistical calculators; it must not depend on Studio, launch execution, RAG,
  or an LLM.
- API composes planner, Statistical Engine, validator, and stats.
- UI depends only on API/fixture wire shapes.
- Optional RAG/stat-agent code depends on local approved source files and
  schemas; validators must not depend on generated prose.
- Guarded launch code depends on export schemas and Studio job infrastructure;
  design and validation routes must not depend on launch execution.

## Extension Points

- LLM planner implementation can be swapped behind the planner adapter.
- Statistical guide can be expanded with new rule ids after an integration
  decision and fixture updates.
- Additional criteria can be added as new validator rules without changing UI
  if they use existing `WarningCard`/`Criterion` shapes.
- Stage-2 validation report can consume the documented outcome tensor later.
- Export handoff can connect to `scripts/build_corpus.py` or a future generation
  orchestrator after explicit approval.
- V2 statistical reports can add methods only when schemas, fixtures, and
  limitations docs are updated together.
- Statistical Engine calculators can add method families only with guide rule
  ids, typed schemas, deterministic tests, and UI-compatible issue/repair
  output.
- A richer retrieval/source-pack layer can be added after the guide-first MVP
  only if it improves explanations or source cards without changing validator
  authority.

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
- **Risk: optional RAG becomes hidden authority.** Mitigation: the MVP does not
  require RAG; any future retrieval is local and citation-only, while
  deterministic rules own verdicts and claim boundaries.
- **Risk: launch path spends budget accidentally.** Mitigation: v2 launch
  requires explicit confirmation, command preview, sandbox checks, and corpus-only
  scope.
- **Alternative: CLI-first implementation.** Rejected for v1; Studio UI is the
  product surface.
- **Alternative: mandatory RAG/stat-agent.** Rejected for the v2 MVP. The guide
  is already structured enough to drive method selection and explanations; the
  hard part is deterministic engine quality, not retrieval.
