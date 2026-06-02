# DynamicMCPBench — master plan & claim ledger

This is the **single living source of truth** for the road to a finished paper.
It is both the roadmap (ordered, dependency-aware steps) and the **claim ledger**
that lets several Claude Code agents work in parallel without colliding. The loop
that drives it is `/continue`; the full protocol is in `docs/AUTONOMY.md`; the
reasoning and the complete experiment catalogue are in `docs/CONCEPT.md`.

**How to work this file:** don't hand-edit statuses during the loop — the scripts
do it atomically. To advance the project, run `/continue` (or say «продолжи»),
which does **exactly one step** then asks before continuing. The plan evolves
toward realizing the ideas from *all* the planning docs (`docs/CONCEPT.md`) while
keeping the headline thesis (`memory/feedback_agb_orthogonality.md`), but **changes
to the step set (adding / splitting / re-sequencing steps, promoting an Idea) must
be proposed to a human and confirmed before they are applied** — the loop never
self-edits the plan's structure.

**Paper-critical scale target:** the substrate must reach **100+ vetted MCP
servers** (ideally several hundred) — this is a headline differentiator (epic E3).

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

---

## E0 — Bootstrap the autonomous loop

### E0.1 — Plan ledger, /continue runbook, scripts, env
- status: done
- owner: bootstrap
- claimed_at: 2026-06-01
- deps: —
- source: user request 2026-06-01
- done-when: docs/PLAN.md + docs/AUTONOMY.md + .claude/commands/continue.md + scripts/{bootstrap,agent_id,check}.sh + scripts/{claim,mark}.py + tests/test_smoke.py merged; CLAUDE.md/README link the loop; memory updated; dev env bootstrapped; gate green.

---

## E1 — Finish the trace-native rev.3 (README roadmap)

### E1.1 — pass^k reliability metric
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T14:13:37Z
- deps: E0.1
- source: simple_approach §6.4/7.4 / research_plan RQ4 / tau-bench
- done-when: `dmcp eval --repeat K` runs each spec K times against replay and records per-spec pass^k (= fraction of K runs that fully pass); report.py shows a pass^k column; a pass^k_no_SAE vs pass^k_overall split is recorded; unit test on the aggregation.

### E1.2 — Tier-3 LLM tool simulator
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T14:25:38Z
- deps: E0.1
- source: README Phase 1 / research_landscape (MirrorAPI / StableToolBench)
- done-when: on a replay cache miss AND Tier-2 miss, an LLM produces a plausible result flagged `simulated=true`; off by default behind a flag; deterministic seed/prompt; unit test on the miss→simulate path.

### E1.3 — External candidate-trace ingestion in `dmcp eval`
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T14:42:54Z
- deps: E0.1
- source: README Phase 3
- done-when: `dmcp eval --candidate-traces <file>` scores externally-produced trajectories without re-running an agent; unit test.

### E1.4 — Persona-seeding library for goal-gen
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T14:48:31Z
- deps: E0.1
- source: README Phase 2 / research_plan 2A
- done-when: a curated persona library + deterministic selection feed `goal_gen.py` (`use_personas`, `--no-personas` baseline); unit tests cover the library, selection, and persona prompt-injection. (Diversity validation moved to E1.4a.)

### E1.4a — Validate persona effect on goal diversity
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T15:11:24Z
- deps: E1.4
- source: user 2026-06-01 (investigate the E1.4 null result)
- done-when: the pre-registered experiment in `docs/experiments/e1.4a-persona-diversity.md` is run (richer servers, >=3 seeds, semantic primary metric) and that report is committed with a result classified positive/neutral/negative. Per the Results rule, a committed negative result is an acceptable outcome.

### E1.5 — Decay metrics over time + refresh backoff
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T15:01:52Z
- deps: E0.1
- source: README Phase 4 / research_plan 4B
- done-when: `refresh.py` records per-server drift rate across runs and `report.py` surfaces a decay table; retry-with-backoff for transient flakes; unit test on classification.

---

## E2 — Sampling / SAE / degradation curves (trace-frame; MVP + PDF)

### E2.1 — Eval-side tool-pool sampler (`dmcp/sampling.py`)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T15:12:37Z
- deps: E0.1
- source: simple_approach §5.2 / PDF
- done-when: new module implements 6 strategies (random, hard_neg, cross_domain, same_name, sibling, stratified) selecting distractors around a spec's required tools from the manifest pool; deterministic with a seed; unit tests per strategy.

### E2.2 — Embedding index for hard-negative mining
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T15:26:30Z
- deps: E2.1
- source: simple_approach §3.3/§5.2
- done-when: tool descriptions embedded + cached (pinned model+seed); hard_neg/cross_domain use cosine similarity with denoising; lexical fallback when no embedding key; unit test on ranking.

### E2.3 — Gold/Target/Full pool modes wired into eval
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T15:40:49Z
- deps: E2.1
- source: simple_approach §6.1 / PDF §4.5
- done-when: `dmcp eval --pool gold|target|full [--p-alt X --pool-size N]` builds the candidate tool pool accordingly via the sampler; replay still deterministic; unit test on pool construction.

### E2.4 — SAE metric + expected/random subtypes + conditional rate
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T15:57:31Z
- deps: E2.3
- source: PDF §5.1 / simple_approach §7.1
- done-when: `evaluator.py` reports SAE (right tool type per equivalence_set, wrong server), split expected vs random, plus SAE conditional rate; only meaningful in Target/Full modes; unit test with a synthetic confused trace.

### E2.5 — Error taxonomy E1–E7 with weights
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T16:13:22Z
- deps: E2.4
- source: PDF §5.2 / simple_approach §7.2
- done-when: failed evaluations are classified into the 7-type taxonomy with the documented default weights; report shows the weighted error breakdown; unit tests.

### E2.6 — Description normalization Level A / Level B
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T16:21:52Z
- deps: E0.1
- source: PDF §4.2 / simple_approach §6.2
- done-when: a normalizer produces Level A (surface) / Level B (semantic-augmented, rubric-templated) descriptions; eval runs A vs B; unit test on templating.

### E2.7 — P_alt degradation-curve driver + complexity bins
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T16:43:40Z
- deps: E2.3 E2.4
- source: simple_approach §7.3/§7.5 / PDF §4.3
- done-when: a driver sweeps P_alt ∈ {0,.25,.5,.75,1} per (strategy, level) and emits accuracy/SAE-vs-P_alt with CIs; results normalized by complexity bin (1 / 2 / 3–4+ required tools), micro+macro averaged.

### E2.8 — Ablation harness + statistics
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-01T17:09:12Z
- deps: E2.7 E2.5
- source: simple_approach §8
- done-when: runs the 5 contrasts (random/hard-neg/cross-domain/same-name/sibling/stratified) and tests H1–H3 with paired χ²/Fisher per cell + a mixed-effects logistic regression `correct ~ strategy + P_alt + level + (1|task) + (1|model)`, with Bonferroni/Holm correction; power-analysis note (≥150/cell); writes an ablation report.

---

## E3 — Scale the server substrate to 100+ (paper-critical)

### E3.1 — Large-scale crawl + vet to ≥100 vetted servers
- status: claimed
- note: re-claimed by Ilya per user direction 2026-06-01; infra+server-collection in progress on a branch; NO merge until user approves
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T17:20:19Z
- deps: E0.1
- source: research_plan Phase 1 / user 2026-06-01 (100+ target)
- done-when: the crawler ingests the full registry and (with parallel, timeout-bounded install + smoke-vet) produces a curated manifest of **≥100 vetted servers** (target several hundred) spanning static / live_read / stateful_write and many domains; deduped; each tagged + sandboxed where stateful; a funnel report (registry size → installable → vetted) is emitted.

### E3.2 — Scale-out hardening of crawl/install/vet
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: README Phase 1
- done-when: install/vet run concurrently with per-server timeouts and failure isolation; oci/docker packages supported where feasible; resumable crawl (checkpoint discovered/vetted JSONL); throughput documented.

### E3.3 — Wire the docker-compose stack as a manifest
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: docker-compose-mcp.yaml
- done-when: a `manifests/compose.json` targets the compose-launched servers (postgres/mongo/neo4j/qdrant/redis/...); documented `docker compose up`; smoke-vet passes for reachable ones; adds stateful_write breadth.

### E3.4 — Credentialed manifest tier (Bucket A)
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: docs/credentials_bucket_a.md / README Phase 1
- done-when: servers needing keys are env-plumbed from `.env` (never committed); a `manifests/credentialed.json` is gated on present keys; missing keys skip gracefully.

### E3.5 — Substrate coverage report
- status: todo
- owner: —
- claimed_at: —
- deps: E3.1
- source: research_plan §3 (substrate table)
- done-when: `report.py` (or a script) emits the paper's substrate table: server count, by dynamism, by domain, tool counts, mining funnel.

---

## E4 — Baselines & experiments (RQ1–RQ4)

### E4.1 — Backward graph-sampling generator (RQ2 baseline)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T18:48:19Z
- deps: E1.1
- source: PDF / research_plan RQ2 / AGB
- done-when: a comparison-only generator builds a tool graph from schemas and back-instructs tasks; clearly labeled a baseline (not the headline) per memory/feedback_agb_orthogonality.md; emits TaskSpecs comparable to the forward path.

### E4.2 — Direct-generation generator (RQ2 baseline)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T19:35:26Z
- deps: E1.1
- source: research_plan RQ2 / MCPEval
- done-when: a generate-then-verify baseline emits TaskSpecs from tool specs directly; comparable output format.

### E4.3 — RQ2 generation-quality comparison
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T19:40:53Z
- deps: E4.1 E4.2
- source: research_plan RQ2 / simple_approach §8 (3 comparison axes)
- done-when: forward vs graph-sampling vs direct compared on executable-on-first-try, human realism, distinct valid paths, coverage, unnecessary-tool rate, filter pass rate, and error-type diversity; report.

### E4.4 — RQ1 headline: answer-match vs trace-align
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-02T10:08:50Z
- deps: E1.1
- source: research_plan RQ1
- done-when: a harness scores the same agents two ways (final-answer string match vs trace/effect alignment) on live_read/stateful tasks, re-run over time; reports ranking instability (Kendall's τ) and false-fail rate.

### E4.5 — RQ3 trace-property failure model
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-02T10:32:43Z
- deps: E2.7
- source: research_plan RQ3
- done-when: fit pass/fail ~ (depth, branching, state_coupling, cross_server, dynamism) per model; report feature importances.

### E4.6 — RQ4 scorer-vs-human + 200-task validation subset
- status: blocked
- note: harness merged in #25; awaiting human annotation pass per e4.6 protocol
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-02T10:44:43Z
- deps: E1.1
- source: research_plan RQ4 / simple_approach §5.6
- done-when: a 200-task subset + annotation protocol; report Tier-1/Tier-2 agreement with human consensus (Cohen's κ / Krippendorff's α ≥ 0.7); false-pass/false-fail; replay determinism <5%.

### E4.7 — ≥5-model leaderboard
- status: todo
- owner: —
- claimed_at: —
- deps: E1.1 E3.1
- source: README Phase 3 / simple_approach §9
- done-when: leaderboard covers ≥5 models (a GPT-class, Gemini, Claude Sonnet/Opus, an open-weight 70B+, a tool-specialized model) in replay, 3× per task; report regenerated.

### E4.8 — Architecture comparison (flat / RAG-MCP / hierarchical)
- status: todo
- owner: —
- claimed_at: —
- deps: E4.7
- source: simple_approach §12 / research_landscape
- done-when: the same benchmark is run against a flat agent, a RAG-MCP retrieval agent, and a hierarchical router+specialist agent; report compares them.

---

## E5 — Paper & release

### E5.1 — Paper scaffold (§1–§7 skeleton)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-02T10:56:50Z
- deps: E4.4
- source: research_plan Phase 5 (paper outline)
- done-when: `paper/` holds a NeurIPS/EMNLP-style skeleton with the section plan, the AGB-contrast paragraph, and figure/table placeholders (Fig: pipeline; example trace→checkpoints; answer-match vs trace-align; perf by dynamism/depth; decay curve; comparison table; capability profile; scorer-vs-human).

### E5.2 — Auto-generated figures & tables
- status: todo
- owner: —
- claimed_at: —
- deps: E5.1 E2.7 E4.3
- source: research_plan Phase 5
- done-when: a script regenerates the paper's figures/tables from eval/report artifacts (substrate table, degradation curves, leaderboard, decay curve, ablation).

### E5.3 — HuggingFace dataset release + datasheet
- status: todo
- owner: —
- claimed_at: —
- deps: E4.7
- source: research_plan Phase 5
- done-when: a `dmcp release` packages specs + reference traces into a HF-loadable layout (tracked `datasets/` path, not the git-ignored working dirs) with a datasheet; a living-leaderboard description.

---

## CC — Cross-cutting (ongoing)

### CC.1 — Grow the test suite
- status: done
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

## Idea backlog (un-sequenced; promote to steps only with human sign-off)

- Adversarial spec filters (naturalness / leakage / trivial-task) on the distiller output.
- Empirical calibration of error-taxonomy weights via pairwise human severity (Bradley-Terry).
- Semantic-cache (Tier-2) threshold sweep vs human-judged equivalence.
- LLM dynamism reclassification when the heuristic disagrees with observed drift (vet.py).
- Mine the full discovery scan for more no-creds public-API servers (Bucket B).
- Continual/live re-evaluation to track model-quality drift over time.
- Cross-server credentialed scenarios once E3.4 lands.
