# Benchmark Advisor — adoption decisions for the EMNLP demo paper

Status: adoption record layered on top of the frozen v1 contracts.
Owner: jrzkaminski · Date: 2026-06-25

This file records the decisions taken when the Benchmark Advisor plan was merged
to `main` and re-scoped for one concrete purpose: **fold the advisor into the
existing DMCP Studio demo and present it in the same EMNLP demo-track paper** (not
a separate demo venue). The colleague's frozen contracts
(`planning/INTERFACES.md`, `planning/STATISTICAL_GUIDE.md`) are **unchanged** — these
are scoping and default-behavior decisions layered on top, not contract edits.

Where a decision here conflicts with prose elsewhere in `docs_benchmark_advisor/`,
this file wins until a follow-up PR reconciles the wording.

---

## D1 — Deterministic-first planner (default), LLM planner is the LIVE option

The planner adapter (BA2.2 / T03) ships a **rule-based deterministic planner as the
default**, mirroring the studio's REPLAY/LIVE split. An LLM planner is the opt-in
LIVE-mode path, not the default.

**Why:** the studio's whole identity is *deterministic, booth-safe REPLAY by
default*; a deterministic planner keeps the demo reproducible (identical figure
twice), makes the validator tests trivial, and honors the repo invariant that
fair comparison and replay are deterministic and machine-independent. The
`planner proposes → deterministic validator decides → UI explains` rule is
preserved either way; this only pins which proposer is the default.

## D2 — Reuse the statistical primitives already in `dmcp`

Planning statistics (BA2.3 / T04) **reuse existing tested helpers** instead of
adding new ones:

- `dmcp/curves.py::proportion_ci` — Wilson score interval (`ci_method: wilson_score`).
- `dmcp/ablation.py::power_n` — two-proportion sample size / MDE heuristic
  (`mde_method: normal_approx_two_proportion`).

This is the sanctioned dependency direction from `planning/ARCHITECTURE.md`
("Advisor module may depend on existing lightweight statistical helpers in `dmcp`").
New stats code is added only where these two don't cover a contract field
(e.g. paired-bootstrap planning heuristic), and is labeled `planning_heuristic`.

## D3 — Freeze the refreshed statistical guide as v1

`planning/STATISTICAL_GUIDE.md` (`guide_version: statistical_guide.v1`, families
G1–G7) is treated as **frozen and sufficient to ship the demo** after the
2026-06-27 human-curated research refresh. The refresh preserves the original
rule ids, expands the v1 rule-id set, and records evidence-status labels, source
keys, repair suggestions, procedure notes, and a source reference map. Downstream
tasks and fixtures cite this refreshed v1 guide rather than reinterpret the
literature.

## D4 — Paper scope: Stage 1 end-to-end; defer Stage 2 backlog and heavy hardening

Build the full Stage-1 loop end to end — schema → deterministic planner →
validator → stats → API → UI → export — with enough golden fixtures and tests to
pass the repo gate and prove the validator's approve/warn/refuse behavior.

**Deferred** (not needed for the paper, kept in the backlog):

- BA5 Stage-2 backlog (outcome tensors, post-run reports, judge-based rationale
  scoring) stays interface-only.
- BA4.2 / T10 adversarial-hardening gold-plating and the full 13-fixture golden set
  are trimmed to a representative subset (pairwise valid, leaderboard warning,
  underpowered refusal, diagnostic, clarification, edited-field revalidation) —
  enough to cover every response state without gold-plating.

## D5 — Module location: top-level `benchmark_advisor/` package

The implementation lives in a **top-level `benchmark_advisor/` package**, imported
by the studio backend. It is **not** placed inside `dmcp/` core. This satisfies the
architecture's dependency-direction rule (studio → advisor → `dmcp` helpers; advisor
never imports studio) and is auto-collected by the repo's root `pytest`.

## D6 — UI placement: a new "Stage 0 — Design" in the existing instrument

The advisor is presented as **Stage 0 — Design**, prepended to the existing
single-page instrument so the studio reads as one continuous pipeline:

```text
Stage 0 Design → Stage 1 Collect → Stage 2 Explore → Stage 3 Distill → Stage 4 Score
```

**Signature interaction:** dragging the task-budget slider flips the design verdict
**approved ⇄ warning ⇄ refused** live, with hover rationale citing a versioned guide
rule (e.g. `G3.coverage.cross_server`). This deliberately rhymes with the studio's
existing Effect⇄Answer verdict-flip — two parallel "the verdict flips, and that flip
is the point" moments across one instrument, on the SIGNAL visual identity.

**Why this placement:** demo-track reviewers reward one coherent system over a
feature list; Stage 0 closes the obvious "is the generated benchmark statistically
sound enough to support the claim?" question *before* expensive generation, and it
needs only one figure to tell the whole pipeline story.

---

## What did NOT change

- No final-answer grading is introduced anywhere.
- The advisor never auto-launches `goal-gen`, `explore`, `distill`, or `eval`.
- `planning/INTERFACES.md` enum registries, state matrix, and validator thresholds
  are normative and untouched.
- `planning/STATISTICAL_GUIDE.md` keeps `guide_version: statistical_guide.v1`;
  the original rule ids are preserved and the refreshed v1 set is mirrored in
  `benchmark_advisor/guide.py`.
- All `docs_benchmark_advisor/CONCEPT.md` hard invariants remain in force.
