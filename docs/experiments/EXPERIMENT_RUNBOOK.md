# DynamicMCPBench — Experiment Runbook & Economics

Single source of truth: every **run config** (generation), every **eval config**
(scoring), the full **experiment suite**, **human annotation**, and the **cost/time
economics** (per model, measured). Pin the candidate set + condition here so every
contributor runs the same and the leaderboards **merge**.

---

## 0. Two separate phases — do not conflate

| Phase | Script | Produces | Run by |
|---|---|---|---|
| **A · GENERATION** | `scripts/build_corpus.py` | the corpus (`specs.jsonl` + `traces.jsonl`) | each person → own corpus |
| **B · EVALUATION** | `scripts/run_leaderboard.py` → `dmcp eval` | leaderboard scores | each person on own corpus → merge |

- **Phase A** sub-steps: goal-gen → explore → distill → **validate** (4th-family spec QC, advisory) → coverage.
- **Phase B** runs AFTER a corpus exists: candidates **replay** against `traces.jsonl` and are scored by trace-align.
- ⚠️ The **"validator" in Phase A is spec quality-control, NOT candidate scoring.** Eval is always a *separate* script/phase after generation — that's why it "looks different".

---

## 1. GENERATION configs (Phase A — per person)

Common flags: `--manifest manifests/servers.json --surfaces manifests/surfaces.json`
`--complexities simple,medium,hard --per-strategy 8 --budget 12 --explore-timeout 600 --resume`
(all 15 strategies by default). **Constraint:** on OpenRouter, `goalgen` + `distiller`
must be **OpenAI/Anthropic/Google** (forced named `tool_choice`); explorers + validator = any family.

| person | goalgen | explorers (panel → shards) | distiller-candidates | validator | script |
|---|---|---|---|---|---|
| **P1** *(done — 290 valid)* | gpt-5.4-mini · haiku-4.5 · gemini-3.5-flash | gpt-5.5 · sonnet-4.6 · gemini-3.1-pro · qwen3.7-max · grok-4.3 · deepseek-v4-pro | gpt-5.5 · sonnet-4.6 | minimax-m3 | `run_corpus_paid_sota.sh` |
| **top-up** *(done — +10)* | same as P1 | same as P1 (no opus) | gpt-5.5 · sonnet-4.6 | minimax-m3 | `run_corpus_topup.sh` |
| **P4** | gemini-2.5-flash | deepseek-v4-pro · minimax-m3 · mistral-large-2512 · grok-4.3 | gpt-5.4-mini · haiku-4.5 | glm-5.1 | `run_corpus_p4.sh` |
| **P5** | haiku-4.5 | glm-5.1 · kimi-k2.6 · nova-pro · minimax-m3 | gemini-3.5-flash · gpt-5.4-mini | deepseek-v4-pro | `run_corpus_p5.sh` |
| **P6** | gpt-5.4-mini | qwen3.7-max · grok-4.3 · nova-pro · mistral-large-2512 | haiku-4.5 · gemini-2.5-flash | minimax-m3 | `run_corpus_p6.sh` |

4 distinct families per spec (goalgen ≠ explorer ≠ distiller ≠ validator). Merge: `specs.jsonl` (validator-valid) + `traces.jsonl` across people.

---

## 2. EVALUATION run-configs (Phase B)

### 2a · `run_leaderboard.py` — orchestrator
Expands `models × pools × p_alts × desc_levels` into **cells**; each cell = one `dmcp eval`. Parallelises **per provider key** (1 key ⇒ sequential).

| arg | default | meaning |
|---|---|---|
| `--specs` | required | corpus to evaluate on |
| `--reference-traces` | — | enables deterministic **replay** (no live MCP) |
| `--manifest` | servers.json | tool universe |
| `--models` | required | comma candidate IDs (who is ranked) |
| `--pools` | gold,target,full | distractor-pool sweep |
| `--p-alts` | 0,0.5,1.0 | P_alt grid (target pool) → degradation curve |
| `--pool-size` | 8 | # distractors in target |
| `--desc-levels` | raw | description normalization sweep (raw,a,b) |
| `--repeat` | 5 | **pass^k** |
| `--budget` | 12 | max agent turns |
| `--concurrency` | 1 | # parallel cells, **each on its own key** (`OPENROUTER_API_KEY[_2,_3…]`) |
| `--key-offset` | 0 | skip first N keys (disjoint slices) |
| `--resume` | off | skip done cells |
| `--out` / `--json` | reports/leaderboard | per-cell JSONL + `leaderboard.md` / numbers JSON for the paper renderer |

### 2b · `dmcp eval` — per-cell scorer (what each cell runs)
`--model` · `--replay --reference-traces` · `--pool gold|target|full --p-alt --pool-size`
· `--desc-level raw|a|b` · `--repeat K` · `--budget` · **`--judge --tier2-threshold --judge-model`** (Tier-2 effect-equivalence judge, **OFF by default**) · `--simulate-misses` (Tier-3 LLM tool sim, OFF) · `--architecture flat|rag|hier --rag-k` · `--candidate-traces[-out]` · `--resume` · `-o`.

### 2c · Candidate set — **PIN THIS** (9 models, lean, ≤$15 out)
```
--models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6,minimax/minimax-m3,qwen/qwen3.7-max,x-ai/grok-4.3,openai/gpt-5.4-mini,google/gemini-3.1-pro-preview,anthropic/claude-haiku-4.5
```
Anchors with the colleague's run (for merge): **deepseek-v4-pro · glm-5.1 · kimi-k2.6 · minimax-m3**.
**Fairness:** when scoring candidate X, drop specs whose family was explorer/distiller (self-preference).

### 2d · Conditions
- **HEADLINE:** `--pools target --p-alts 0.5 --pool-size 8 --desc-levels raw --repeat 3 --budget 12 --replay` (no judge).
- **ABLATION grid:** `--pools gold,target,full --p-alts 0,0.25,0.5,0.75,1.0 --desc-levels raw,a,b` (+ architecture + judge-robustness as separate runs).

---

## 3. EVALUATION / scoring configs (what is measured)

**Two scoring philosophies**
- **trace/effect-align** (HEADLINE): scores ACTIONS via effect-checkpoints (`equivalence_set` of acceptable `{server,tool}` + `arg_predicate` + `ordering` + `minefields`). Path-agnostic; never scores the answer string.
  - **Tier-1** deterministic (no LLM). **Tier-2** = LLM judge (`emit_equivalence_judgment`) rescues failed checkpoints achieved via an unlisted tool; conservative (default NO); OFF by default.
- **answer-match** (`baselines/answer_match.py`): token-Jaccard ≥0.5 on the final message. **RQ1 baseline only** — forbidden in headline scoring — used to show its false-fail/ranking-instability.

**Metrics** (on trace-align): `pass^k` · `pass^k_no_SAE` · **SAE** (right tool type, wrong server; subtypes `expected`=related server / `random`=unrelated; `conditional_rate` = SAE / right-type calls) · **error-taxonomy E1–E7** weighted (E1 missing_prereq 1.0 · E2 wrong_branch 0.8 · E3 incomplete_aggregation 0.6 · **E4 server_confusion=SAE 1.0** · E5 order_violation 0.4 · E6 tool_blindness 1.0 · E7 arg_hallucination 0.7) · **IAE** (incomplete value-production).

**Condition axes (= ablation knobs):** pool (gold/target/full) · P_alt (0→1) · desc (raw/A/B) · architecture (flat/rag/hier) · Tier-3 sim · judge on/off.

---

## 4. The experiment suite (→ runner → output → status)

| # | experiment | runner / command | output (paper) | status |
|---|---|---|---|---|
| 1 | **Leaderboard** (headline) | `run_leaderboard.py` headline cond | Table 1 (pass^k, SAE) | ready |
| 2 | **SAE deep-dive** | `run_leaderboard.py` full grid + `dmcp/curves.py` | P_alt curves, gold/target/full, desc A/B, **gen×eval SAE heatmap** | ready |
| 3 | **RQ1** answer vs trace | `dmcp rq1-compare` | false-fail/false-pass, ranking instability | ready |
| 4 | **RQ2** forward vs graph vs direct | `dmcp compare-generators` | generation-quality table | ready |
| 5 | **RQ3** failure model | `dmcp rq3-failure-model` | which trace props predict failure | ready |
| 6 | **RQ4** scorer vs human | `dmcp rq4-subset` → annotate → `dmcp rq4-agreement` | **κ / α** (needs humans) | needs raters |
| 7 | **Difficulty curve** | `scripts/difficulty_curve.py` | pass-rate vs depth/complexity | ready |
| 8 | **Strategy ablation** | `scripts/strategy_ablation.py` | which gen-strategy is hardest | ready |
| 9 | **Architecture** | `dmcp eval --architecture flat,rag,hier` | flat vs RAG-MCP vs hier | ready |
| 10 | **Industry: cost/latency** | `scripts/cost_latency.py` | $/task, latency by model | ready |
| 11 | **Industry: tool-scaling** | `scripts/tool_scaling.py` | pass-rate vs pool-size | ready |
| 12 | **Industry: decay** | `scripts/decay_run.py` | drift over time | ready |
| 13 | **judge-robustness** | rerun headline with `--judge` | ranks stable w/ vs w/o judge | ready |
| 14 | **HF release** | `scripts/release_hf.py` | dataset + datasheet | ready |

Build is 100% done — these are all **runs** on the existing harnesses.

---

## 5. RQ4 — Human annotation (the only non-compute experiment)

- `dmcp rq4-subset` builds the **200-task validation subset** (candidate trajectories + the scorer verdict, blinded).
- **≥3 human raters** independently label each trajectory pass/fail.
- `dmcp rq4-agreement` computes:
  - **H1 (primary):** Cohen's **κ** between Tier-1 (deterministic) verdict and human consensus (target ≥ pre-registered).
  - **H2:** Krippendorff's **α** over {human raters + Tier-1 + Tier-2 as symmetric raters}.
- Validates that the trace-align scorer agrees with humans. **Action item: recruit ≥3 raters; ~200 trajectories each (~2–3 h/rater).**

---

## 6. Economics & time (per model — MEASURED on the probe)

**Probe:** 9 models × 10 specs, pass^1, target/p0.5/raw, replay, on 1 OpenRouter key (sequential).
Back-calculated token volume from deepseek's measured spend: **~61k input + ~12k output tokens per spec** (~7 turns; pool + growing replay history).

| model | $/spec | cost / 10 specs | time / 10 specs |
|---|---|---|---|
| deepseek-v4-pro | **0.037 ✓meas** | **$0.37 ✓** | **~13 min ✓** |
| minimax-m3 | 0.033 | ~$0.33 | — |
| kimi-k2.6 | 0.082 | ~$0.82 | — |
| glm-5.1 | 0.097 | ~$0.97 | **~4.5 min ✓** |
| gpt-5.4-mini | 0.100 | ~$1.00 | — |
| grok-4.3 | 0.106 | ~$1.06 | — |
| haiku-4.5 | 0.121 | ~$1.21 | — |
| qwen3.7-max | 0.121 | ~$1.21 | — |
| gemini-3.1-pro | 0.266 | ~$2.66 | slowest |
| **ALL 9** | **~$0.96/spec** | **~$9.6 / 10 specs** | ~1–2 h sequential (1 key) |

(gemini-3.1-pro = 28% of cost; deepseek/minimax cheapest. Time is highly model-dependent.)

### Cost per experiment (on **our 300** valid; all-9 = ~$0.96/spec)
| experiment | cells × specs × passᵏ | cost |
|---|---|---|
| Leaderboard (headline, pass^3) | 1 × 300 × 3 | **~$865** |
| P_alt curve (+4 p_alts, pass^1) | 4 × 300 × 1 | ~$1,150 |
| Pool (gold+full, pass^1) | 2 × 300 × 1 | ~$575 |
| desc A/B (pass^1) | 2 × 300 × 1 | ~$575 |
| Architecture (rag+hier, pass^1) | 2 × 300 × 1 | ~$575 |
| RQ1/RQ3/difficulty/strategy | post-hoc on outputs | ~$0 |
| cost/latency · tool-scaling · decay | reuse/light | ~$200 |
| **full eval suite (300, brute grid)** | | **≈ $3.9k** |

### ⚠️ Scope to fit budget — ablations on a SUBSET
Ablations don't need all 9 models or the full corpus. Run **headline = all 9 × full corpus × pass^3**, but **ablations (P_alt/pool/desc/arch) = 3–4 representative models × ~150 specs × pass^1** → cuts ablation cost ~5×.
**Scoped suite ≈ $865 (headline) + ~$500 (ablations subset) ≈ ~$1.4k on our 300.**

### Two blockers
1. **Budget:** key at **$531 / $700 (headroom ~$169)** → raise to **~$2k** (our share). On the merged ~2000 corpus it scales ~6.7× → split across contributors (each runs their own corpus).
2. **Parallelism:** runner pins one key per cell → **1 key = sequential = days**. Fix: create **4–6 OpenRouter sub-keys** (`OPENROUTER_API_KEY_2…6`) → `--concurrency 6` → ÷6 wall-clock; or patch the runner for within-key concurrency.

---

## Canonical commands

**Headline leaderboard** (swap `--specs`/`--reference-traces`/`--out` per person; keep the rest IDENTICAL):
```bash
uv run python scripts/run_leaderboard.py \
  --specs data/<corpus>/specs_valid.jsonl --reference-traces data/<corpus>/traces.jsonl \
  --manifest manifests/servers.json \
  --models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6,minimax/minimax-m3,qwen/qwen3.7-max,x-ai/grok-4.3,openai/gpt-5.4-mini,google/gemini-3.1-pro-preview,anthropic/claude-haiku-4.5 \
  --pools target --p-alts 0.5 --pool-size 8 --desc-levels raw --repeat 3 --budget 12 \
  --concurrency <#keys> --resume --out reports/lb_<name> --json docs/experiments/lb_<name>.json
```
**Full ablation grid** (same, scoped to a subset corpus + 3–4 models):
```bash
  --pools gold,target,full --p-alts 0,0.25,0.5,0.75,1.0 --desc-levels raw,a,b --repeat 1
```
