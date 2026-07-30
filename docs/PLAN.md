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
- status: done
- note: DONE 2026-06-02 — 136 servers (120 crawled no-creds + 16 substrate) in manifests/servers.json; portable (npx/uvx, no hardcoded paths); crawled set gated at 100%-all-tools-pass; on a branch, NO merge until user approves
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-01T17:20:19Z
- deps: E0.1
- source: research_plan Phase 1 / user 2026-06-01 (100+ target)
- done-when: the crawler ingests the full registry and (with parallel, timeout-bounded install + smoke-vet) produces a curated manifest of **≥100 vetted servers** (target several hundred) spanning static / live_read / stateful_write and many domains; deduped; each tagged + sandboxed where stateful; a funnel report (registry size → installable → vetted) is emitted.

### E3.2 — Scale-out hardening of crawl/install/vet
- status: done
- owner: —
- claimed_at: —
- deps: E3.1
- source: README Phase 1
- done-when: install/vet run concurrently with per-server timeouts and failure isolation; oci/docker packages supported where feasible; resumable crawl (checkpoint discovered/vetted JSONL); throughput documented.

### E3.3 — Wire the docker-compose stack as a manifest
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-02T13:28:56Z
- deps: E3.1
- source: docker-compose-mcp.yaml
- done-when: a `manifests/compose.json` targets the compose-launched servers (postgres/mongo/neo4j/qdrant/redis/...); documented `docker compose up`; smoke-vet passes for reachable ones; adds stateful_write breadth.

### E3.4 — Credentialed manifest tier (Bucket A)
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-02T15:03:38Z
- deps: E3.1
- source: docs/credentials_bucket_a.md / README Phase 1
- done-when: servers needing keys are env-plumbed from `.env` (never committed); a `manifests/credentialed.json` is gated on present keys; missing keys skip gracefully.

### E3.5 — Substrate coverage report
- status: done
- owner: —
- claimed_at: —
- deps: E3.1
- source: research_plan §3 (substrate table)
- done-when: `report.py` (or a script) emits the paper's substrate table: server count, by dynamism, by domain, tool counts, mining funnel.

### E3.6 — Portable launch + dependency-aware 100% verification gate
- status: done
- owner: galyukshev
- claimed_at: 2026-06-02
- deps: E3.1
- source: user 2026-06-02 (no hardcoded paths; all tools must work; tool-dependencies)
- done-when: manifests launch via npx/uvx (no machine paths); `dmcp verify --require-all` keeps a server only if EVERY exercised non-destructive tool passes; verification is dependency-aware (resolves a tool's prerequisite by reusing an id harvested from a producer tool) with one error-fed arg-retry; discovered producer→consumer edges are recorded in the catalog.

### E3.7 — Canonical merged manifest + catalog + subset selector
- status: done
- owner: galyukshev
- claimed_at: 2026-06-02
- deps: E3.6
- source: user 2026-06-02 (merge all; experiments on subsets and full set)
- done-when: `manifests/servers.json` merges crawled + substrate (deduped), tagged domain/dyn/pkg/size/deps/alt; `manifests/catalog.json` holds package coords + tools + dependencies + pass_rate; `dmcp subset` filters by those axes; prebuilt subsets under `manifests/subsets/`; experiment guide in `docs/EXPERIMENTS.md`.

### E3.8 — DirectAlt seed (SAE / P_alt primitive)
- status: done
- owner: galyukshev
- claimed_at: 2026-06-02
- deps: E3.7
- source: simple_approach §5.3 (DirectAlt, κ≥0.7)
- done-when: `manifests/direct_alt.json` seeds same-name cross-server tool groups (`reviewed:false`) that feed the `same_name` sampling strategy + the P_alt grid; flagged for human review.

### E3.9 — Full goals + TaskSpecs corpus over the 100+ set
- status: claimed
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-02T15:19:07Z
- deps: E3.7 E6.1
- source: user 2026-06-02 (diverse generation / "полные данные"); research_plan Phase 2
- done-when: a STRATEGY-DIVERSE, stratified corpus over the full `servers.json` (docker stack up) — per generation-strategy (E6) × difficulty bin, intra ∪ inter-server, binned by MEASURED `trace_depth` — toward the power-analysis scale (≥150 tasks/cell, ~750–1000 total; simple_approach §6.3); resumable + detached; emits `data/specs_full.jsonl` + a coverage report (per strategy / depth-bin / dynamism / intra-vs-inter / server-tier).

---

## E6 — Strategy-diverse task generation (forward; headline)

Tasks must be composed by tool RELATIONSHIP, not at random. Reuse the eval-side sampler
(`dmcp/sampling.py:sample_distractors`) to also pick the SEED tool-set for forward
exploration; the explorer still explores live and the distiller distills from the real
trace — the trace-native invariant holds (graph/direct stay RQ2 baselines).

### E6.1 — Strategy-driven goal seeding
- status: done
- owner: Ilya-Galyukshev@roman-desktop
- claimed_at: 2026-06-02
- deps: E2.1 E3.7
- source: user 2026-06-02 (diverse generation setups); simple_approach §5.2
- done-when: `dmcp goal-gen --strategy {random,hard_neg,cross_domain,same_name,sibling,cross_server_alt,complementary,stratified}` picks the seed tool-set via `sample_distractors(strategy,[anchor],catalog)` (+ `direct_alt.json` for alternatives); the LLM writes a human goal exercising exactly that set; goals carry the strategy + intra/inter-server tag; forward-explore+distill yield traces with the intended structure.

### E6.2 — Corner-case generation strategies
- status: done
- owner: —
- claimed_at: —
- deps: E6.1
- source: user 2026-06-02 (corner cases); PDF §1.4 edges / §5.2 error taxonomy
- done-when: `long_similar_chain` (N≥4 pairwise-similar tools → max SAE+depth), `decoy`/`shortcut_trap` (E6), `prerequisite_strict` (E1/E5), `recovery_required`, `destructive_adjacent` (minefield), `ambiguous_intent` (path-agnostic), `homonym_trap` (same name/different semantics) are implemented and produce the targeted structure.

### E6.3 — Difficulty controls + depth stratification + coverage
- status: done
- owner: —
- claimed_at: —
- deps: E6.1
- source: research_plan Phase 3 (stratification); simple_approach §7.5
- done-when: a `--complexity {simple,medium,hard}` knob (required-tool count × chain length × cross-server count) shapes seeds; the corpus is binned by MEASURED `trace_depth`; a coverage report tabulates tasks per strategy / depth-bin / dynamism / intra-vs-inter / server-tier.

### E6.4 — DirectAlt curation + complementary-I/O edge mining
- status: done
- owner: —
- claimed_at: —
- deps: E3.8 E4.1
- source: simple_approach §5.3 (DirectAlt κ≥0.7); PDF §1.4 (complementary edge)
- done-when: `direct_alt.json` same-name groups are reviewed/scored (target κ≥0.7) and used for `cross_server_alt` seeding; complementary (output→input) edges are mined by reusing `baselines/graph_sampling` typed-overlap and used for `complementary` seeding.

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
- status: blocked
- note: paid OpenRouter run; supersedes by E8.8 against E8.6/E8.7 shared corpus — needs human budget approval
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T10:29:18Z
- deps: E1.1 E3.1
- source: README Phase 3 / simple_approach §9
- done-when: leaderboard covers ≥5 models (a GPT-class, Gemini, Claude Sonnet/Opus, an open-weight 70B+, a tool-specialized model) in replay, 3× per task; report regenerated.

### E4.8 — Architecture comparison (flat / RAG-MCP / hierarchical)
- status: done
- note: flat / RAG / hier compared in docs/experiments/e9.1-tool-exposure-matrix.md (flat on minimax-m3 only, context window)
- owner: —
- claimed_at: —
- deps: E4.7
- source: simple_approach §12 / research_landscape
- done-when: the same benchmark is run against a flat agent, a RAG-MCP retrieval agent, and a hierarchical router+specialist agent; report compares them.

---

### E4.9 — Generation-strategy ablation + gen×eval SAE heatmap
- status: todo
- note: code merged PR#44 gen-strategy ablation + gen-x-eval SAE matrix, smoke-tested, awaiting E3.9 corpus run
- owner: —
- claimed_at: —
- deps: E3.9 E2.8
- source: user 2026-06-02 (all ablations); simple_approach §8
- done-when: per generation-strategy, report SAE / pass^k / `trace_depth` of the produced tasks; plus a 2-D generation-strategy × eval-distractor-strategy SAE heatmap (which gen × eval setup maximises server confusion) — a headline figure.

### E4.10 — Difficulty curve (simple → long-similar-chain)
- status: todo
- note: code merged PR#44 difficulty curve, smoke-tested, awaiting E3.9 corpus run
- owner: —
- claimed_at: —
- deps: E3.9 E6.3
- source: user 2026-06-02 (simple → max-complex); research_plan RQ3
- done-when: agent accuracy / SAE / pass^k plotted vs difficulty bin (simple/medium/hard incl. long-similar-chain), per model; shows the expected monotone degradation.

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
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-02T11:15:35Z
- deps: E5.1 E2.7 E4.3
- source: research_plan Phase 5
- done-when: a script regenerates the paper's figures/tables from eval/report artifacts (substrate table, degradation curves, leaderboard, decay curve, ablation).

### E5.3 — HuggingFace dataset release + datasheet
- status: todo
- note: release script merged PR#47 release_hf.py, dry-run smoke-tested, awaiting corpus to package and push
- owner: —
- claimed_at: —
- deps: E4.7
- source: research_plan Phase 5
- done-when: a `dmcp release` packages specs + reference traces into a HF-loadable layout (tracked `datasets/` path, not the git-ignored working dirs) with a datasheet; a living-leaderboard description.

---

## E7 — Reusable framework (test an agent on YOUR MCP servers)

The whole pipeline must run on ANY user manifest — the repo IS the product: point it at your
MCP servers → diverse benchmark → multi-model agent eval + baselines → ablations → report.

### E7.1 — `dmcp bench` end-to-end orchestrator
- status: done
- owner: —
- claimed_at: —
- deps: E6.1 E4.7
- source: user 2026-06-02 (framework for own MCP servers)
- done-when: `dmcp bench --manifest <any> --models … --strategies …` runs generate (E6) → multi-model agent eval + graph/direct baselines → ablations/curves → a single report on an arbitrary manifest; documented in `docs/EXPERIMENTS.md`; reuses every existing command (no orphan module).

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
- status: done
- owner: —
- claimed_at: —
- deps: E0.1
- source: governance
- done-when: a GitHub Actions workflow runs the gate on PRs (only when the team opts in — currently the local gate is the guard).

### CC.3 — Ruff-format baseline + strict format gate
- status: done
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

---

## E8 — EMNLP experiment suite (full run)

Detailed plan: **`docs/EXPERIMENTS_SUITE.md`** (models, conditions, metrics, success criteria,
optional arms). Mandate (user 2026-06): run as many experiments as possible; decide the
publication cut later. Roster (pinned): gpt-5.5, claude-opus-4.8, claude-sonnet-4.6,
gemini-3.1-pro-preview, qwen3.7-max, kimi-k2.6, glm-4.7, minimax-m3. Authoring uses a
cross-family panel (explorer ≠ distiller), not a single model.

### E8.0b — Free-models provider + recalibration
- status: done
- owner: —
- claimed_at: —
- deps: E8.0a
- source: user 2026-06-04 (free API key for 6 models; run experiments free, layer paid OR on top)
- done-when: `dmcp/providers.py` auto-routes free-pool ids (deepseek-v4-pro, kimi-k2p6, kimi-k2p5, glm-5p1, gpt-oss-120b, minimax-m2p7) to `FREE_MODELS_BASE_URL` + `FREE_MODELS_API_KEY`; everything else stays on OpenRouter; family slugs cover the bare-name ids so cross-family pairings keep biting; `dmcp/pricing.py` pins these at $0 so the calibration extrapolation reads them as free; a free-only calibration run (N=10 specs × 6 free models) executes at $0 and the report at `docs/experiments/e8.0b-free-models-calibration.md` documents the final combined pool (free-first + targeted paid).

### E8.0c — Resumable runs + paper-pricing aliases
- status: done
- owner: —
- claimed_at: —
- deps: E8.0b
- source: user 2026-06-08 (more keys coming; experiments must be resumable; paper still needs OR-equivalent prices)
- done-when: `dmcp/resume.py` exposes `seen_task_ids` / `seen_goal_ids` / `file_row_count`; `dmcp eval --resume` skips finished task_ids in the output file; `dmcp generate --resume` skips finished goal_ids via `provenance.goal_id` (auto-stamped by the distiller); `scripts/cost_calibration.py` and `scripts/build_corpus.py` accept `--resume` and skip cells whose output is already complete; `dmcp/paper_pricing.py` maps every free model to its OpenRouter equivalent so paper cost can be recomputed from captured token counts; tests pin the resume contract end-to-end.

### E8.0a — Model pool calibration: live-price extrapolation
- status: done
- owner: —
- claimed_at: —
- deps: E8.1
- source: user 2026-06-04 (redact frontier-heavy roster; pick value-tier panel by measured $/spec)
- done-when: `scripts/cost_calibration.py` fetches live OpenRouter prices and runs N=10 specs per model in a 10-model pool spanning {mid-frontier, large-cheap, tool-specialist, small-fast, open-value}, capturing summary.cost; per-model markdown + JSON extrapolates to {E8.8 600-spec leaderboard, E8.7 1100-spec corpus} × pass^k ∈ {1, 3, 5}; report committed at `docs/experiments/e8.0a-model-calibration.md` with the Pareto-frontier recommended subset.

### E8.1 — Build: cost/latency capture (B1)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T10:30:08Z
- deps: E0.1
- source: docs/EXPERIMENTS_SUITE.md B1 / user 2026-06 (cost/latency Pareto)
- done-when: OpenRouter token usage + wall-clock thread through `dmcp/llm.py` into `EvaluationResult.summary.cost`; `scripts/cost_latency.py` emits the accuracy-vs-$ Pareto + $/correct; smoke-tested.

### E8.2 — Build: architecture harnesses (flat / RAG-MCP / hierarchical) (B2)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T10:42:36Z
- deps: E0.1
- source: docs/EXPERIMENTS_SUITE.md B2 / G6.3 / simple_approach §12
- done-when: `dmcp eval --architecture {flat,rag,hier}`: flat (current), RAG-MCP (embed prompt → retrieve top-k tools via `embeddings.py`, expose only those), hierarchical (router LLM → server-group → specialist); smoke-tested on a small manifest.

### E8.3 — Build: tool-scaling runner (B3)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T10:56:10Z
- deps: E0.1
- source: docs/EXPERIMENTS_SUITE.md B3 / G6.2
- done-when: `scripts/tool_scaling.py` sweeps `--pool-size {4,8,16,32,full}` → accuracy/SAE vs surface size; smoke-tested.

### E8.4 — Build: decay multi-window runner (B4)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T11:59:14Z
- deps: E1.5
- source: docs/EXPERIMENTS_SUITE.md B4 / G6.4
- done-when: `scripts/decay_run.py` wraps `dmcp refresh` over N time windows → per-server decay curve + `fig:decay_curve` numbers; smoke-tested.

### E8.5 — Build: IAE metric surfacing (B5)
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T12:04:07Z
- deps: E2.3
- source: docs/EXPERIMENTS_SUITE.md B5 / rev.1 PDF §5.1 (IAE)
- done-when: incomplete-aggregation (E3) surfaced as an explicit IAE rate in the SAE summary; smoke-tested.

### E8.6 — Generation upgrade: cross-family panel + role split + validation
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-04T12:10:12Z
- deps: E6.1
- source: docs/EXPERIMENTS_SUITE.md §2.2 / user 2026-06 (single-model authoring is a risk)
- done-when: corpus authored with explorer-family ≠ distiller-family, sharded over 3 explorer families (gpt-5.5/opus-4.8/gemini-3.1-pro), distilled by a top cross-family model, validated by a 4th family (qwen3.7-max); family provenance recorded per spec for G0.

### E8.7 — Run: shared corpus (~1100 specs, sharded) [supersedes E3.9]
- status: done
- owner: jrzkaminski@Jerzys-M4-Pro.local
- claimed_at: 2026-06-08T00:17:30Z
- deps: E8.6 E3.7
- source: docs/EXPERIMENTS_SUITE.md §2.4
- done-when: ~1100 keepers over servers.json (docker up), 15 strategies weighted to SAE-relevant, × 3 complexity, intra ∪ inter, ≥150 SAE-eligible + ≥150/complexity-bin, family-sharded, 200-task RQ4 subset reserved; coverage report emitted.

### E8.8 — Run: 8-model leaderboard + pools + reliability
- status: done
- owner: —
- claimed_at: —
- deps: E8.7 E8.1
- source: docs/EXPERIMENTS_SUITE.md G2
- done-when: 8 models × 600 core × pass^3 at MAIN; gold/full ceiling/floor on a subset; pass^5 reliability (pass^k_no_SAE vs overall) on the SAE-rich subset; `e4.7_numbers.json` written.

### E8.9 — Run: SAE deep-dive (P_alt curves + sampling ablation + heatmap)
- status: done
- note: e8.9-sae-deep-dive.md: P_alt curves + Wilson, 6-strategy ablation with Holm, gen-by-eval heatmap, SAE/IAE; e8.9_numbers.json committed
- owner: Keysiks@MacBook-Air-Kiriill.local
- claimed_at: 2026-07-27T14:26:22Z
- deps: E8.7
- source: docs/EXPERIMENTS_SUITE.md G3 / simple_approach §8
- done-when: P_alt degradation curves (3 ref models) with Wilson CIs; 6-strategy sampling ablation with Fisher/χ²+Holm (H1–H3); gen×eval SAE heatmap; SAE_expected/random/conditional + IAE; numbers JSONs written.

### E8.10 — Run: RQ1/RQ2/RQ3 + difficulty + generator-contamination (post-hoc)
- status: done
- note: RQ1 e4.4, RQ2 e4.3, RQ3 e4.5, contamination + same-family logit e8.10a, corrected leaderboard e8.10d; numbers JSONs committed
- owner: —
- claimed_at: —
- deps: E8.8
- source: docs/EXPERIMENTS_SUITE.md G0/G1/G4.1/G5
- done-when: RQ1 answer-vs-trace (τ, false-pass/fail); RQ2 forward-vs-graph-vs-direct; RQ3 failure model; difficulty curve; G0 contamination matrix + same-family logit; all numbers JSONs written.

### E8.11 — Run: industry extras (cost/latency, tool-scaling, architecture, decay)
- status: claimed
- note: released: auto-claimed by scripts/claim.py (which takes no step id) while targeting E9.10; work not started, owner line stale
- owner: Keysiks@MacBook-Air-Kiriill.local
- claimed_at: 2026-07-30T08:15:04Z
- deps: E8.8 E8.2 E8.3 E8.4
- source: docs/EXPERIMENTS_SUITE.md G6
- done-when: cost/latency Pareto + $/correct; tool-scaling curve; flat/RAG/hier architecture comparison; living-bench decay over ≥3 windows; numbers JSONs written.

### E8.12 — Run: RQ4 human validation (200 tasks, ≥3 raters)
- status: done
- note: e4.6-rq4-scorer-vs-human.md: 200-task subset, >=3 raters, Cohen kappa + Krippendorff alpha, per-tier false pass/fail, replay flip; e4.6_numbers.json committed
- owner: —
- claimed_at: —
- deps: E8.7
- source: docs/EXPERIMENTS_SUITE.md G4.3 / research_plan RQ4 (annotators confirmed)
- done-when: 200-task stratified subset annotated by ≥3 raters; Cohen κ (Tier-1/Tier-2) + Krippendorff α reported (target ≥0.7), per-tier false-pass/fail, replay flip <5%; optional Bradley-Terry error-weight calibration; `e4.6_numbers.json` written.

### E8.13 — Paper population + HF release
- status: todo
- owner: —
- claimed_at: —
- deps: E8.8 E8.9 E8.10 E8.11 E8.12
- source: docs/EXPERIMENTS_SUITE.md G7 / E7.2 / E5.3
- done-when: all `docs/experiments/*_numbers.json` committed; `paper/regenerate.py` fills every figure/table; HF dataset pushed with datasheet; living leaderboard described.

---

## E9 — Camera-ready (EMNLP 2026 Industry Track)

Everything promised to the four reviewers in the rebuttal. The authoritative
item-by-item ledger, including the exact reviewer wording each item answers, is
`docs/CAMERA_READY.md`; the ids in each `source:` line are its section numbers. A
step is done when its `docs/CAMERA_READY.md` checkbox can honestly be ticked.

### E9.1 — Paper text: narrow the over-claims
- status: done
- note: CR 1.1-1.7 all landed (PRs #183, #184, #185)
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 1.1 1.2 1.3 1.4 1.5 1.6 1.7
- done-when: Principle 1 restated as a measured invariant (no "cannot arise by construction") in §1, §3.1, §3.3 and the Conclusion; the Tier-2 naming collision resolved by renaming one mechanism and stating that no reported number involves an LLM judgment (scoring, not construction); the replay path-freedom trade-off stated; the tool-exposure scope boundary stated; GLM-5.1 carries the same-family caveat; decay reframed as a materiality demonstration with both caveats visible; the three missing limitations added.

### E9.2 — Appendix: generation funnel, human confusion matrix, open-universe table
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 2.2 2.3 2.6
- done-when: funnel (980 → 1,014 → 959 → 710) with the non-comparable-denominators caveat; the 2×2 over 975 cards (488/26/230/231, 73.7%, 94.9%) framed as the stated lower bound; the `e8.11` open-universe table promoted with its one-model/one-attempt caveat. All three regenerate from committed numbers JSONs.

### E9.3 — Main body: leave-own-family-out leaderboard + decay per domain
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 2.4 2.5
- done-when: both tables in the **main body** (not the appendix): LOFO leaderboard with Spearman 0.997, the three adjacent swaps and GLM-5.1 50.3% → 46.4%; decay per domain with per-row call counts (yfinance 18, arXiv 105, Wikipedia 3, pooled 126) so the pooled rate is checkable against the rows.

### E9.4 — Distiller-fidelity audit: protocol, write-up, item-level release
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 2.1 4.2
- done-when: the audit protocol (annotator independence, blinding to the distiller's retain/drop decision, adjudication of disagreements, written rubric) documented from the collaborator who ran it; appendix reports protocol, raw counts, Wilson intervals, the length stratification and the one failure case; item-level labels + rubric released. **Gate:** without the protocol this is an unblinded self-audit reporting three 100% rows — the weakest link in the package. Do not write it up until the protocol is in hand; `blocked` is the correct status if it does not arrive.

### E9.5 — Restore the six-strategy distractor ablation
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 2.7 / E8.9 (deferred there to the post-acceptance appendix)
- done-when: the ablation lost when `paper/` was reset to the submitted sources is restored from PR #143 in git history, re-checked against current numbers, and cited from the distractor discussion.

### E9.6 — Run: tool-exposure matrix over the open universe
- status: done
- note: matrix over 4 models x rag-k{4,8,16,32}+hier, flat on minimax-m3 only (context window); pass^3 at rag:8; report e9.1 + numbers committed
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 3.1 / docs/experiments/e9.1-tool-exposure-matrix.md
- done-when: `rag-k` ∈ {4,8,16,32}, `hier`, and `flat` where the context window allows, over ≥4 models on the committed 150-task depth-balanced subset (`manifests/subsets/cr150.ids.txt`), plus pass^3 at `rag:8`; every cell matched task-for-task against the released curated verdicts; cells that cannot run reported as not-runnable with the reason; `docs/experiments/e9.1-tool-exposure-matrix.md` filled with data + result + conclusion and `e9.1_numbers.json` committed.

### E9.7 — Run: Tier-2 override rates per category across judge families
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 3.2
- done-when: saved leaderboard Tier-1 failures replayed through the judge across several judge families at temperature 0, joined against the specs so every record carries its category; override rates reported overall and for each of the 15 categories. `dmcp/baselines/rq4_agreement.py::_tier1_verdict` drops `tier==2` rows and therefore mis-derives Tier-1 — fixed or bypassed, with the choice stated in the report.

### E9.8 — Run: widen the refresh beyond 22 traces / 3 families
- status: todo
- owner: —
- claimed_at: —
- deps: E9.11 E9.12
- source: docs/CAMERA_READY.md 3.3
- done-when: reference traces re-executed across substantially more of the 121 servers; per-domain decay recomputed on the wider sample; `broken` still reported as an upper bound with the retry policy stated.

### E9.9 — Annotate a second model for scorer strictness
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 3.4
- done-when: at least one model beyond the original is human-annotated and the result reported as whether the scorer's conservatism shifts the level rather than the ordering. Annotation work, not compute — the most expensive item on the list.

### E9.10 — Fix the broken task and tighten the reference validator
- status: done
- note: reference validator widened to every required checkpoint + enforced in dmcp generate; report docs/experiments/e9.10-reference-validation-gate.md; PR #182
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 4.1
- done-when: the one identified broken task fixed; the validator rejects a claimed-successful exploration that does not produce every required external effect; a regression test covers the rejection.

### E9.11 — Refresh preflight (quarantine, don't blame the agent)
- status: todo
- owner: —
- claimed_at: —
- deps: —
- source: docs/CAMERA_READY.md 4.3
- done-when: required files, tables, credentials and writable resources confirmed before a refreshed task is readmitted; a task failing preflight is quarantined rather than counted as agent failure; covered by tests.

### E9.12 — Finer refresh classifier
- status: todo
- owner: —
- claimed_at: —
- deps: E9.11
- source: docs/CAMERA_READY.md 4.4
- done-when: transient errors (timeouts, connection errors, 429, recoverable 5xx) retried with backoff across windows; schema drift classified only when discovery shows a changed or removed tool on a reachable server; decay stated when the schema is intact but a required record is gone; everything else quarantined; covered by tests.

### E9.13 — Pre-submission verification sweep
- status: todo
- owner: —
- claimed_at: —
- deps: E9.1 E9.2 E9.3
- source: docs/CAMERA_READY.md 5.1 5.2 5.3
- done-when: Reproducibility Statement checked against the HF release — the evaluation records are present at `leaderboard_e8.10d/verdicts/evals_*.jsonl`, so the statement is cited by path rather than softened; a committed script regenerates the three Gwet AC1 figures alongside the existing Fleiss kappa; the 16% / 15.5% equivalence-set figures reconciled to one labelled framing (15.5% is the corpus figure, 16% the 750-slice figure).
