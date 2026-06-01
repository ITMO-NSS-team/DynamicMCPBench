# Concept, lineage, and the full experiment plan

The canonical "why" and "what" behind DynamicMCPBench, distilled from the team's
private planning documents so any contributor — human or Claude — has the full
context without those originals. `CLAUDE.md` holds operational rules; `docs/PLAN.md`
holds the ordered, claimable backlog; this file holds the reasoning **and the
complete catalogue of experiments, metrics, and baselines** the paper draws on.

---

## 1. The problem we measure

LLM agents increasingly run over **many MCP servers at once** (the paper targets
**100+ servers** — see §6 and PLAN E3). Two empirical facts motivate the project:

- **Tool selection breaks at scale.** Clients cap concurrent tools (Cursor ≈ 40,
  Copilot 128); public registries list ~15–16k servers. Agents must pick the right
  tool among many semantically overlapping ones.
- **Server attribution error (SAE).** When GitHub and GitLab both expose
  `search_issues`, an agent often calls the *right kind* of tool on the *wrong
  server*. No mainstream benchmark isolates SAE from plain wrong-tool error.

A second, deeper problem is **how you grade**. Most benchmarks compare a final
answer string or a ground-truth tool list. On live, stateful tools the right
answer changes between runs, and GT tool lists are ~50% noise (AGB's finding).
Answer-matching therefore mis-ranks agents on exactly the tools agents really use.

A third problem is **description quality**: ~97% of tool descriptions carry at
least one "smell"; the benchmark must control for this or it measures spec quality,
not agent capability (→ Level A/B normalization, §6).

## 2. Three revisions of the idea (only rev.3 is the headline)

- **rev.1 — graph-based** (`MCP_Benchmark_Generator_v1.pdf`): build a tool
  dependency graph, mine structural patterns (alternative cliques, dependency
  chains/stars, conditional/sequential edges), generate questions from patterns.
  Superseded as the *headline* because AGB owns the graph lane and ≥99% of servers
  lack `outputSchema`. **Its metrics and patterns are reused** (SAE, error taxonomy,
  complexity scoring — §6/§7).
- **rev.2 — sampling MVP** (`simple_approach.md`): drop the graph; sample
  distractors with six strategies and build accuracy-vs-density curves. Superseded
  as the headline, but **re-enters as the eval-side distractor sampler** that makes
  SAE and P_alt curves measurable (§6).
- **rev.3 — trace-native** (`research_plan`, current headline): explore live
  servers forward, record successful traces as ground truth, distill into
  path-agnostic effect checkpoints, grade on effect alignment (never the final
  answer). See §3.

The literature survey (`research_landscape.md`) informs methods: type-based sparse
graphs, back-instruct, the four-tier evaluation stack, StableToolBench-style
replay, BenchAgents' plan→generate→verify→evaluate decomposition, τ-bench pass^k.

## 3. rev.3 trace-native pipeline (headline)

`crawl → goal-gen → forward exploration → distill → eval (replay, Tier-1/2/3) →
report → refresh`. A trace distills into a **TaskSpec**: fuzzy prompt; `tool_effect`
checkpoints (with an `equivalence_set` + optional `ArgPredicate`) and
`value_produced` checkpoints; minefields (must-not effects → instant fail); a
partial ordering (only real dependencies); a complexity profile (depth,
cross-server, runtime-branching, state-coupling, recovery); a dynamism tag
(static / live_read / stateful_write).

## 4. The four orthogonality pillars (full rules: `memory/feedback_agb_orthogonality.md`)

1. **Trace, not graph** — the primitive is a recorded trajectory.
2. **Forward, not backward** — explore → distill, never subgraph → back-instruct.
3. **Effect, not answer** — grade reproduced effects, never a final-answer string.
4. **Live, not static cache** — live/stateful substrate; a refresh protocol
   measures decay instead of freezing the world.

Graph and sampling are built **only as labeled comparison baselines** (RQ2), never
as the headline.

## 5. Research questions (drive the paper)

- **RQ1 (headline):** Does answer-matching mis-rank agents on dynamic-data tasks,
  and does trace alignment fix it? *IV:* scoring method (answer-match vs
  trace-align) × dynamism level × re-run time. *DV:* score variance across re-runs,
  ranking agreement (Kendall's τ), false-fail rate. *H:* answer-match drifts &
  falsely fails on live data; trace-align is stable.
- **RQ2:** Does forward exploration produce more realistic / diverse / executable
  tasks than backward graph-sampling (AGB-style) or direct generation
  (MCPEval-style)? *DV:* executable-on-first-try rate, human realism, distinct valid
  paths/task, tool/server coverage, unnecessary-tool rate (ours → 0 by construction).
- **RQ3:** Which emergent trace properties predict agent failure? *Axes:* trace
  depth, runtime branching, state-coupling, recovery-required, dynamism level,
  single- vs cross-server. *Method:* fit pass/fail ~ properties per model; report
  feature importances.
- **RQ4:** How reliable is trace-based scoring vs human judgment? *Method:*
  200-task subset, ≥3 annotators; Tier-1/Tier-2 agreement (Cohen's κ /
  Krippendorff's α ≥ 0.7); false-pass/false-fail; replay determinism (<5% variance).

## 6. Experiments & methods catalogue (the complete set from all docs)

Everything below is in-scope for the paper. PLAN.md sequences each as steps.

### 6.1 Scale: the 100+ server substrate (paper-critical)
The headline scale claim. Crawl the official MCP Registry (+ PulseMCP / Smithery /
glama supplements), install (pypi/npm/oci), smoke-vet, dynamism-tag, dedup, and
curate **≥100 vetted servers** (target a few hundred), spanning static / live_read /
stateful_write and many domains. Report the mining funnel (registry size → vetted)
and a server/domain/dynamism breakdown table. Sandboxed + public-API + credentialed
(Bucket A) tiers. This is what differentiates the benchmark's realism.

### 6.2 Three evaluation modes (tool-pool conditions)
- **Gold** — only the required tools in the pool (upper bound; a frontier model
  should clear >90% or the task is malformed).
- **Target** — required tools + a controlled distractor set `D` with chosen
  `(P_alt, |D|)` (the main experimental condition).
- **Full** — the entire pool of all crawled servers (lower bound; realism).

### 6.3 Description normalization (controlled variable)
- **Level A (surface):** original descriptions (the wild, ~97% smelly).
- **Level B (semantic augmentation):** normalized to a rubric
  `[Purpose][Inputs][Outputs][Constraints][When to use vs alternatives]`.
Run A and B separately; the gap measures how much description quality masks
capability.

### 6.4 Distractor / tool-pool sampling — 6 strategies (eval-side)
Around a trace's required tools, build `D` by: **random** (baseline), **hard-neg**
(embedding cosine near-misses, denoised), **cross-domain similar**, **same-name
collisions** (+ near-collisions by edit distance), **sibling** (intra-server), and
**stratified** mix. Deterministic with a pinned embedding model + seed. Controls
semantic density (P_alt) without graph-based task generation.

### 6.5 Metrics
- **SAE rate** = right tool type (in the spec's `equivalence_set`), wrong server.
  Subtypes: **SAE_expected** (servers are direct alternatives) vs **SAE_random**
  (not), plus **SAE conditional rate** = SAE / (SAE + correct calls of that type).
- **Error taxonomy E1–E7 with weights:** E1 missing prerequisite (1.0), E2 wrong
  branch (0.8), E3 incomplete aggregation (0.6), E4 SAE/server confusion (1.0),
  E5 order violation (0.4), E6 tool blindness (1.0), E7 argument hallucination
  (0.7). Weights are expert priors (PDF also gives per-pattern weights); calibrate
  empirically later via pairwise human severity (Bradley-Terry).
- **Degradation curves:** for each (strategy, Level A/B), plot
  (P_alt ∈ {0,.25,.5,.75,1}) vs accuracy ± CI and SAE_rate ± CI. Expect accuracy ↓
  and SAE_expected ↑ as P_alt rises.
- **pass^k reliability** (K=5): fraction of K independent runs that fully pass; plus
  a **pass^k_no_SAE vs pass^k_overall** split to show how much SAE drives instability.
- **Complexity-bin normalization:** bin by required-tool count (1, 2, 3–4+);
  micro-average within bins, macro-average across — so models are compared fairly.

### 6.6 Ablation study (a first publishable result)
Five contrasts: (1) random vs hard-neg; (2) hard-neg vs cross-domain; (3) same-name
vs different-name-similar; (4) sibling vs cross-server (intra- vs inter-server
confusion); (5) stratified mix vs sum of components (interaction effects).
**Hypotheses:** H1 hard-neg ≫ random SAE (≥15 pp, p<0.01); H2 cross-domain <
within-domain SAE_expected; H3 same-name has an independent effect over semantic
similarity (`SAE ~ cos_sim + same_name`). **Stats:** paired χ²/Fisher per
strategy-pair per P_alt; mixed-effects logistic regression
`correct ~ strategy + P_alt + level + (1|task) + (1|model)`; Bonferroni/Holm
correction. **Power analysis:** ≥150 questions/cell for a 15 pp SAE difference at
α=0.05, power=0.80.

### 6.7 Generation baselines & quality gating (RQ2)
Compare three generators on the same substrate: **forward exploration** (ours),
**backward graph-sampling** (AGB-style baseline), **direct generation**
(MCPEval-style baseline). Distillation/quality gating mirrors the doc's three
adversarial filters — naturalness, leakage (no tool-name hints), and a trivial-task
check — plus the trace-native solvability re-execution. Three comparison axes:
filter pass rate, agent error rate, error-type diversity.

### 6.8 Models, architectures, and the living benchmark
- **Leaderboard:** ≥5 candidate models (a GPT-class, Gemini, Claude Sonnet/Opus, an
  open-weight 70B+, a tool-specialized model) in deterministic replay; 3× per task.
- **Architecture comparison (future arm):** flat agent vs RAG-MCP retrieval vs
  hierarchical router+specialist, all on the same benchmark.
- **Living benchmark:** the refresh protocol re-runs reference traces against live
  servers, classifies identical/drifted/broken/skipped, and reports decay over time.

### 6.9 Human validation & ground truth
200-task subset, ≥3 annotators: verify prompt solvability, checkpoint
correctness/completeness, genuine minefields, admitted alternative paths; report
Krippendorff's α (target >0.7). For SAE, maintain a published cross-server
"direct-alternative" set (the equivalence_set role), reviewed to Cohen's κ ≥ 0.7.

### 6.10 Cost & reproducibility
Budget per agent run ≈ 4–6 tool calls; pin model/embedding snapshots; deterministic
replay + seeds; release specs + reference traces (HuggingFace) and a Docker-compose
substrate. A GitHub PAT is required for credentialed/GitHub servers (rate limits).

## 7. Source documents

Distilled from: the graph-based technical description (rev.1 PDF), the sampling MVP
spec (rev.2, `simple_approach.md`), the 50+-paper field survey
(`research_landscape.md`), and the rev.3 trace-native research plan
(`research_plan`). Those originals are not in the repo; this file and `docs/PLAN.md`
are their in-repo successors. Keep them in sync when the direction changes (plan
changes require human sign-off — see `CLAUDE.md`).
