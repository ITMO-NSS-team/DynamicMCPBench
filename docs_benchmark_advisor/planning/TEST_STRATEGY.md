# Benchmark Advisor Test Strategy

## Unit Tests

- Schema tests:
  - valid request/design/response fixtures parse;
  - unknown fields fail;
  - required fields are enforced;
  - response state matrix is enforced;
  - enum registries reject unknown values;
  - guide references parse and unknown rationale fields fail;
  - export config serializes to JSON.
- Validator tests:
  - underpowered design warns/refuses;
  - too few repeats warns;
  - cross-server intent with low cross-server ratio warns/refuses;
  - overbroad claim is refused;
  - threshold boundary cases match `INTERFACES.md`;
  - refused and clarification responses have null `export_config`;
  - valid design is approved.
- Planner tests:
  - golden intents produce schema-valid designs;
  - planner outputs cite `STATISTICAL_GUIDE.md` rule ids for every criterion and
    major user-visible parameter;
  - ambiguous intents produce clarification/refusal-ready output;
  - no unsupported claim strings in generated rationale fixtures.
- Statistical guide tests:
  - every fixture guide rule id exists in `STATISTICAL_GUIDE.md`;
  - each mode has intent, metric, criterion, claim-boundary, and rationale rules;
  - good/bad rationale examples are present.
- Stats tests:
  - MDE decreases as task count increases;
  - CI width decreases as task count increases;
  - coverage diagnostics are deterministic.
- V2 schema tests:
  - `StatisticalPlan`, `PowerAnalysis`, `DesignAlternative`,
    `AssumptionLedger`, `StatisticalIssue`, `OutcomeTensor`,
    `StatisticalReport`, `LaunchRequest`, and `LaunchJob` parse and reject
    unknown fields;
  - v1 schemas remain compatible.
- Local statistical knowledge tests:
  - retrieval is offline and deterministic;
  - returned citations map to known guide rule ids or approved source keys;
  - changing retrieved prose cannot change deterministic validator decisions.
- V2 statistical tests:
  - power/MDE curves are monotonic;
  - paired and unpaired planning assumptions are explicit;
  - rank-stability planning is reproducible;
  - non-inferiority margins are handled explicitly;
  - missingness and multiplicity policies are present.

## Integration Tests

- `POST /api/advisor/design` returns `AdvisorResponse` for golden requests.
- `POST /api/advisor/validate` validates user-edited structured design.
- A legacy `/api/advisor` route, if retained, is not the only passing contract
  route.
- Refused response contains no exportable launch action.
- Clarification response contains no export config.
- Warning response contains warning cards and export preview.
- API route tests confirm no benchmark generation/evaluation function is called.
- `POST /api/advisor/v2/design` returns a rule-gated statistical plan with
  alternatives, assumptions, citations, and issues.
- `POST /api/advisor/v2/validate` returns all applicable issues after edits.
- `POST /api/advisor/v2/report` consumes an outcome tensor and returns scoped
  allowed/not-allowed claims.
- `POST /api/advisor/v2/launch` refuses missing confirmation, refused designs,
  unmet sandbox requirements, and any leaderboard/eval launch attempt.

## Smoke Tests

- UI fixture render for approved, warning, refused, and smoke-test-only states.
- UI fixture render for hover rationale on criteria and major numeric
  parameters.
- End-to-end local smoke: request -> planner -> validator -> response -> export
  preview.
- Static frontend build/typecheck if toolchain is available.
- V2 Studio smoke:
  - advisor state persists from Design into Collect;
  - structured edits call v2 validate;
  - power/method/assumption/citation cards render;
  - launch job status and artifact paths render from fixtures.

## Golden Fixtures

Minimum fixture set:

- pairwise finance long-workflow valid design;
- leaderboard small-budget warning design;
- regression-testing design;
- same-name/wrong-server diagnostic design;
- underpowered refusal;
- too-few-repeats warning;
- low cross-server coverage warning;
- smoke-test-only design;
- ambiguous intent needing clarification;
- edited numeric-field validation.
- refused final-answer-grading request;
- invalid export with missing generation knobs.
- guide-backed rationale / hover explanation.
- v2 approved statistical plan with alternatives.
- v2 edited-design downgrade with all issue reporting.
- v2 post-run pairwise report.
- v2 leaderboard rank-stability report.
- v2 guarded launch refusal without confirmation.
- v2 guarded launch dry-run job fixture.

## CI Commands

Use repo-local commands where available:

```bash
ruff check .
ruff format --check .
pytest -q
```

Studio-specific checks, when frontend dependencies are available:

```bash
cd dmcp-studio/frontend
bun run check
```

If Windows local tooling is broken, record the exact failure and run focused
Python import/serialization smoke tests with the available interpreter.

## Manual Validation Steps

1. Open DMCP Studio.
2. Confirm Advisor appears before benchmark execution.
3. Submit finance long-workflow intent.
4. Confirm hypotheses, criteria, distribution, warnings, evidence ledger, and
   export preview render.
5. Hover over primary metric, criterion, task budget, and distribution fields;
   confirm each explanation cites the statistical reason.
6. Lower task budget enough to trigger underpowered warning/refusal.
7. Confirm refused design cannot be exported.
8. Confirm no generation/evaluation starts during Advisor interaction.
9. In v2, confirm "Carry to Collect" persists advisor state rather than only
   navigating.
10. Edit budget/distribution fields and confirm all validation issues appear.
11. Confirm launch requires explicit confirmation and shows a command preview.
12. Confirm a completed outcome-tensor fixture renders a statistical report with
   allowed and not-allowed claims.
