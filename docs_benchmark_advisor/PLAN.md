# Benchmark Advisor - master plan and claim ledger

This is the advisor-local equivalent of `docs/PLAN.md`: the roadmap and claim
ledger for implementing Benchmark Advisor as a statistically aware pre-run
planning module for DMCP Studio.

The "why" and component catalogue are in `docs_benchmark_advisor/CONCEPT.md`.
The work protocol is in `docs_benchmark_advisor/AUTONOMY.md`. Detailed contracts
and task packets are under `docs_benchmark_advisor/planning/`.

**Adoption note (2026-06-25):** this plan was merged to `main` and re-scoped to
fold the advisor into the existing DMCP Studio demo for the EMNLP demo paper. The
adoption decisions (deterministic-first planner, reuse of `dmcp` stats, guide
frozen as v1, Stage-0 UI placement, paper-scope trims) are recorded in
`docs_benchmark_advisor/ADOPTION.md` and annotated inline below as **[Adopted: …]**.
Where this plan's prose and `ADOPTION.md` disagree, `ADOPTION.md` wins until a
follow-up PR reconciles them.

**How to work this file:** one step should map to one PR. The advisor ledger is
not yet connected to `scripts/claim.py`; if a fully automated loop is desired,
promote or wire these steps only after human approval. Until then, contributors
should claim work in PR descriptions or coordination chat and keep the step's
scope aligned with its task packet.

**V1 target:** Studio can take user intent, propose a statistically grounded
benchmark design, explain the rationale for major parameters, validate/refuse
deterministically, and export a JSON config preview without launching generation
or evaluation.

## Step format

```text
### <id> - <title>
- status: todo | claimed | in_review | done | blocked
- owner: -
- claimed_at: -
- deps: <id> <id> | -
- source: <planning doc / task packet>
- done-when: <concrete, checkable acceptance criteria>
```

---

## BA0 - Advisor planning bootstrap

### BA0.1 - Advisor concept, contracts, and ledger
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-24
- deps: -
- source: user planning request; `planning/TASKS/T00-planning-docs.md`
- done-when: `docs_benchmark_advisor/CONCEPT.md`, `AUTONOMY.md`, `PLAN.md`,
  `planning/MODULE_SPEC.md`, `planning/ARCHITECTURE.md`,
  `planning/INTERFACES.md`, `planning/TASK_GRAPH.md`,
  `planning/INTEGRATION_PLAN.md`, `planning/TEST_STRATEGY.md`, and task packets
  exist; v1 interfaces and human-approval boundaries are documented.

---

## BA1 - Contracts, guide, and fixtures

### BA1.1 - Core schema layer
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA0.1
- source: `planning/TASKS/T01-core-schema.md`
- note: **[Adopted: D5]** schemas live in a top-level `benchmark_advisor/` package
  (imported by the studio backend; never inside `dmcp/` core). Implemented in
  `benchmark_advisor/schema.py` + `tests/test_benchmark_advisor_schema.py`; the
  `response_state_violations` helper enforces the state matrix; package added to
  the hatch wheel targets.
- done-when: Pydantic v2 schemas exactly match `planning/INTERFACES.md`,
  forbid unknown fields, round-trip golden fixture shapes, include
  `StatisticalGuideReference`, and serialize `ExportConfig`.

### BA1.2 - Human statistical guide curation and v1 freeze
- status: done — **[Adopted: D3]** the refreshed `STATISTICAL_GUIDE.md` is
  integrated as `statistical_guide.v1`; the version remains stable, old rule ids
  are preserved, and runtime validation knows the expanded rule-id set.
- note: human-curated refresh integrated on 2026-06-27 with source keys,
  evidence-status labels, validator behavior, repair suggestions, procedure
  notes, and a source reference map.
- owner: kmetra1910
- claimed_at: 2026-06-27
- deps: BA0.1
- source: `planning/TASKS/T03a-statistical-guide.md`;
  `planning/STATISTICAL_GUIDE.md`
- done-when: `STATISTICAL_GUIDE.md` has been improved by a human-curated review
  of current/relevant statistical and benchmark-evaluation sources; each major
  rule family has a source rationale or explicit expert-default label; stable
  `statistical_guide.v1` rule ids cover intent mapping, metrics, task
  distribution, budget/power, criteria, claim boundaries, and UI rationale;
  downstream tasks can cite rule ids without inventing statistical knowledge.

### BA1.3 - Golden advisor fixtures
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA1.2 (done — guide refreshed and frozen as v1)
- source: `planning/TASKS/T08-golden-fixtures.md`
- note: 14 fixtures in `docs_benchmark_advisor/fixtures/` (+ README) spanning every
  response state and validator-threshold family; loader + structural tests in
  `tests/advisor_fixtures.py` and `tests/test_benchmark_advisor_fixtures.py`
  (requests parse against BA1.1, cited guide ids exist, state-matrix consistent).
- done-when: valid, warning-heavy, refused, clarification, and smoke fixtures
  exist; at least 10 intent fixtures cover pairwise, leaderboard, regression,
  and diagnostic scenarios; guide references and hover rationale are present;
  fixtures conform to `planning/INTERFACES.md` and are ready to parse against
  schemas once BA1.1 lands.

### BA1.4 - Statistical guide extension for distractor and domain intent
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-27
- deps: BA1.2
- source: user follow-up on advisor intent extraction; `planning/STATISTICAL_GUIDE.md`
- note: covered by the refreshed guide plus a dedicated registry test for the
  required BA1.4 `G3.*` ids; downstream BA2.4/BA2.5 still own planner extraction
  and validator behavior.
- done-when: `STATISTICAL_GUIDE.md` includes v1 rule ids and source rationale
  for short/medium/long workflow intent, domain/category extraction such as
  finance, hard-negative / near-miss / same-name distractor pressure, and the
  boundary between diagnostic distractor-heavy designs and confirmatory pairwise
  designs; runtime guide registry and tests know the new `G3.*` ids.

---

## BA2 - Advisor reasoning core

### BA2.1 - Deterministic validator
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T02-deterministic-validator.md`
- note: `benchmark_advisor/validator.py` (+ `benchmark_advisor/guide.py` runtime
  rule-id registry, kept in sync with the doc by a test). Deterministic, no LLM,
  structured-fields-only. Enforces budget bands, target-vs-MDE power, pass@3
  repeats, category-claimed coverage, distribution sums + stateful-write/sandbox,
  diagnostic-not-selection, unknown-guide-id refusal, and clarification on missing
  candidate models, resolved by the state-matrix precedence
  refused > clarification > warning > approved.
- done-when: structured `AdvisorDesign` validation emits deterministic
  approvals, warnings, refusals, and repair suggestions for underpowered budget,
  too few repeats, low cross-server coverage, invalid distributions, overbroad
  claims, missing guide references, and unknown guide rule ids; no LLM is called.

### BA2.2 - Planner adapter
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T03-planner-adapter.md`
- note: **[Adopted: D1]** the default planner is rule-based and deterministic
  (booth-safe REPLAY); the LLM planner is the opt-in LIVE-mode path. Implemented
  in `benchmark_advisor/planner.py` (intent→`AdvisorDesign` + guide-backed evidence
  ledger; intent-level refusals for final-answer/generation-launch; clarification
  on missing candidate models). `tests/test_benchmark_advisor_planner.py` includes
  the full planner+validator end-to-end check reproducing all 14 fixture oracles.
- done-when: user intent converts into schema-valid advisor proposals using
  LLM/rule adaptation; every criterion and major user-visible parameter cites
  statistical-guide rule ids and includes hover-ready rationale; invalid or
  ambiguous intents become clarification/refusal-ready proposals.

### BA2.3 - Planning statistics helpers
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA1.1
- source: `planning/TASKS/T04-planning-statistics.md`
- note: **[Adopted: D2]** reuse `dmcp/curves.py::proportion_ci` (Wilson) and
  `dmcp/ablation.py::power_n` (two-proportion MDE) rather than reimplementing
  them; add new code only for contract fields they don't cover. Implemented in
  `benchmark_advisor/stats.py` (+ `tests/test_benchmark_advisor_stats.py`):
  planned MDE, CI width, budget→MDE curve, coverage diagnostics with the
  INTERFACES threshold bands (single source of truth for the validator), all
  labeled `planning_heuristic`.
- done-when: pre-run CI width, MDE/power heuristics, coverage diagnostics, and
  warning thresholds are deterministic, tested, and labeled as planning
  heuristics rather than final inference.

### BA2.4 - Intent extraction and distribution tuning
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-27
- deps: BA2.2 BA2.1 BA1.2 BA1.4
- source: user follow-up on advisor demo query; `planning/TASKS/T03-planner-adapter.md`
- note: implemented in `benchmark_advisor/planner.py` with guide-backed
  extraction for finance/domain, short-chain, same-name, near-miss, and
  hard-negative signals. Covered by the
  `pairwise-short-finance-hard-negative` fixture and
  `test_short_finance_hard_negative_intent_tunes_distribution`.
- done-when: deterministic planner extracts domain, chain-length, distractor,
  and diagnostic-pressure signals from user intent. The query "Compare two local
  agents on short step finance workflows and tell me which is better. There
  should be hard negative tools with similar names that would test them" remains
  pairwise, raises short-chain coverage, includes finance/domain and distractor
  pressure categories, raises same-name and near-miss distractor fractions above
  defaults, and records evidence-ledger rationale for those choices.

### BA2.5 - Validator checks for distractor-pressure claims
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-30
- deps: BA1.4 BA2.1 BA2.4
- source: user follow-up on advisor demo query; `planning/TASKS/T02-deterministic-validator.md`
- note: implemented in `benchmark_advisor/validator.py` via deterministic
  `DISTRACTOR_CLAIMS` checks for `same_name`, `near_miss`, and `hard_negative`.
  Covered by `test_low_distractor_pressure_warns_when_claimed` and
  `test_very_low_distractor_pressure_refused_when_claimed`.
- done-when: if structured categories claim `same_name`, `near_miss`, or
  `hard_negative` pressure, validator checks corresponding distractor fractions
  against documented thresholds and emits deterministic warning/refusal rather
  than silently approving default-low distractor pressure.

---

## BA3 - Studio surface and export preview

### BA3.1 - Studio API routes
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA2.1 BA2.2 BA2.3 BA1.3
- source: `planning/TASKS/T05-studio-api.md`
- note: composition in `benchmark_advisor/service.py` (planner→validator→export,
  state-matrix-correct `AdvisorResponse`); thin routes `POST /api/advisor/design`
  and `POST /api/advisor/validate` in `dmcp-studio/backend/app.py`. Tests:
  `tests/test_benchmark_advisor_service.py` + `dmcp-studio/backend/tests/test_studio_advisor.py`.
  No generation/eval launched; existing studio routes still green.
- done-when: Studio exposes `POST /api/advisor/design` and
  `POST /api/advisor/validate`; route tests use golden fixtures; responses are
  schema-valid and include warnings/refusals/export preview without launching
  benchmark generation.

### BA3.2 - Studio UI shell
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-26
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T06-studio-ui-shell.md`
- note: **[Adopted: D6]** shipped as **Stage 0 — Design** prepended to the
  single-page instrument (Design → Collect → Explore → Distill → Score) on the
  SIGNAL identity. Intent box + mode + candidate models + three instrument
  sliders; the task-budget slider flips the verdict approved ⇄ warning ⇄ refused
  live against `/api/advisor/design`, with guide-cited evidence-ledger hover
  rationale, advisor cards, and a dry-run JSON export preview. Distinct
  `.stage-design`/`.step-design` classes keep the existing JS flow untouched;
  `app.ts` four-stage handlers unchanged (one `gotoStep` guard). Headless capture
  regenerates `fig_studio.png` and adds `fig_advisor.png`.
- done-when: the first-stage Advisor screen renders intent input, numeric
  editable fields, design cards, warnings/refusals, JSON preview, approval
  affordance, and hover/popover rationale for criteria and major numeric
  parameters using fixture/API shapes only.

### BA3.3 - Export handoff preview
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-25
- deps: BA1.1 BA3.1
- source: `planning/TASKS/T07-export-handoff.md`
- note: `benchmark_advisor/export.py` builds the JSON `ExportConfig` (dry-run-only
  guard, mode→goal_strategy, distractors mirror, sandbox rule) for approved/warning
  designs only; refused/clarification expose no export. `tests/test_benchmark_advisor_export.py`.
  Bundled with BA3.1 since the service needs the export builder.
- done-when: approved/warning designs produce generation-ready JSON shape and
  missing required knobs fail validation; no `goal-gen`, `explore`, `distill`,
  or `eval` path is launched.

---

## BA4 - Integration and hardening

### BA4.1 - End-to-end integration smoke
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-26
- deps: BA3.1 BA3.2 BA3.3 BA1.3
- source: `planning/TASKS/T09-integration-smoke.md`
- note: `tests/test_benchmark_advisor_integration.py` — intent→export across
  core/planner/validator/service/export, refused & clarification not exportable,
  a static guard that the advisor never imports generation/eval modules, and a
  Stage-0-UI-wired-to-the-API check. Browser-level smoke is `capture_screenshot.py`
  (both figures regenerate). Studio route smoke in `test_studio_advisor.py`.
- done-when: a demo scenario runs from intent to user-approved export preview
  across core, planner, validator, API, UI, and export adapter; backend route
  smoke, UI build/render check, and export validation pass; no benchmark run is
  launched.

### BA4.2 - Hardening review
- status: done
- owner: jrzkaminski
- claimed_at: 2026-06-26
- deps: BA4.1
- source: `planning/TASKS/T10-hardening-review.md`
- note: **[Adopted: D4]** trimmed to a representative adversarial subset.
  `tests/test_benchmark_advisor_hardening.py` (invalid distribution, overbroad
  diagnostic, unknown guide id, final-answer, stateful/sandbox, budget boundaries,
  banned-overclaim sweep, state-matrix cleanliness, no-export rule, Stage-2 stays
  declared-only). `docs_benchmark_advisor/LIMITATIONS.md` lists allowed/disallowed
  claims and makes the statistical-knowledge sources explicit.
- done-when: adversarial tests cover overclaiming, missing/unknown guide
  references, invalid designs, refusal behavior, invariant violations, and
  accidental Stage 2 scope creep; docs explain limitations clearly.

---

## BA5 - Statistical Advisor v2

The v1 advisor is useful as a deterministic pre-run gate, but the next wave must
make statistics the center of the product. BA5 adds a v2 contract and statistical
engine while keeping all v1 routes compatible.

### BA5.0 - Durable gap memo
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-30
- deps: BA4.2
- source: `planning/ADVISOR_GAPS.md`
- note: implemented as `planning/ADVISOR_GAPS.md` in the v2 planning update.
- done-when: current advisor limitations are listed in a durable planning memo,
  including heuristic-only stats, no post-run report, brittle intent parsing,
  no real handoff, missing validate/edit UI, weak frontend schemas,
  first-refusal-only validator output, empty server-scope handoff, no dedicated
  Statistical Engine before parameter selection, and no v2 guide citation index.

### BA5.1 - Statistical Advisor v2 contract
- status: done
- owner: kmetra1910
- claimed_at: 2026-06-30
- deps: BA4.2
- source: `planning/TASKS/T11-v2-statistical-contract.md`
- note: implemented on `codex/ba5-0-5-1-stat-contract` with
  `benchmark_advisor/v2_schema.py`, additive v2 route request/response shapes,
  guarded launch/report contracts, and `tests/test_benchmark_advisor_v2_schema.py`.
- done-when: additive v2 schemas and route contracts exist for design,
  validation, report, and guarded launch; v1 contracts and tests remain
  compatible.

### BA5.2 - Guide citation index and optional source pack
- status: done
- owner: kmetra1910
- claimed_at: 2026-07-03
- deps: BA5.1 BA1.2
- source: `planning/TASKS/T12-local-statistical-knowledge-base.md`
- note: implemented as `benchmark_advisor/guide_citations.py` with deterministic
  offline parsing/auditing of `STATISTICAL_GUIDE.md` rule ids, section labels,
  evidence status, source keys, and snippets. `LocalStatisticalCitation` now
  carries `source_keys`; tests cover rule/method/mode lookup, missing source-key
  failures, and validator independence from guide snippet text.
- done-when: v2 can cite `STATISTICAL_GUIDE.md` rule ids, sections, source keys,
  and short guide-derived snippets without runtime network or vector retrieval.
  A larger human-approved retrieval corpus is explicitly optional/future work,
  not a blocker for the Statistical Engine MVP.

### BA5.3 - Guide-first v2 planner composition
- status: done
- owner: kmetra1910
- claimed_at: 2026-07-03
- deps: BA5.1 BA5.4 BA2.1 BA2.2
- source: `planning/TASKS/T13-dual-engine-planner.md`
- note: implemented as the first deterministic v2 composition layer:
  `benchmark_advisor/v2_engine.py` searches a finite candidate grid, calls the
  existing deterministic planner as a structured design factory, validates every
  candidate, attaches local guide citations, and emits a typed `EngineDecision`
  inside `StatisticalPlan`; `benchmark_advisor/v2_service.py` exposes
  guide-first v2 design/validate composition, and Studio routes
  `/api/advisor/v2/design` + `/api/advisor/v2/validate` are wired. This closes
  the T13 MVP without claiming the broader BA5.4 full-engine expansion is done.
- done-when: the v2 planner normalizes intent, selects claim/method constraints
  from `STATISTICAL_GUIDE.md`, calls the Statistical Engine, and composes the
  engine output into the v2 response. Final task budget, attempts, target
  effect, distribution, and confirmatory slice parameters come from engine
  scoring, and every proposal is clamped by deterministic validation before the
  API returns it. No RAG/stat-agent is required for the MVP.

### BA5.4 - Statistical Engine and real planning statistics
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.1 BA2.3 BA1.2
- source: `planning/TASKS/T14-real-planning-statistics.md`
- done-when: `planning/STATISTICAL_ENGINE_DESIGN.md` is implemented as a
  deterministic pre-recommendation engine; pre-run planning searches and scores
  candidate task budgets, attempts, effect targets, distributions,
  confirmatory/exploratory slices, missingness policies, and multiplicity
  policies; outputs expose power curves, MDE by design type, paired/unpaired
  assumptions, repeated-attempt caveats, stratification and rank-stability
  diagnostics, sensitivity analysis, and budget alternatives.

### BA5.5 - Post-run statistical report
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.1 BA5.4
- source: `planning/TASKS/T15-post-run-statistical-report.md`
- done-when: outcome tensors can be converted into scoped statistical reports
  for pairwise, leaderboard, regression, and diagnostic modes, including CIs,
  effect sizes, rank stability, missingness, multiplicity notes, and allowed /
  disallowed claims.

### BA5.6 - Statistical Advisor UI v2
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.1 BA5.3 BA5.4 BA5.5
- source: `planning/TASKS/T16-statistical-advisor-ui-v2.md`
- done-when: Studio renders claim cards, power curves, method cards, assumption
  panels, alternatives, repair actions, citations, and post-run report views
  using typed v2 frontend schemas.

---

## BA6 - Guarded handoff

BA6 connects an approved advisor design to corpus generation, but only through a
separate guarded launch layer. Design and validation routes must remain
side-effect free.

### BA6.1 - Persist advisor state through Studio
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.6
- source: `planning/TASKS/T16-statistical-advisor-ui-v2.md`;
  `planning/TASKS/T17-guarded-corpus-handoff.md`
- done-when: "Carry to Collect" stores the approved/warning v2 design and
  export in Studio state, including task budget, server scope, strategy,
  assumptions, validation status, and sandbox requirements.

### BA6.2 - Validate/edit UI
- status: todo
- owner: -
- claimed_at: -
- deps: BA6.1 BA5.1
- source: `planning/TASKS/T16-statistical-advisor-ui-v2.md`
- done-when: users can edit budget, attempts, models, server scope, effect
  target, task distribution, and sandbox fields; Studio calls
  `/api/advisor/v2/validate` and displays all issues after edits.

### BA6.3 - Guarded corpus launch backend
- status: todo
- owner: -
- claimed_at: -
- deps: BA6.1 BA5.3
- source: `planning/TASKS/T17-guarded-corpus-handoff.md`
- done-when: `/api/advisor/v2/launch` accepts only approved/warning exports with
  explicit confirmation, builds a deterministic `scripts/build_corpus.py`
  command preview, enforces sandbox guards, and starts a tracked background job
  only for corpus/specs/traces generation.

### BA6.4 - Job status and artifacts UI
- status: todo
- owner: -
- claimed_at: -
- deps: BA6.3
- source: `planning/TASKS/T17-guarded-corpus-handoff.md`
- done-when: Studio shows queued/running/succeeded/failed job status, command
  preview, logs, output paths, and generated goals/specs/traces artifacts.

### BA6.5 - Corpus-only first handoff
- status: todo
- owner: -
- claimed_at: -
- deps: BA6.3
- source: `planning/TASKS/T17-guarded-corpus-handoff.md`
- done-when: the first advisor launch path targets corpus/specs/traces through
  `scripts/build_corpus.py`; leaderboard/eval remains out of scope unless a
  separate task explicitly approves it.

---

## BA7 - Advisor v2 hardening and fixups

### BA7.1 - Intent robustness
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.3
- source: `planning/TASKS/T18-advisor-hardening-v2.md`
- done-when: normalized intent extraction handles "short finance workflows",
  synonyms, reordered wording, multilingual-ish phrasing, and negative cases
  without over-triggering categories.

### BA7.2 - Strong frontend schemas
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.6
- source: `planning/TASKS/T16-statistical-advisor-ui-v2.md`;
  `planning/TASKS/T18-advisor-hardening-v2.md`
- done-when: v2 frontend schemas type advisor design, export, issue lists,
  statistical plan, launch job, and report objects; no v2 advisor core object is
  accepted as `unknown`.

### BA7.3 - Full issue reporting
- status: todo
- owner: -
- claimed_at: -
- deps: BA5.1 BA2.1
- source: `planning/TASKS/T18-advisor-hardening-v2.md`
- done-when: v2 validation exposes all blocking warnings/refusals with severity
  and repair actions, while preserving status precedence
  refused > clarification > warning > approved.

### BA7.4 - Docs, fixtures, and limitations sync
- status: todo
- owner: -
- claimed_at: -
- deps: BA7.1 BA7.2 BA7.3 BA6.5
- source: `planning/TASKS/T18-advisor-hardening-v2.md`
- done-when: `PLAN.md`, `TASK_GRAPH.md`, task packets, `INTERFACES.md`,
  `TEST_STRATEGY.md`, fixtures, frontend schemas, backend schemas, and
  `LIMITATIONS.md` describe the same v2 behavior.
