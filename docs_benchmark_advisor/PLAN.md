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
- status: deferred (not a blocker) — **[Adopted: D3]** the current
  `STATISTICAL_GUIDE.md` is frozen as `statistical_guide.v1` and is sufficient to
  ship the demo; the expert literature-review refresh is future work and a stated
  paper limitation. Downstream tasks may cite the existing rule ids now.
- note: an initial guide draft exists; this human-led step reviews current
  papers/methodology, improves the guide, then freezes it for implementation
  use.
- owner: -
- claimed_at: -
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
- deps: BA1.2 (satisfied by D3 — guide frozen as v1)
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

---

## BA2 - Advisor reasoning core

### BA2.1 - Deterministic validator
- status: todo
- owner: -
- claimed_at: -
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T02-deterministic-validator.md`
- done-when: structured `AdvisorDesign` validation emits deterministic
  approvals, warnings, refusals, and repair suggestions for underpowered budget,
  too few repeats, low cross-server coverage, invalid distributions, overbroad
  claims, missing guide references, and unknown guide rule ids; no LLM is called.

### BA2.2 - Planner adapter
- status: todo
- owner: -
- claimed_at: -
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T03-planner-adapter.md`
- note: **[Adopted: D1]** the default planner is rule-based and deterministic
  (booth-safe REPLAY); the LLM planner is the opt-in LIVE-mode path. Both satisfy
  the done-when below.
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

---

## BA3 - Studio surface and export preview

### BA3.1 - Studio API routes
- status: todo
- owner: -
- claimed_at: -
- deps: BA2.1 BA2.2 BA2.3 BA1.3
- source: `planning/TASKS/T05-studio-api.md`
- done-when: Studio exposes `POST /api/advisor/design` and
  `POST /api/advisor/validate`; route tests use golden fixtures; responses are
  schema-valid and include warnings/refusals/export preview without launching
  benchmark generation.

### BA3.2 - Studio UI shell
- status: todo
- owner: -
- claimed_at: -
- deps: BA1.1 BA1.2 BA1.3
- source: `planning/TASKS/T06-studio-ui-shell.md`
- note: **[Adopted: D6]** ship as **Stage 0 — Design** prepended to the existing
  single-page instrument (Design → Collect → Explore → Distill → Score) on the
  SIGNAL identity; signature interaction is the task-budget slider flipping the
  verdict approved ⇄ warning ⇄ refused with guide-cited hover rationale.
- done-when: the first-stage Advisor screen renders intent input, numeric
  editable fields, design cards, warnings/refusals, JSON preview, approval
  affordance, and hover/popover rationale for criteria and major numeric
  parameters using fixture/API shapes only.

### BA3.3 - Export handoff preview
- status: todo
- owner: -
- claimed_at: -
- deps: BA1.1 BA3.1
- source: `planning/TASKS/T07-export-handoff.md`
- done-when: approved/warning designs produce generation-ready JSON shape and
  missing required knobs fail validation; no `goal-gen`, `explore`, `distill`,
  or `eval` path is launched.

---

## BA4 - Integration and hardening

### BA4.1 - End-to-end integration smoke
- status: todo
- owner: -
- claimed_at: -
- deps: BA3.1 BA3.2 BA3.3 BA1.3
- source: `planning/TASKS/T09-integration-smoke.md`
- done-when: a demo scenario runs from intent to user-approved export preview
  across core, planner, validator, API, UI, and export adapter; backend route
  smoke, UI build/render check, and export validation pass; no benchmark run is
  launched.

### BA4.2 - Hardening review
- status: todo
- owner: -
- claimed_at: -
- deps: BA4.1
- source: `planning/TASKS/T10-hardening-review.md`
- note: **[Adopted: D4]** trimmed for the paper to a representative adversarial
  subset (overclaiming, missing/unknown guide refs, refusal, invariant checks)
  rather than full gold-plating; the rest stays backlog.
- done-when: adversarial tests cover overclaiming, missing/unknown guide
  references, invalid designs, refusal behavior, invariant violations, and
  accidental Stage 2 scope creep; docs explain limitations clearly.

---

## BA5 - Stage 2 backlog

**[Adopted: D4]** Out of scope for the EMNLP demo paper — Stage 2 stays
interface-only. These are intentionally unsequenced until Stage 1 lands.

- Implement validation report generation from outcome tensors.
- Add user-queryable post-run statistical summaries.
- Add judge-based validation of rationale quality.
- Consider RAG or external statistical libraries for guide expansion after v1
  contracts prove useful.
- Connect export preview to a guarded generation launch flow after explicit
  human approval.
