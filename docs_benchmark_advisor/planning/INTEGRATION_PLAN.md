# Benchmark Advisor Integration Plan

## Integration Strategy

Integrate through stable JSON contracts, not shared mutable implementation
details. Each implementation PR should consume `INTERFACES.md` and golden
fixtures. Planner and validator PRs must also consume `STATISTICAL_GUIDE.md`.
Cross-component integration happens only after core schemas, statistical guide,
fixtures, planner, validator, stats, API, UI, and export handoff are
independently tested.

## Stage 1 Integration Flow

1. UI sends `AdvisorRequest` to Studio API.
2. API runs planner adapter with the versioned statistical guide.
3. API runs deterministic validator.
4. API enriches response with planning statistics and export preview.
5. UI displays response.
6. UI shows hover/popover rationale for parameters and criteria using evidence
   ledger entries.
7. User edits numeric fields.
8. UI sends edited structured design in an `AdvisorValidationRequest` to the
   validation endpoint.
9. API validates edited design.
10. UI exposes JSON export only for approved/warning states.

## V2 Integration Flow

1. UI sends a v2 request to `/api/advisor/v2/design`.
2. API retrieves local statistical knowledge and constructs a proposed
   `StatisticalPlan`.
3. API runs deterministic validation and returns all issues.
4. UI renders statistical workbench cards: claim, method, power, assumptions,
   alternatives, citations, and repairs.
5. User edits structured design fields.
6. UI sends the edited plan to `/api/advisor/v2/validate`.
7. Approved/warning plans can be carried into Collect with server scope,
   sandbox requirements, export state, and validation state.
8. UI shows a command preview and requests explicit confirmation before launch.
9. `/api/advisor/v2/launch` creates a tracked corpus/specs/traces job for
   `scripts/build_corpus.py`.
10. Completed outcome tensors can be submitted to `/api/advisor/v2/report`.
11. UI renders the statistical report with allowed and not-allowed claims.

## What Integration Must Not Do

- Do not launch `goal-gen`, `explore`, `distill`, `eval`, or paid LLM evals.
- Do not change candidate scoring behavior.
- Do not add final-answer grading.
- Do not bypass deterministic validation.
- Do not treat warning-heavy designs as claim-valid without showing warnings.
- Do not treat the legacy `/api/advisor` prototype route as sufficient for v1.
- Do not export configs for `refused` or `needs_clarification` responses.
- Do not let RAG/stat-agent prose override deterministic validation.
- Do not use runtime network retrieval in the statistical knowledge layer.
- Do not launch leaderboard/eval from the first guarded handoff.
- Do not make `/api/advisor/v2/design` or `/api/advisor/v2/validate`
  side-effectful.

## Cross-Component Contracts

- Backend and frontend use the same `AdvisorResponse` fixture shape.
- Export handoff validates `ExportConfig`, but does not execute it.
- Planner output must be validated before API returns it to UI.
- Planner output must include guide references and rationale entries for major
  proposed values.
- Validator must flag missing/unknown guide references.
- Validator accepts structured design only; raw intent interpretation belongs to
  planner.
- The validate route accepts `AdvisorValidationRequest`, not a bare design plus
  implicit context.
- The state matrix in `INTERFACES.md` defines when `design`, `refusal`,
  `clarification`, and `export_config` are null or non-null.
- V2 issue lists carry all applicable warnings/refusals, but status precedence
  remains refused > clarification > warning > approved.
- V2 frontend schemas must type core advisor objects; `unknown` is allowed only
  for explicitly opaque non-advisor payloads.
- Launch jobs consume validated export configs and must expose command preview,
  status, logs, and artifact paths.

## Integration Checkpoints

- Fixture response renders in UI.
- Planner-generated response validates.
- User-edited response re-validates.
- Export preview validates.
- Refused design cannot be exported.
- Clarification response cannot be exported.
- Hover rationale renders for at least criteria, task budget, attempts, task
  distribution, and primary metric.
- Smoke test confirms no benchmark run is launched.
- V2 statistical plan validates with local citations.
- V2 edited design revalidates with all issues.
- V2 report fixture renders scoped claims.
- Advisor state persists Design -> Collect -> Launch.
- Guarded launch refuses missing confirmation and refused designs.
- Guarded launch creates corpus/specs/traces jobs only.

## Rollback Strategy

If integration fails late, keep the UI shell fixture-backed and disable live API
calls behind a visible "Advisor API unavailable" state. Do not remove validator
or schema tests to make UI pass.

For v2 launch failures, keep the design/report UI usable and disable only the
launch button. Do not weaken confirmation, sandbox, or corpus-only guards to make
launch tests pass.
