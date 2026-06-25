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

## Integration Tests

- `POST /api/advisor/design` returns `AdvisorResponse` for golden requests.
- `POST /api/advisor/validate` validates user-edited structured design.
- A legacy `/api/advisor` route, if retained, is not the only passing contract
  route.
- Refused response contains no exportable launch action.
- Clarification response contains no export config.
- Warning response contains warning cards and export preview.
- API route tests confirm no benchmark generation/evaluation function is called.

## Smoke Tests

- UI fixture render for approved, warning, refused, and smoke-test-only states.
- UI fixture render for hover rationale on criteria and major numeric
  parameters.
- End-to-end local smoke: request -> planner -> validator -> response -> export
  preview.
- Static frontend build/typecheck if toolchain is available.

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
