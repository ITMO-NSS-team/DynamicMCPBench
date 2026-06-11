# DynamicMCPBench — Evaluation & Experiment Runbook (for the paper)

The corpus is **already generated** (`data/<corpus>/specs_valid.jsonl` + `traces.jsonl`).
This doc is **every model-run and scoring-run that produces a paper result**: exact
script + arguments, **$ and time**, and a clear flag on **which runs need no LLM at all**
(post-hoc analyses on existing eval outputs). Human annotation is a separate section.

> One rule: **evaluation is a separate phase from generation.** Everything below is run
> *after* a corpus exists. Candidates **replay** against `traces.jsonl` and are scored by
> **trace/effect-align** (Tier-1 deterministic ± optional Tier-2 LLM judge) — never by
> answer-string matching (that's the RQ1 baseline only).

---

## 1. Pin — shared by every run

- **Corpus:** `--specs data/<corpus>/specs_valid.jsonl --reference-traces data/<corpus>/traces.jsonl --manifest manifests/servers.json`
- **Candidates (9):**
  `--models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6,minimax/minimax-m3,qwen/qwen3.7-max,x-ai/grok-4.3,openai/gpt-5.4-mini,google/gemini-3.1-pro-preview,anthropic/claude-haiku-4.5`
  Anchors with the colleague (for merge): **deepseek-v4-pro · glm-5.1 · kimi-k2.6 · minimax-m3**.
- **Base condition:** `--pool target --p-alt 0.5 --pool-size 8 --desc-level raw --budget 12 --replay`
- **Fairness:** when scoring candidate X, drop specs whose family was explorer/distiller.
- **Cost basis (measured, 10-spec probe, all-9):** **~$0.96 / spec** (deepseek $0.037 · minimax $0.033 · kimi $0.082 · glm $0.097 · gpt-5.4-mini $0.10 · grok $0.106 · haiku $0.121 · qwen $0.121 · gemini-3.1-pro $0.27). 1 key ⇒ sequential.

`<corpus>` = `corpus_merged` (our 300) now; each contributor swaps in their own; merge per-candidate JSONL.

---

## 2. LLM RUNS — model evaluations (these cost money)

`PINNED` = the pin block above. `out/json` per run.

| # | run | script + the distinguishing args | new cells | $ (our 300) | time 1 key / 6 keys |
|---|---|---|---|---|---|
| **R1** | **Leaderboard** (headline) | `run_leaderboard PINNED --pools target --p-alts 0.5 --desc-levels raw --repeat 3` | 9 | **~$865** | ~35h / ~6h |
| **R2** | **P_alt degradation curve** | `run_leaderboard PINNED --pools target --p-alts 0,0.25,0.5,0.75,1.0 --repeat 1` | 36 | ~$1,150 | ~45h / ~8h |
| **R3** | **Pool: gold/target/full** | `run_leaderboard PINNED --pools gold,target,full --p-alts 0.5 --repeat 1` | 18 | ~$575 | ~22h / ~4h |
| **R4** | **Desc raw/A/B** | `run_leaderboard PINNED --pools target --p-alts 0.5 --desc-levels raw,a,b --repeat 1` | 18 | ~$575 | ~22h / ~4h |
| **R5** | **Architecture flat/RAG/hier** | `dmcp eval PINNED --architecture rag` and `--architecture hier` (per model) | 18 | ~$575 | ~22h / ~4h |
| **R6** | **Judge-robustness** | rerun R1 cell `dmcp eval … --candidate-traces <R1 traces> --judge --judge-model openai/gpt-5.5` | 9 | ~$200 (judge only) | ~3h |
| **R7** | **Tool-scaling** | `scripts/tool_scaling.py PINNED --model <m> --pool-sizes 4,8,16,32 --p-alt 0.5` | 4×(1–3) | ~$300 | ~6h |
| **R8** | **Decay over time** | `scripts/decay_run.py PINNED --model <m> --windows 0,7,30 --refresh-stateful` | ~3×(1–3) | ~$300 | ~6h |

**Brute total on our 300 ≈ $4.5–5k.** R2–R5 share the target/p0.5/raw cell with R1.
**Scope to fit budget:** keep **R1 on all 9 × full 300 × pass^3**; run **R2–R5 on a 150-spec subset × 4 representative models × pass^1** → cuts those ~5× → **scoped suite ≈ $2.2k**. R6 can reuse R1's candidate traces (`--candidate-traces`) so only the judge LLM is paid.

### Exact commands
```bash
# R1 — headline leaderboard
uv run python scripts/run_leaderboard.py \
  --specs data/<corpus>/specs_valid.jsonl --reference-traces data/<corpus>/traces.jsonl \
  --manifest manifests/servers.json --models <9> \
  --pools target --p-alts 0.5 --pool-size 8 --desc-levels raw --repeat 3 --budget 12 \
  --concurrency <#keys> --resume --out reports/R1_lb_<name> --json docs/experiments/R1_<name>.json

# R2/R3/R4 — same runner, change the swept axis (and --repeat 1):
#   R2 P_alt:  --pools target --p-alts 0,0.25,0.5,0.75,1.0
#   R3 pool:   --pools gold,target,full --p-alts 0.5
#   R4 desc:   --pools target --p-alts 0.5 --desc-levels raw,a,b

# R5 — architecture (per model; flat is the default/base):
uv run dmcp eval data/<corpus>/specs_valid.jsonl -m manifests/servers.json \
  --model <m> --replay --reference-traces data/<corpus>/traces.jsonl \
  --pool target --p-alt 0.5 --pool-size 8 --budget 12 --architecture rag --rag-k 8 \
  -o reports/R5_arch_rag_<m>.jsonl        # repeat with --architecture hier

# R6 — judge robustness (reuse R1 candidate traces → pay only the judge):
uv run dmcp eval data/<corpus>/specs_valid.jsonl -m manifests/servers.json \
  --candidate-traces reports/R1_lb_<name>/cand_<m>.jsonl \
  --judge --tier2-threshold 0.5 --judge-model openai/gpt-5.5 -o reports/R6_judge_<m>.jsonl

# R7 — tool-scaling (pool-size sweep, per model):
uv run python scripts/tool_scaling.py --specs … --reference-traces … --manifest … \
  --model <m> --pool-sizes 4,8,16,32 --p-alt 0.5 --budget 12 --repeat 1 \
  --out reports/R7_scaling_<m> --report --json docs/experiments/R7_<m>.json

# R8 — decay (re-eval over time windows, per model):
uv run python scripts/decay_run.py --specs … --reference-traces … --manifest … \
  --windows 0,7,30 --wait-s … --refresh-stateful --snapshots-dir … \
  --report --json docs/experiments/R8_<m>.json
```

---

## 3. NO-LLM RUNS — post-hoc analyses (free, CPU, seconds–minutes)

These read the **eval JSONLs already produced by R1–R8** (and the corpus). **No model calls, ~$0.**

| # | analysis | command | input | LLM? |
|---|---|---|---|---|
| **A1** | RQ1 answer-match vs trace-align | `dmcp rq1-compare --evals reports/R1_*/eval_*.jsonl --specs … --reference-traces … --threshold 0.5` | R1 evals + candidate final messages | **no** |
| **A2** | RQ2 forward vs graph vs direct | `dmcp compare-generators --forward … --graph … --direct … --reference-traces … --catalog …` | the 3 generated corpora | **no** |
| **A3** | RQ3 failure model | `dmcp rq3-failure-model --evals reports/R1_*/eval_*.jsonl --specs … --ridge --json-out …` | R1 evals + spec features | **no** |
| **A4** | Difficulty curve (E4.10) | `scripts/difficulty_curve.py --evals … --specs … --out … --json …` | evals | **no** |
| **A5** | Gen-strategy ablation (E4.9) + SAE heatmap | `scripts/strategy_ablation.py --evals … --specs … --traces … --out … --json …` | evals + traces | **no** |
| **A6** | Cost/latency table | `scripts/cost_latency.py --evals … --out … --json …` | evals (latency captured during R*) | **no** |
| **A7** | Coverage report | `scripts/corpus_coverage.py --traces … --specs … --manifest … -o coverage.md` | corpus | **no** |
| **A8** | Figures + tables → paper | `dmcp paper-figures --root . [--fail-on-pending]` | all the `*_numbers.json` | **no** |
| **A9** | HuggingFace release | `scripts/release_hf.py --specs … --traces … --manifest … --direct-alt … --repo-id … --license … [--push]` | corpus | **no** |

P_alt curves, pool/desc comparison, SAE-by-strategy×eval heatmap, error-taxonomy and IAE breakdowns all fall out of A4/A5/A8 over the R1–R5 outputs — **no extra model calls.**

---

## 4. HUMAN ANNOTATION — RQ4 (separate; no compute, needs people)

1. `dmcp rq4-subset --candidate-traces reports/R1_*/cand_*.jsonl --rater <id> --n 200 --seed <S> --subset-out … --annotation-out …` → one **blinded** sheet per rater (no LLM).
2. **≥3 human raters** independently label each of the **200** trajectories pass/fail (~2–3 h/rater).
3. `dmcp rq4-agreement --annotations <sheets> --tier1-evals reports/R1_*/eval_*.jsonl --tier2-evals reports/R6_*/eval_*.jsonl --consensus-out … --json-out …` →
   - **H1:** Cohen's **κ** between Tier-1 verdict and human consensus.
   - **H2:** Krippendorff's **α** over {human raters + Tier-1 + Tier-2 as symmetric raters}.

Only step 2 needs humans; steps 1 & 3 are deterministic (no LLM).

---

## 5. Economics & blockers

| bucket | runs | cost (our 300) | time |
|---|---|---|---|
| **LLM — headline** | R1 | ~$865 | ~6 h (6 keys) |
| **LLM — ablations** | R2–R5 (brute) / (150×4 subset) | ~$2.9k / **~$1.1k** | scales with cells |
| **LLM — extras** | R6–R8 | ~$800 | |
| **No-LLM analyses** | A1–A9 | **$0** | seconds–minutes |
| **Human** | RQ4 | $0 compute | ~2–3 h × ≥3 raters |
| **Scoped total** | R1 + scoped ablations + extras | **≈ $2.2k** | ~1–2 days (6 keys) |

On the merged ~2000 corpus this scales ~6.7× — but each contributor runs **their own** corpus (each swaps `--specs`/`--reference-traces`/`--out`), so per-person cost ≈ corpus-size-proportional, then merge per-candidate JSONL.

**Two blockers:**
1. **Budget** — key at **$531 / $700 (headroom ~$169)** → raise to **~$2.5k** for our share.
2. **Parallelism** — `run_leaderboard --concurrency` pins **one key per cell** ⇒ 1 key = sequential (days). Create **4–6 OpenRouter sub-keys** (`OPENROUTER_API_KEY_2…6`) → `--concurrency 6` → ÷6 wall-clock; or patch the runner for within-key concurrency.

**Open decisions:** (a) judge on/off in the canon — proposed Tier-1 primary + R6 robustness on a subset; (b) raise budget + add sub-keys; (c) ablation subset size (150) and which 4 models.
