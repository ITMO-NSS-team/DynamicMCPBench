# DynamicMCPBench — master plan & claim ledger

This is the **single living source of truth** for the road to a finished paper.
It is both the roadmap (ordered, dependency-aware steps) and the **claim ledger**
that lets several Claude Code agents work in parallel without colliding. The loop
that drives it is `/continue`; the full protocol is in `docs/AUTONOMY.md`.

**How to work this file:** don't hand-edit statuses during the loop — the scripts
do it atomically. To advance the project, run `/continue` (or say «продолжи»),
which does **exactly one step** then asks before continuing. The plan evolves
toward realizing the ideas from *all* the planning docs (`docs/CONCEPT.md`) while
keeping the headline thesis (`memory/feedback_agb_orthogonality.md`), but **changes
to the step set (adding / splitting / re-sequencing steps, promoting an Idea) must
be proposed to a human and confirmed before they are applied** — the loop never
self-edits the plan's structure.

## Step format (machine-parsed by scripts/claim.py & scripts/mark.py)

```
### <id> — <title>
- status: todo | claimed | in_review | done | blocked
- owner: —                      (set by claim.py)
- claimed_at: —                 (set by claim.py)
- deps: <id> <id> | —           (a step is eligible only when all deps are done)
- source: <which doc/RQ motivates it>
- done-when: <concrete, checkable acceptance criteria>
```

`status` legend — **todo**: free to claim. **claimed**: an agent owns it.
**in_review**: PR open. **done**: merged. **blocked**: needs a human (see note).

---

## E0 — Bootstrap the autonomous loop

### E0.1 — Plan ledger, /continue runbook, scripts, env
- status: done
- owner: bootstrap
- claimed_at: 2026-06-01
- deps: —
- source: user request 2026-06-01
- done-when: docs/PLAN.md + docs/AUTONOMY.md + .claude/commands/continue.md + scripts/{bootstrap,agent_id,check}.sh + scripts/{claim,mark}.py + tests/test_smoke.py merged; CLAUDE.md/README link the loop; memory updated; env on itmo-laba bootstrapped; gate green; this PR merged via the loop itself.

---

## E1 — Finish the trace-native rev.3 (README roadmap)

### E1.1 — pass^k reliability metric
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: README Phase 3 / research_plan RQ4 / tau-bench
- done-when: `dmcp eval --repeat K` runs each spec K times against replay and records per-spec pass^k (= fraction of K runs that fully pass); report.py shows a pass^k column; unit test covers the aggregation.

### E1.2 — Tier-3 LLM tool simulator
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: README Phase 1 / research_landscape (MirrorAPI / StableToolBench)
- done-when: on a replay cache miss AND Tier-2 miss, an LLM produces a plausible tool result flagged `simulated=true` in the step; off by default behind a flag; deterministic seed/prompt; unit test on the miss→simulate path.

### E1.3 — External candidate-trace ingestion in `dmcp eval`
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: README Phase 3
- done-when: `dmcp eval --candidate-traces <file>` scores externally-produced trajectories (so others can score their own runs against our specs) without re-running an agent; unit test.

### E1.4 — Persona-seeding library for goal-gen
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: README Phase 2 / research_plan 2A
- done-when: a curated persona/intent set feeds `goal_gen.py`; generated goals show measurably higher diversity than the free-form baseline on a small sample; unit test that personas flow through.

### E1.5 — Decay metrics over time in refresh
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: README Phase 4 / research_plan 4B
- done-when: `refresh.py` records per-server drift rate across runs and `report.py` surfaces a decay table; retry-with-backoff for transient flakes; unit test on classification.

---

## E2 — Sampling / SAE / degradation curves (trace-frame; MVP + PDF)

### E2.1 — Eval-side tool-pool sampler (`dmcp/sampling.py`)
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: simple_approach.md §5.2 / PDF
- done-when: new module implements 6 strategies (random, hard_neg, cross_domain, same_name, sibling, stratified) selecting distractor tools/servers from `manifest.configs()` around a spec's required tools; deterministic with a seed; unit tests per strategy.

### E2.2 — Embedding index for hard-negative mining
- status: todo
- owner: —
- claimed_at: —
- deps: E2.1
- source: simple_approach.md §3.3, §5.2
- done-when: tool descriptions embedded + cached; hard_neg/cross_domain strategies use cosine similarity with a pinned model+seed; fallback to lexical similarity when no embedding key; unit test on ranking.

### E2.3 — SAE metric + expected/random subtypes
- status: todo
- owner: —
- claimed_at: —
- deps: E2.1
- source: PDF §5.1 / simple_approach.md §7.1
- done-when: `evaluator.py` reports Server Attribution Error (right tool type from the spec's equivalence_set, wrong server) split into expected vs random; only meaningful in Target/Full pool modes; unit test with a synthetic confused trace.

### E2.4 — P_alt degradation curves + Gold/Target/Full modes
- status: todo
- owner: —
- claimed_at: —
- deps: E2.1 E2.3
- source: PDF §4.3-4.5 / simple_approach.md §6
- done-when: `dmcp eval --pool gold|target|full --p-alt X` controls distractor density; a driver sweeps P_alt ∈ {0,.25,.5,.75,1} and emits accuracy/SAE-vs-P_alt curves; report includes the curve table.

### E2.5 — Error taxonomy E1–E7 with weights
- status: todo
- owner: —
- claimed_at: —
- deps: E2.3
- source: PDF §5.2
- done-when: failed evaluations are classified into the 7-type taxonomy with the documented default weights; report shows the error-type breakdown; unit tests on classification.

### E2.6 — Description normalization Level A / Level B
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: PDF §4.2 / simple_approach.md §6.2
- done-when: a normalizer rewrites tool descriptions to Level A (surface) / Level B (semantic augmentation); eval can run A vs B; documents the effect as a controlled variable; unit test on the templating.

---

## E3 — Scale the server substrate

### E3.1 — Expand the curated manifest
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: research_plan Phase 1 / README Phase 1
- done-when: `manifests/local.json` grows with more vetted public-API + sandboxed servers (each tagged dynamism + sandbox), all smoke-passing; manifest validates.

### E3.2 — Wire the docker-compose stack as a manifest
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: docker-compose-mcp.yaml
- done-when: a `manifests/compose.json` targets the compose-launched MCP servers (postgres/mongo/neo4j/qdrant/redis/... via http/sse); a documented `docker compose up` brings them up; smoke-vet passes for the reachable ones.

### E3.3 — Credentialed manifest tier (Bucket A)
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: docs/credentials_bucket_a.md / README Phase 1
- done-when: servers needing keys are env-plumbed from `.env` (never committed); a `manifests/credentialed.json` is gated on present keys; missing keys skip the server gracefully.

---

## E4 — Baselines & experiments (RQ1–RQ4)

### E4.1 — Backward graph-sampling generator (RQ2 baseline)
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1
- source: PDF / research_plan RQ2 / AGB
- done-when: a comparison-only generator builds a tool graph from schemas and back-instructs tasks; clearly labeled a *baseline* (not the headline path) per memory/feedback_agb_orthogonality.md; produces TaskSpecs comparable to the forward path.

### E4.2 — Direct-generation generator (RQ2 baseline)
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1
- source: research_plan RQ2 / MCPEval
- done-when: a generate-then-verify baseline produces TaskSpecs from tool specs directly; comparable output format.

### E4.3 — RQ1 headline: answer-match vs trace-align
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1
- source: research_plan RQ1
- done-when: a harness scores the same agents two ways (final-answer string match vs trace/effect alignment) on live_read/stateful tasks, re-run over time; reports ranking instability (Kendall's τ) and false-fail rate.

### E4.4 — RQ3 trace-property failure model
- status: todo
- owner: —
- claimed_at: —
- deps: E2.4
- source: research_plan RQ3
- done-when: fit a model on (depth, branching, state_coupling, cross_server, dynamism) → pass/fail per model; report feature importances.

### E4.5 — RQ4 scorer-vs-human + 200-task validation subset
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1
- source: research_plan RQ4
- done-when: a 200-task subset + annotation protocol; report Tier-1/Tier-2 agreement with human consensus (Cohen's κ / Krippendorff's α).

### E4.6 — ≥5-model leaderboard
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1
- source: README Phase 3
- done-when: leaderboard covers ≥5 candidate models (GPT-4o, Gemini, Sonnet 4.x, an open-weight 70B+, plus current set) in replay mode; report regenerated.

---

## E5 — Paper & release

### E5.1 — Paper scaffold (LaTeX, §1–§7 skeleton)
- status: todo
- owner: —
- claimed_at: —
- deps: E4.3
- source: research_plan Phase 5
- done-when: `paper/` holds a NeurIPS/EMNLP-style skeleton with the section plan, the AGB-contrast paragraph, and auto-pulled figure/table placeholders.

### E5.2 — HuggingFace dataset release packaging
- status: todo
- owner: —
- claimed_at: —
- deps: E4.6
- source: research_plan Phase 5
- done-when: a `dmcp release` packages specs + reference traces into a HF-loadable dataset layout (under a tracked `datasets/` path, not the git-ignored working dirs) with a datasheet.

---

## CC — Cross-cutting (ongoing)

### CC.1 — Grow the test suite
- status: in_review
- owner: bootstrap
- claimed_at: 2026-06-01
- deps: —
- source: governance / no tests existed
- done-when: `tests/` seeded (E0) and every code step adds tests; pytest is part of the gate.

### CC.2 — Optional CI workflow
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: governance
- done-when: a GitHub Actions workflow runs the gate on PRs (only when the team opts in — currently the local gate is the guard).

### CC.3 — Ruff-format baseline + strict format gate
- status: todo
- owner: —
- claimed_at: —
- deps: E0.1
- source: governance / E0 found 15 pre-existing unformatted files
- done-when: `uv run ruff format .` applied repo-wide in a dedicated format-only PR; then `scripts/check.sh` re-enables `ruff format --check .` as a hard gate step.

---

## Idea backlog (un-sequenced; loop may promote to steps)

- Semantic-cache (Tier-2) tuning study: threshold sweep vs human-judged equivalence.
- LLM dynamism reclassification when heuristic disagrees with observed drift (vet.py).
- Mine the full registry discovery scan for more no-creds public-API servers (Bucket B).
- Cross-server credentialed scenarios once E3.3 lands.
- Architecture comparison: flat agent vs RAG-MCP vs hierarchical router (research_landscape).
- Empirical calibration of error-taxonomy weights via pairwise human severity judgments.
