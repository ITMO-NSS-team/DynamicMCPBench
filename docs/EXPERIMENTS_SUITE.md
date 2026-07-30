# DynamicMCPBench — Full Experiment Suite (EMNLP 2026 Industry)

> **Status:** execution plan. All harness code is built + smoke-tested + merged (E6, E4.7,
> E4.9, E4.10, E7.1, E7.2, E5.3 + `--desc-levels`); Phase 0 below adds the four extras. The
> short run-recipe lives in [`EXPERIMENTS.md` §9](EXPERIMENTS.md); **this file is the
> detailed, maximal version** — every condition, model, metric, success criterion, and the
> optional arms.
>
> **Operating mandate (user, 2026-06):** run *as many experiments as possible* now and decide
> the publication cut later; do not be constrained by the current paper draft. Quality over
> "the easy way". Maximal breadth, every variant we discussed, optionals marked **`[OPT]`**.

---

## 0. Design principles

1. **One shared corpus.** Generate ~1000–1200 diverse TaskSpecs once; *every* experiment
   draws from it. No per-experiment regeneration.
2. **Fractional design, not full-cross.** A naïve cross of pool × P_alt × desc × sampling ×
   models × pass^k is 10⁵–10⁶ runs. Instead: one **MAIN condition** anchors the leaderboard;
   each ablation **sweeps a single axis** holding the rest at MAIN, on a fixed **reference
   subset** + **reference models**.
3. **Replay for comparability.** Candidate models run against the same cached world
   (`--replay --reference-traces`) so differences are the model, not server flakiness. Live
   mode is reserved for decay (G6.4) and architecture (G6.3).
4. **Reuse runs.** RQ1, RQ3, gen-strategy ablation, difficulty curve, cost/latency, and the
   generator-contamination check are **post-hoc analyses of the same leaderboard runs** —
   near-zero extra spend.
5. **Pre-registration.** Each RQ has a decision rule fixed *before* the full run (§7).
6. **Reproducibility.** Pinned model snapshots (no floating `-latest`), pinned embedding
   model, fixed seeds, released specs + reference traces.

**The anchor — MAIN condition:** `pool=target, P_alt=0.5, pool-size=8, desc=raw, --replay,
budget=12, repeat=3`.

**Reference models** (single-axis sweeps, to control cost): `deepseek-v4-pro` (free, top acc),
`kimi-k2p6` (free, top tool-use specialist), `qwen/qwen3-coder-plus` (paid, Qwen family). Span the space at ≈$0.

**Reference subset:** a 350-task stratified slice balanced across gen-strategy × complexity ×
dynamism × intra/inter. **Leaderboard core:** 600 balanced tasks. **Full ~1100** used for
generation-side analyses + the 200-task human subset.

---

## 1. Models

### 1.1 Candidate roster — calibrated free/cheap pool (per E8.0a/b; supersedes the original frontier-8)

> **Updated 2026-06-04+ (team sync):** the user redacted the frontier-heavy panel toward
> cheap/free models and obtained a **private free-tier endpoint** (6 agentic models).
> `scripts/cost_calibration.py` (E8.0a/b) measured real `$/spec`; the **source of truth for the
> pool is now `docs/experiments/e8.0a-model-calibration.md` + `e8.0b-free-models-calibration.md`.**

**Headline pool for E8.7/E8.8 — 6 models, ~$55 for the 1100-spec corpus (vs ~$309 pure-paid):**

| # | Model | Tier | Family | Why kept |
|---|---|---|---|---|
| 1 | `deepseek-v4-pro` | **free** | deepseek | top acc at $0; matches paid sonnet-4.6 |
| 2 | `glm-5p1` | **free** | z-ai | tied-top at $0; BFCL family |
| 3 | `kimi-k2p6` | **free** | moonshot | tool specialist; matches paid kimi-k2.6 |
| 4 | `minimax-m2p7` | **free** | minimax | cross-family diversity |
| 5 | `qwen/qwen3-coder-plus` | paid (~$19) | qwen | adds Qwen family; tool specialist |
| 6 | `anthropic/claude-haiku-4.5` | paid (~$36) | anthropic | adds Anthropic family for cross-family pairs |
| 7 `[OPT]` | `anthropic/claude-sonnet-4.6` | paid (~$143) | anthropic | frontier ceiling anchor; drop if budget tight |

Free models route via `dmcp/providers.py` to the private endpoint (3 keys round-robin);
everything else stays on OpenRouter. Free-endpoint wall-clock is slow (p95 110–162 s) → run
with `--concurrency 3` (~3 h per 1100-spec model over 3 lanes). `[OPT]` diversity probes:
`gpt-oss-120b` (free, `openai-oss` family, 40% acc), `kimi-k2p5`.

> The original frontier-8 (gpt-5.5, opus-4.8, sonnet-4.6, gemini-3.1-pro, qwen3.7-max,
> kimi-k2.6, glm-4.7, minimax-m3) remains available as **paid-ceiling / optional arms** (§1.2).

### 1.2 Optional candidate add-ons **`[OPT]`**

| Model ID | Angle |
|---|---|
| `google/gemini-3.1-pro-preview-customtools` | tool-tuned twin of #4 → does tool-tuning resist SAE? (G3.7) |
| `qwen/qwen3-coder-plus` | BFCL coding-tool leader |
| `deepseek/deepseek-v4-pro` | "best general reasoning + tool-use" (per 2026 surveys) |
| `x-ai/grok-4.3` / `x-ai/grok-4.20-multi-agent` | the multi-agent variant is purpose-built for orchestration |
| thinking/reasoning variants (e.g. `qwen3.7-max` vs a thinking sibling) | reasoning-effort vs SAE ablation (G2.3) |

### 1.3 Generation models (the authoring panel — implemented in E8.6, `dmcp/families.py`)

`build_corpus.py` round-robin shards goals across `--explore-model` (a comma panel) and, per
shard, picks the first cross-family distiller from `--distiller-candidates` (`cross_family_pick`
guarantees explorer-family ≠ distiller-family); `--validator` adds a 4th-family check. Per-spec
provenance (explorer/distiller family, shard, goal_id) is recorded for G0. Calibrated free-pool panel:

| Stage | Model(s) |
|---|---|
| explore (sharded) | `kimi-k2p6` (moonshot) · `deepseek-v4-pro` (deepseek) · `glm-5p1` (z-ai) |
| distill (cross-family per shard) | `--distiller-candidates deepseek-v4-pro,kimi-k2p6,minimax-m2p7` (picker takes first non-explorer-family) |
| cross-family validation | `qwen/qwen3-coder-plus` (qwen — a 4th family) |

---

## 2. Generation — the shared corpus

### 2.1 The 4-stage forward pipeline (trace-native, headline-invariant)

`goal-gen` (LLM proposes a realistic human goal from a seed tool-set) → `explore` (an explorer
agent chains live tools until a successful trajectory is recorded → **Trace**) → `distill`
(LLM compiles the trace into a **TaskSpec**: effect checkpoints + `equivalence_set` +
minefields + causal ordering) → (eval scores candidates on **effects**, path-agnostic).

### 2.2 Why we do NOT author with a single model (and the fix)

Single-model authoring (today's default `claude-haiku-4.5` for all three stages) has three
defects: **monoculture** (one model's blind spots shape every task), **self-preference
contamination** (if the author family is also a candidate, that family is unfairly advantaged),
and **weak-author → weak-spec** (cheap models write poor checkpoints/minefields; spec quality
underpins the whole benchmark and RQ4 validity). It is *partly* mitigated because scoring is
effect-based + path-agnostic (the candidate need not match the explorer's path), but the *set*
of required effects and the difficulty still come from the author.

**The fix (mostly already supported — `generate` has separate `--explore-model`/`--distill-model`):**

- **Strong authors**, distiller = top tier (spec correctness is paramount; single-shot → cheap to use the best).
- **Cross-family role split** — explorer family ≠ distiller family (the "generator ≠ filter" principle).
- **Generator panel via sharding** — ⅓ of the corpus explored by each of 3 families → a *cross-family* corpus, not a monoculture, and it yields the family slices that power the contamination check (G0). No code change: shard + merge.
- **Cross-family validation** — a 4th-family model (`qwen3.7-max`) auto-checks each spec (solvability, checkpoint correctness, genuine minefield) before it enters the corpus — an automated RQ4 proxy.

### 2.3 The 15 generation strategies (each tags `strategy:<s>` + intra/cross-server + complexity)

| group | strategies | probes |
|---|---|---|
| base (6) | random, hard_neg, cross_domain, same_name, sibling, stratified | diversity, near-miss, **SAE primitive**, intra-chains |
| corner (7) | long_similar_chain, homonym_trap, decoy, prerequisite_strict, recovery_required, destructive_adjacent, ambiguous_intent | max SAE+depth, E1/E5, minefields, equivalence stress |
| special (2) | cross_server_alt (from `direct_alt.json`), complementary (output→input edges) | true cross-server equivalents, genuine data-dependency chains |

### 2.4 Corpus shape & power

- **~1100 keepers**, weighted toward SAE-relevant strategies (`same_name`, `homonym_trap`,
  `cross_server_alt`, `long_similar_chain` ≈ 2× share), × 3 complexity bins (simple 1–2 /
  medium 3–4 / hard 5+), intra ∪ inter-server, binned by **measured** `trace_depth`.
- Guarantees ≥150 SAE-eligible tasks (the §6.3 power floor: 150/cell for a 15 pp SAE
  difference at α=0.05, power=0.80) and ≥150 per complexity bin.
- Family-sharded for G0; 200-task stratified subset reserved for RQ4 human validation.

```bash
# detached, resumable, docker up; explore sharded over 3 families
scripts/build_corpus.py -m manifests/servers.json \
    --complexities simple,medium,hard --per-strategy 24 \
    --explore-model <shard> --distill-model <cross-family> --out data/corpus
# (run 3 shards with different --explore-model, merge; or use the panel wrapper from B6)
```

### 2.5 Generation-side experiments

| ID | Question | Setup | Compare / criterion |
|---|---|---|---|
| **GEN.1** coverage | Does the corpus cover the design space? | post-hoc `corpus_coverage.py` | every strategy × depth-bin × dynamism × intra/inter populated; ≥150/SAE-cell |
| **GEN.2** `[OPT]` explorer-strength | Does a stronger explorer yield harder/deeper tasks? | generate matched slices with explore∈{kimi, gpt-5.5, qwen3.7} | mean trace_depth, |eq_set|, downstream pass-rate |
| **GEN.3** `[OPT]` distiller-quality | Does distiller choice change spec quality? | distill the same traces with 2 families | |eq_set|, checkpoint count, RQ4 human-agreement per distiller |
| **GEN.4** `[OPT]` persona ablation | Do personas raise goal diversity? | goal-gen with/without `--no-personas` | `diversity_score` (1 − mean pairwise Jaccard) |

---

## 3. Experiment catalogue

Legend: **swept** = the axis varied; everything else held at MAIN. Costs at ~$0.06–0.10/run.

### G0 — Generator-contamination / robustness *(NEW, the answer to "one model?")*

| ID | Question | Setup | Compare / criterion | Cost |
|---|---|---|---|---|
| **G0.1** | Does candidate pass-rate correlate with shared generator-family? | post-hoc on the family-sharded corpus × the 8-model leaderboard | 8×3 (candidate-family × generator-family) pass-rate matrix; logit `pass ~ same_family + controls`; **criterion: \|β_same_family\| small / n.s. → "generator-robust"** | $0 |
| **G0.2** `[OPT]` | Cross-family validation yield | fraction of specs each family-validator rejects | rejection rate by author-family; inter-validator κ | small |

### G1 — Generation comparison (RQ2: forward vs graph vs direct)

| ID | Setup | Compare / criterion | Cost |
|---|---|---|---|
| **G1.1** | `baseline-graph` (motifs chain+hub, size 3) + `baseline-direct` on the substrate → `compare-generators` | mean/max **\|eq_set\|** (forward >1.05 vs 1.00/1.00 pre-registered), coverage, executable-on-first-try, unnecessary-tool→0, ordering density, error-type diversity, filter pass rate | ~$120 gen + offline |
| **G1.2** `[OPT]` | graph motif sweep (chain vs hub vs mixed) | does motif change generated difficulty? | ~$60 |

### G2 — Leaderboard / capability profile (the engine)

| ID | Swept | Setup | Compare / criterion | Cost |
|---|---|---|---|---|
| **G2.1 main** | model | 8 models × 600 core × pass^3, MAIN (target P_alt=0.5) | per-model accuracy + Wilson CI; ranking with non-overlapping CIs on top-3 | ~10.8k runs |
| **G2.2 pool ceiling/floor** | pool | 8 models × 300-subset × {gold, full} × pass^1 | gold (upper bound, frontier >90%) vs full (lower bound) | ~4.8k runs |
| **G2.3 reliability** | — | pass^5 on a 200-task SAE-rich subset × 3 ref models | **pass^k_no_SAE vs pass^k_overall** (SAE's share of instability) | ~3k runs |
| **G2.4 stratified profile** | — | post-hoc on G2.1 | accuracy by dynamism × complexity-bin × recovery × intra/inter | $0 |
| **G2.5** `[OPT]` budget | tool-call budget | 2 ref × 300 × budget∈{4,8,12,20} | accuracy vs budget — does more headroom help? | ~2.4k |
| **G2.6** `[OPT]` thinking-mode | reasoning on/off | 2 models (thinking vs non-thinking sibling) × 300 | reasoning's effect on SAE + accuracy | ~1.2k |
| **G2.7** `[OPT]` customtools | tool-tuned variant | gemini-3.1-pro vs `-customtools` × 300 | does tool-tuning cut SAE? | ~0.6k |

### G3 — SAE deep-dive *(the industry hook)*

| ID | Swept | Setup | Compare / criterion | Cost |
|---|---|---|---|---|
| **G3.1 P_alt curves** | P_alt {0,.25,.5,.75,1} | 3 ref × 350 subset, `dmcp curve` | accuracy↓ & **SAE_expected↑** monotone; Wilson CIs; complexity-faceted | ~5.3k |
| **G3.2 sampling ablation** | 6 strategies | 2 ref × 350, `dmcp ablate` (random/hard_neg/cross_domain/same_name/sibling/stratified) | **H1** hard_neg−random ≥15 pp (p<.01 Holm); **H2** cross_domain < within-domain SAE_expected; **H3** `SAE ~ cos_sim + same_name` → same_name β>0 independent; sibling vs cross_server (intra vs inter); stratified linearity | ~4.2k |
| **G3.3 gen×eval heatmap** | — | post-hoc (`strategy_ablation.py`) | which gen-strategy × eval-condition maxes SAE (headline figure) | $0 |
| **G3.4 SAE decomposition** | — | post-hoc | SAE_expected vs SAE_random vs conditional rate; **expected/random ratio** = does the model grasp service families | $0 |
| **G3.5 IAE companion** | — | post-hoc (B5) | incomplete-aggregation (E3) rate on completeness tasks, alongside SAE | $0 |
| **G3.6** `[OPT]` per-domain SAE | domain | post-hoc | which domains confuse most (github↔gitlab, jira↔linear, slack↔telegram) | $0 |
| **G3.7** `[OPT]` mixed-effects | — | post-hoc | `correct ~ strategy + P_alt + level + (1|task) + (1|model)` — the full statistical model | $0 |

### G4 — Scoring validity (RQ1 + RQ4)

| ID | Setup | Compare / criterion | Cost |
|---|---|---|---|
| **G4.1 RQ1 answer-vs-trace** | post-hoc re-score leaderboard traces both ways | **Kendall τ** between rankings (pre-reg: <0.5), false-pass vs false-fail, over-time stability | ~$0 + small judge |
| **G4.2 RQ1 live drift** `[OPT]` | re-run a 100-task live_read slice at T+Δ | answer-match drift rate over real time (the "today's Madrid" demo) | ~$50 |
| **G4.3 RQ4 scorer-vs-human** | 200-task subset, **≥3 annotators** (confirmed available) | Cohen κ (Tier-1, Tier-2) ≥0.7, Krippendorff α ≥0.7, per-tier false-pass/fail, **replay flip <5%** | human + ~$30 |
| **G4.4 Tier-2 threshold** `[OPT]` | sweep `--tier2-threshold` {0.6,.75,.9,1.0} on 200 subset | judge sensitivity; agreement vs human at each | ~$0.6k |
| **G4.5 judge-family bias** `[OPT]` | Tier-2 judge with 2 different families | does the judge family bias verdicts? | ~$0.4k |
| **G4.6 error-weight calibration** `[OPT]` | fold pairwise severity judgments into the annotation pass | **Bradley-Terry** empirical E1–E7 weights vs the expert priors | human |

### G5 — Failure model (RQ3) + difficulty

| ID | Setup | Compare / criterion | Cost |
|---|---|---|---|
| **G5.1 RQ3 failure model** | post-hoc logit on leaderboard | `pass/fail ~ depth + runtime_branching + state_coupling + cross_server + dynamism + recovery`, per-model + pooled; odds ratios + drop-loglik importance; **pre-reg:** ≥1 feature \|β\|>0.5 & drop-loglik>0.5 & top in ≥2/3 models | $0 |
| **G5.2 difficulty curve** | post-hoc | pass / SAE / pass^k vs depth bin (simple → long-similar-chain); monotone degradation | $0 |
| **G5.3 error taxonomy** `[OPT]` | post-hoc | E1–E7 frequency × model — which models fail which way | $0 |

### G6 — Industry extras *(your 4 picks)*

| ID | Setup | Compare / criterion | Cost | Build |
|---|---|---|---|---|
| **G6.1 cost/latency Pareto** | post-hoc on leaderboard (tokens+timing captured) | accuracy vs $/1k-tasks vs wall-clock; **$ per correct task**; Pareto frontier | $0 | B1 |
| **G6.2 tool-scaling curve** | 2 ref × 250 × pool-size {4,8,16,32,full} | accuracy/SAE vs surface size — the "how many MCP servers before degradation" onset | ~2.5k | B3 |
| **G6.3 architecture comparison** | flat / RAG-MCP / hierarchical × 3 ref × 250 | which architecture best resists SAE & scales; `[OPT]` RAG retrieval-k sweep; `[OPT]` router-quality | ~2.3k | B2 |
| **G6.4 living-bench decay** | refresh ~300 reference traces × 3 time windows | per-server identical/drift/broken; decay slope; spec half-life | ~$30 | B4 |

### G7 — Substrate / dataset

| ID | Setup | Output |
|---|---|---|
| **G7.1 substrate table** | from `servers.json` + crawl funnel | server count by dynamism / domain / tool-count; registry→installable→vetted funnel |
| **G7.2 server-tier** `[OPT]` | post-hoc | compose/docker vs no-docker; stateful_write vs live_read vs static difficulty |
| **G7.3 HF release** | `release_hf.py --push` | specs + reference traces + labels + datasheet; living leaderboard |

---

## 4. Phase 0 — build the missing harnesses (build → smoke → PR → merge)

| ID | Build | Entails |
|---|---|---|
| **B1** cost/latency capture | thread OpenRouter `usage` (tokens) + wall-clock through `dmcp/llm.py` → `EvaluationResult.summary.cost = {tokens, usd, wall_ms, n_calls}`; `scripts/cost_latency.py` → Pareto + `$/correct` |
| **B2** architecture harnesses | `--architecture {flat,rag,hier}` on eval: **flat** (exists) / **RAG-MCP** (embed prompt → retrieve top-k tools via `embeddings.py`, expose only those) / **hierarchical** (router LLM → server-group → specialist agent). Heaviest item. |
| **B3** tool-scaling runner | `scripts/tool_scaling.py` sweeps `--pool-size` → accuracy/SAE vs surface size (reuses pool machinery) |
| **B4** decay multi-window | `scripts/decay_run.py` wraps `dmcp refresh` over N windows → decay curve + `fig:decay_curve` |
| **B5** IAE metric | surface E3 incomplete-aggregation as an explicit IAE rate in the SAE summary |
| **B6** `[OPT]` panel wrapper | optional convenience: one command that shards `build_corpus` over N explore-model families + merges (otherwise run 3 shards by hand) |

---

## 5. Budget — calibrated (E8.0a/b), free-pool

The bulk now routes through the free endpoint; paid spend is reserved for the cross-family
Anthropic/Qwen anchors and the optional ceiling.

| Run | Pool | ~$ |
|---|---|---|
| E8.7 corpus (1100 × pass^3) | 4 free + 2 paid | **~$55** |
| + optional sonnet-4.6 anchor | +1 paid | ~$198 |
| pure-paid frontier (reference) | E8.0a recommendation | ~$309 |

≈5.6× cheaper than the original ~$3.3k frontier plan; sweeps (G3/G6) run free-first likewise.
Source of truth: `docs/experiments/e8.0a/b`.

> **Caveat (review, fix pending):** the calibration auto-Pareto picker has a $0-cluster bug —
> models with zero/unknown price ride the frontier — so the pool above was set by **manual
> override**, not the raw picker. Fix = drop `unknown_price`/zero-usage models + tie-break on accuracy.

---

## 6. Sequencing & dependencies

```
Phase 0 (B1–B5, parallel)  ─┐
OpenRouter pre-flight       ─┤→  Phase 1 corpus (sharded, detached ~½ day)
                             │      └→ smoke every command on the corpus
                             ▼
        Phase 2: leaderboard G2.1–G2.4 (the long pole)
                             │
   ┌─────────────────────────┼───────────────────────────┐
   ▼                         ▼                            ▼
 G3 SAE sweeps          G6 extras (B1–B4)          G1 RQ2 gen baselines
 (P_alt, sampling)      (tool-scale, arch, decay)
   └─────────────────────────┼───────────────────────────┘
                             ▼
  post-hoc: G0, G2.4, G3.3–3.5, G4.1, G5.1–5.2, G6.1   (reuse runs, ~$0)
                             ▼
  RQ4 human pass (200 tasks, ≥3 raters)  →  G4.3 / G4.6
                             ▼
  paper population (regenerate.py → docs/experiments/*_numbers.json)  →  HF release G7.3
```

Critical path: corpus → leaderboard → post-hoc. SAE/extras/baselines run in parallel after the
leaderboard. RQ4 annotation runs concurrently from the moment the corpus exists.

---

## 7. Pre-registration (decision rules fixed before the full run)

- **RQ1:** positive iff Kendall τ(answer-match, trace-align rankings) **< 0.5** AND false-pass **>** false-fail.
- **RQ2:** positive iff forward mean **\|eq_set\| > 1.05** AND both baselines = 1.00.
- **RQ3:** positive iff ≥1 trace-property has **\|β\| > 0.5** in the pooled fit AND its drop-loglik loss **> 0.5** AND it is top driver in **≥2/3** per-model fits.
- **RQ4:** positive iff **κ_tier1 ≥ 0.70** AND **κ_tier2 ≥ 0.70** AND **replay flip < 5%**.
- **SAE ablation (H1):** hard_neg − random SAE **≥ 15 pp** at **p<0.01** (Fisher/χ² + Holm).
- **G0 (contamination):** benchmark is "generator-robust" iff `same_family` coefficient is **n.s.** (or \|β\| below a pre-set small threshold) controlling for difficulty.

---

## 8. Open items & risks

1. **`gemini-3.1-pro-preview` is a preview tag** → snapshot into the replay cache early; pin the fallback.
2. **Stateful_write servers** are sandboxed; `refresh --refresh-stateful` is off by default (mutation risk) — decay (G6.4) measured on live_read + static, stateful noted separately.
3. **Architecture comparison (B2)** is the heaviest build and runs partly live (RAG retrieval + hierarchical routing) → its cost estimate is the softest.
4. **Cost numbers** assume ~15k in / 3k out per replay run; real token use is captured by B1 and the budget is reconciled after the leaderboard.
5. **Generator panel cost** — frontier explorers are pricier than haiku; the +$200 over a single-model corpus buys spec quality + the G0 robustness result + RQ4 validity. Non-negotiable for a credible paper.

---

*The calibrated free-pool roster (§1.1) and panel (§1.3) reflect the team's 2026-06-04 redaction
and the E8.0a/b calibration — those reports are the source of truth. Ledger steps for execution
live under epic **E8** in `docs/PLAN.md`. Known build issues from the E8.1–E8.6 review
(architecture-harness SAE confound, cost auto-picker $0-cluster, build_corpus cross-provider key
routing) are tracked separately, not yet fixed.*

---

## 9. Camera-ready additions (post-acceptance, EMNLP 2026 Industry)

The suite above defines the **submitted** experiments. The camera-ready adds one
new experimental group and two re-runs of existing machinery. Ledger:
`docs/CAMERA_READY.md`; steps: **E9.6–E9.9** in `docs/PLAN.md`. Design principles
from §0 apply unchanged — in particular, every cell is scored in deterministic
replay against the released reference traces, and pre-registration precedes the
run.

### G8 — Tool exposure over the open universe *(the answer to "you only tested a curated pool")*

Extends G6's architecture comparison from a curated pool to the **full 1,168-tool
catalog**. `e8.11` established the single point (`qwen3.7-max`, embedding top-8,
150 tasks, one attempt: 57.3% → 36.7%); G8 turns it into a surface.

- **Slice:** `manifests/subsets/cr150.ids.txt` — 150 tasks from the released
  750-task leaderboard slice, balanced 50/50/50 over reference-chain depth,
  `random.seed(0)`, rebuilt deterministically by `scripts/cr_subset.py`.
- **Axes:** `rag-k` ∈ {4, 8, 16, 32}; architectures `rag`, `hier`, `flat`;
  models `minimax-m3`, `kimi-k2.6`, `claude-haiku-4.5`, `qwen3.7-max`;
  attempts 1 for the sweep, 3 (pass^3) at `rag:8`.
- **Baseline:** matched task-for-task against the released curated verdicts
  (`leaderboard_e8.10d/verdicts/`), so no baseline compute is spent.
- **Known incompleteness (reported, not hidden):** the catalog serialises to
  ~292k tokens of tool schema, so the literal `flat` full-catalog condition
  exceeds the context window of `kimi-k2.6` (262,144), `glm-5.1` (204,800) and
  `claude-haiku-4.5` (200,000). Only the 1M-context models can be offered the
  whole catalog; the rest are reported as **not runnable**, with the reason.
- **Pre-registration + decision rules:** `docs/experiments/e9.1-tool-exposure-matrix.md`.

```bash
uv run python scripts/cr_subset.py --corpus hfdl --out manifests/subsets/cr150.jsonl \
    --ids-out manifests/subsets/cr150.ids.txt
uv run python scripts/run_cr_matrix.py \
    --models minimax/minimax-m3,moonshotai/kimi-k2.6,anthropic/claude-haiku-4.5,qwen/qwen3.7-max \
    --conditions rag:4,rag:8,rag:16,rag:32,hier --repeat 1 --lanes 1,2,3 --shards 9
uv run python scripts/cr_compare.py --evals 'evals/cr/*.jsonl' --corpus hfdl
```

`scripts/run_cr_matrix.py` shards each cell across the `OPENROUTER_API_KEY*`
lanes in `.env` and is resume-safe; runs are staged in waves with the per-task
cost remeasured after each wave. Wave boundaries are spend checkpoints, not
scientific ones — the analysis is over whatever cells complete.

### G9 — Tier-2 override rates per category *(E9.7)*

Re-runs the judge over the saved leaderboard Tier-1 failures across **several
judge families** at temperature 0, joined against the specs so every record
carries its category, and reports override rates overall and per each of the 15
categories. The existing judge-enabled records (`annotations/rq4/scorer/`) carry
no category field, which is why this is a re-run rather than a re-analysis.
`dmcp/baselines/rq4_agreement.py::_tier1_verdict` drops `tier==2` rows and
mis-derives Tier-1 — fix or bypass it before reusing, and state which.

### G10 — Widened refresh *(E9.8)*

Re-executes reference traces across substantially more of the 121 servers rather
than 22 traces over three families, and recomputes per-domain decay on the wider
sample. Depends on the refresh preflight (E9.11) and the finer classifier (E9.12)
landing first, so that infrastructure failures are quarantined instead of being
counted as decay.

**Done** — `scripts/decay_sweep.py`, report in
`docs/experiments/e9.8-wide-decay-sweep.md`. 246 specs over 100 sampled servers
produced 938 completed calls on 113 servers in 12 domains: 32.6% identical
(against 36% narrow), 67.0% drifted, 0.4% attributably broken, with a 25.8%
upper bound on breakage if every unresolved failure were persistent. Free —
live network calls only, no LLM.
