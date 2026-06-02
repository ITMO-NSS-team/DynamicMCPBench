# DynamicMCPBench: a trace-grounded, effect-scored benchmark for LLM agents over live MCP servers

_Working title; venue (NeurIPS / EMNLP / ICLR) TBD until §5 is complete._

## Abstract

LLM agent benchmarks that score the **final answer** against a reference
string are fragile under live, stateful data: today's "Madrid" becomes
tomorrow's stale fact, and a candidate that did the right tools with the
wrong wording gets penalized while a candidate that parroted the right
words without invoking any tools gets credit. We introduce
**DynamicMCPBench**, a benchmark whose ground truth is an **execution
trace**, not a tool list or a final string. Tasks are *forward-generated*
by exploring live MCP servers with a goal-seeded explorer until a
successful trajectory is recorded; that trace is **distilled** into
path-agnostic effect **checkpoints** and trip-wire **minefields**.
Evaluation never grades the answer — it grades whether the candidate's
trajectory produces the demanded effects, with *any* permitted tool, in
the necessary causal order. On 56 tasks × 3 models with no new LLM calls,
the final-answer scorer's ranking is **near-inverted** vs the trace-align
ranking (Kendall's τ = −0.816); its false-pass rate is **63 %** while
trace-align's false-fail rate is **1.8 %**. A pre-registered comparison
against the two closest prior-art generation shapes — graph-sampling +
back-instruction (AGB) and direct generate-then-verify (MCPEval) — shows
that only forward-distilled specs admit non-trivial *equivalence sets*
(mean |eq_set| = 1.42 vs 1.00 / 1.00 by construction), the structural
difference that makes path-agnostic scoring possible. A trace-property
failure model fit per candidate identifies **task dynamism** (`live_read`
vs `static`) as the dominant statistical driver of failure across all
three candidate models.

> **Status (E5.1).** This abstract draft is the scaffold target — concrete
> numbers come from the experiment reports under `docs/experiments/`
> (`e4.3`, `e4.4`, `e4.5`); it will be refreshed once `e4.6` (scorer-vs-
> human) and `e4.7` (≥5-model leaderboard) land.

[Fig 1 here — pipeline overview. See `figures.md::fig:pipeline`.]

---

## §1 Introduction

### 1.1 Motivation

LLM agents over Model Context Protocol (MCP) servers are an increasingly
real deployment surface; their benchmarks are not. The two prevailing
shapes for "how do we know an agent did the right thing?" both lean on
proxies that wobble under live data:

- **Final-answer string matching** (the common-case "score the reply
  against the reference answer"). Works for static fact-recall, breaks
  the moment the answer depends on the current world: today's weather,
  this morning's commit, the live database row.
- **Tool-list recall** (AGB and its descendants). The ground truth is the
  set of tools the agent *should have called*. Diagnosed by AGB itself as
  ~50 % noise — *unnecessary tools* drift in because tool lists are not
  observable from prompts alone.

We propose to **change the organizing primitive** of the benchmark from
*answer* and *tool set* to the **execution trace**. The trace is the only
object that is unambiguously observable (we recorded it) and unambiguously
faithful (every tool in a trace was actually invoked).

### 1.2 Claims & contributions

1. **A forward generator** (`dmcp explore → dmcp distill`) that turns a
   live successful trajectory into a path-agnostic `TaskSpec` made of
   effect *checkpoints* and *minefields*, with *equivalence sets* over
   tools that genuinely substitute (Method §3). The headline structural
   property absent in prior-art generators: forward distillation emits
   `mean |equivalence_set| > 1.0`, while graph-sampling and direct
   generate-then-verify are singletons by construction
   (Experiment e4.3, §5.2).
2. **Trace/effect alignment** as the scorer (`evaluator.py`, Tier-1
   deterministic) with an optional LLM judge (Tier-2). Never grades the
   final answer; never requires step-for-step trajectory match
   (Method §3.3). On 56 × 3 evals: switching from trace-align to
   answer-match inverts the model ranking, Kendall's τ = **−0.816**;
   answer-match's false-pass rate is **63 %** vs trace-align's
   **1.8 %** false-fail rate (Experiment e4.4, §5.1).
3. **A trace-property failure model** identifying `dynamism_live` as the
   dominant driver of failure across candidate models (pooled
   β = −3.110, drop-loglik +6.606, ≈ 70 % of pooled importance budget
   on the v3 substrate; Experiment e4.5, §5.3).
4. **A living-bench protocol** for measuring decay between distillation
   and re-evaluation (`dmcp refresh`, §3.4; deployment-time numbers
   pending E1.5).
5. **A reproducible substrate** of vetted, sandboxed, live MCP servers
   (currently 16; target ≥ 100, §4; scale gated on E3).

### 1.3 Headline figures

[Fig 1 — pipeline overview (recap, see §3).]

[Fig 3 — answer-match vs trace-align (the τ = −0.816 result). See
`figures.md::fig:rq1_kendall`.]

### 1.4 Paper structure

§2 frames the AGB / MCPEval / MCP-Bench / τ-bench / StableToolBench
landscape and pins down the dimensions along which DynamicMCPBench is
*deliberately orthogonal* to AGB. §3 walks the generation and scoring
pipeline. §4 documents the substrate. §5 reports RQ1–RQ4 with their
pre-registered decision rules. §6 discusses what the empirical pattern
implies; §7 covers limitations and the living-bench release plan.

---

## §2 Related work and the AGB-orthogonality stance

The neighbourhood DynamicMCPBench sits in: **AgentGraphBench (AGB)** for
graph-shaped tool-use evaluation; **MCPEval** for generate-then-verify
task synthesis over MCP servers; **MCP-Bench** and **MCP-Atlas** for
substrate breadth; **τ-bench** and **ToolSandbox** for state-coupled tool
use; **StableToolBench** for caching as a determinism mechanism. See
`memory/reference_key_papers.md` for the full reference list.

This paper's structural choice is to **stay orthogonal to AGB** along
the four pillars below. The headline AGB connective thesis we adopt is
that they **diagnosed the disease** (GT tool lists are ~50 % noise) and
that DynamicMCPBench offers a **different cure** (trace-grounding makes
the unnecessary-tool problem impossible by construction — every tool in
a trace was actually invoked).

| dimension | AgentGraphBench (AGB) | DynamicMCPBench (this paper) |
|---|---|---|
| Organizing object | tool-dependency graph + motifs | **execution trace** (real trajectory) |
| Generation direction | backward: sample subgraph → back-instruct | **forward: explore live → distill from success** |
| Substrate | static cached catalog (StableToolBench-style) | **live, stateful, crawled MCP servers** |
| Ground truth | GT tool set (denoised) | **reference trace → effect checkpoints; no GT tool list** |
| Eval signal | tool-selection recall on a candidate list | **trace/effect alignment + intermediate state** |
| Final answer | checked | **deliberately not checked** (robust to live data) |
| Difficulty axis | graph-motif class + subgraph size | **emergent trace complexity + dynamism level** |

We pre-empt three reviewer objections from the AGB neighbourhood:

1. *"Isn't this just AGB without the graph?"* No — removing the graph
   forces a different *generator* (forward exploration), a different
   *ground truth* (trace, not tool set), and a different *evaluation*
   (effect alignment, not recall). The graph re-enters this paper
   **only** as one of two clearly-labeled RQ2 baselines (§5.2).
2. *"Isn't this just MCPEval?"* No — MCPEval is
   generate-then-verify; we are **explore-then-distill**. The trace is
   the primitive, not a verification afterthought; we score effects /
   state, not tool-call matching against a generated plan; we refuse
   to grade the final answer.
3. *"Traces have multiple valid paths — is that fair?"* Yes, by design.
   The reference trace compiles into checkpoints with equivalence sets,
   causal ordering *only where a real dependency exists*, and minefields.
   Any trajectory satisfying the checkpoints without tripping a minefield
   passes (§3.3).

---

## §3 Method

### 3.1 Substrate and trace recording

We start from a **server manifest** (`dmcp/manifest.py`) declaring each
MCP server's transport, **dynamism class** (`static / live_read /
stateful_write`), and a hard `sandbox=true` requirement for any
`stateful_write` server. The recorder (`dmcp/recorder.py`) is the only
substrate the rest of the pipeline talks to; its replay counterpart
(`dmcp/replay.py`) is a drop-in interchange that turns recorded traces
into a deterministic world for scoring (§3.4).

### 3.2 Forward generation: goal → exploration → distillation

A **goal generator** (`dmcp/goal_gen.py`) drives an LLM to propose
realistic user goals against each server's tool surface (per-server and
cross-server pairs), with deterministic **persona seeding**
(`dmcp/personas.py`). The **explorer** (`dmcp/explorer.py`) executes one
goal as an agent loop with a turn budget against the live substrate. On
success, the recorded trace is fed to the **distiller**
(`dmcp/distiller.py`), which produces a `TaskSpec`:

- a fuzzy natural-language **prompt** (tool names stripped, concrete
  resources retained);
- one or more **checkpoints**: `tool_effect` (a tool from an *equivalence
  set* must have been called, optionally matching arg predicates) and
  `value_produced` (a tool result must contain demanded substrings);
- optional **minefields** (forbidden tools / args);
- an **ordering** of checkpoints — partial; only where one effect
  genuinely depends on a prior one. Parallelizable effects are left
  unordered on purpose.
- a `ComplexityProfile` (trace depth, runtime branching, state coupling,
  cross-server) and dynamism class for stratification.

The distiller is explicit about its scope: it never invents checkpoints
the trace does not justify; it always echoes the LLM's ambiguity notes
into `TaskSpec.notes` so reviewers can see what the model was unsure
about.

[Fig 2 here — example trace → TaskSpec. See `figures.md::fig:trace_distill_example`.]

### 3.3 Evaluation: Tier-1 deterministic, Tier-2 LLM judge

Given a candidate trace and a `TaskSpec`, **Tier-1**
(`dmcp/evaluator.py`) is fully deterministic: for each `tool_effect`,
verify some tool from the equivalence set was called with arguments
satisfying the predicate; for each `value_produced`, verify the
substring; for each minefield, verify it was not tripped; verify the
partial order. **Tier-2** (`dmcp/judge.py`) optionally upgrades failed
`tool_effect` checks via an LLM **effect-equivalence judge** — also
constrained to a tool-call schema at `temperature=0`. The fair
multi-agent path is `dmcp eval --replay`: candidates run against a
`TraceReplayRecorder` built from each spec's source trace, so the world
is identical across candidates and re-runs.

Critically, we **never grade the final answer** for correctness. A
`value_produced` checkpoint matches *evidence the spec demands*, never
"is the answer right". §5.1 (RQ1) shows what happens when one does.

### 3.4 Living bench: refresh and decay

The `refresh` path (`dmcp/refresh.py`) re-runs each spec's reference
trace against the live substrate and classifies every reference call as
*identical / drifted / broken / skipped*. A `dmcp report` decay table
turns this into the stratified drift rate that signals when a spec
should be re-distilled. Stateful_write servers are **skipped by default**
in refresh — re-running a `git_create_branch` with the same name would
just fail; the explicit `--refresh-stateful` override is for sandboxes
known to support re-execution.

### 3.5 Eval-side controls: tool-pool sampling, P_alt degradation

Beyond the headline scoring path, evaluation supports **distractor pool
modes** (`gold | target | full`) with a sampler over six strategies
(`random / hard_neg / cross_domain / same_name / sibling / stratified`,
`dmcp/sampling.py`) and a **description normalizer** (`Level A` surface
vs `Level B` semantic, `dmcp/normalize.py`). The **P_alt** driver
(`dmcp/curves.py`) sweeps the alternative-tool density and produces
degradation curves with Wilson CIs by complexity bin (§5.5).

---

## §4 Substrate

The v3 substrate is documented in `memory/project_v3_scale_tier2.md`:
16 servers spanning `static / live_read / stateful_write`, 56 distilled
specs, multi-model leaderboard discriminating between candidate models.
This is the working scale of every experiment in §5.

The paper-target substrate is **≥ 100 vetted servers** (E3) — that scale
work is in progress; numbers in §5 will be re-derived on the larger
substrate before submission. The §4 table below is updated by E3.5 (the
*substrate coverage report*).

[Tbl 4 here — substrate breakdown. See `figures.md::tab:substrate`.]

[Fig 4 here — performance by dynamism × depth bin. See
`figures.md::fig:perf_by_dynamism_depth`.]

---

## §5 Experiments

Every experiment in this section has a **pre-registered decision rule**
that lives in its own report under `docs/experiments/`. The paper never
re-derives numbers; it cites the experiment id.

### 5.1 RQ1: answer-match vs trace/effect alignment (e4.4)

**Setup.** Same 56 forward-distilled specs × 3 candidate models
(`anthropic/claude-haiku-3.5`, `anthropic/claude-haiku-4.5`,
`qwen/qwen3-8b`); same replay-mode evaluation. Both scorers consume the
same eval JSONLs. The answer-match scorer (`dmcp/baselines/answer_match.py`)
is token-Jaccard with substring fallback; threshold 0.5.

**Decision rule (pre-registered).** Positive iff Kendall's τ between the
two model rankings < 0.5 AND `false_pass > false_fail`.

**Result.** **τ = −0.816** (rankings nearly reversed). The strongest
model under trace-align (haiku-4.5, 45 %) becomes the worst under
answer-match (89 %, tied with qwen3); the weakest under trace-align
(haiku-3.5, 21 %) becomes the best under answer-match (95 %). Overall
false-pass rate = **63.1 %**; false-fail rate = **1.8 %**.

**Implication.** A leaderboard scored by final-answer string match
*would attribute the best score to the model that least often does the
right thing*. The CLAUDE.md "never grade the final answer" invariant
acquires a quantitative defense.

[Fig 3 here — answer-match vs trace-align. See `figures.md::fig:rq1_kendall`.]

### 5.2 RQ2: forward vs graph-sampling vs direct generation (e4.3)

**Setup.** Three TaskSpec generation paths on a shared substrate
(`time + wikipedia + arxiv`): the headline **forward distillation**
(9 specs filtered from v3); a **graph-sampling baseline**
(`dmcp/baselines/graph_sampling.py`, 6 specs across `chain` and `hub`
motifs); a **direct generate-then-verify baseline**
(`dmcp/baselines/direct_generation.py`, 9 specs). Both baselines are
clearly labeled (`distiller_version="baseline-…"`) and never imported
by the headline scoring path.

**Decision rule (pre-registered).** Positive iff forward
`mean |eq_set| > 1.05` AND both baselines `mean |eq_set| == 1.0`.

**Result.** **Forward mean |eq_set| = 1.42** (max 2, singleton-rate
58 %). Both baselines = 1.00 exactly, by construction. Filter pass rate
100 % / 100 %; coverage 65 % / 44 % / 18 %; zero marker violations.

**Implication.** Path-agnostic equivalence sets are the structural
difference between forward distillation and the two closest prior-art
shapes. The gap is what makes effect-based scoring (§3.3) faithful
across multiple valid agent trajectories.

[Tbl 1 here — RQ2 comparison. See `figures.md::tab:rq2_comparison`.]

### 5.3 RQ3: trace-property failure model (e4.5)

**Setup.** Ridge-regularized logistic regression of pass/fail on the
`ComplexityProfile` + dynamism features
(`trace_depth, runtime_branching, state_coupling, cross_server,
dynamism_live, dynamism_stateful`); per-candidate + pooled. Pure-Python
IRLS, no new dep. Drop-column permutation importance.

**Decision rule (pre-registered).** Positive iff at least one feature
has `|β| > 0.5` in the pooled fit AND that feature's drop-loglik loss
> 0.5 AND it is the top driver in ≥ 2 of 3 per-model fits.

**Result.** Pooled `dynamism_live` β = **−3.110**, odds ratio
**0.045**, drop-loglik loss **+6.606** — ≈ 70 % of the pooled
importance budget. Top driver in `haiku-4.5` and `qwen3-8b`; second
behind `trace_depth` in `haiku-3.5`. Secondary effects:
`trace_depth` (β = −0.097, loss +1.682) and `cross_server`
(β = −0.757, loss +0.871).

**Implication.** Task **dynamism** is not just a taxonomy label — it is
the dominant statistical driver of failure across models. This is the
empirical defense of the project's choice to stratify by dynamism
class in §4 / §5.5.

[Fig 4 here — perf by dynamism × depth. See `figures.md::fig:perf_by_dynamism_depth`.]

### 5.4 RQ4: scorer-vs-human validation (e4.6, status: planned)

**Setup.** A deterministic stratified subset of 200 tasks
(`dmcp rq4-subset`, balanced by dynamism × complexity_bin), three human
raters per cell, full annotation protocol pre-registered in
`docs/experiments/e4.6-rq4-scorer-vs-human.md`. Cohen's κ between
Tier-1 / Tier-2 verdicts and the majority-vote consensus; Krippendorff's
α over the full rater × scorer grid; replay determinism (Tier-1 verdict
flip rate between two re-runs).

**Decision rule (pre-registered).** Positive iff `tier1_kappa ≥ 0.70`
AND `tier2_kappa ≥ 0.70` AND replay flip rate < 5 %.

**Result.** _Pending the human annotation pass — the harness merged
without faking numbers._ The experiment doc captures the protocol so the
result can be filled in deterministically once raters complete the pass.

**Implication (preview).** Whatever the result, it is the **honest
calibration** for every claim in §5.1–§5.3: if κ ≥ 0.70 the trace-align
scorer is materially aligned with humans; if it is not, the downstream
claims are revisited.

[Tbl 3 here — RQ4 scorer-vs-human. See `figures.md::tab:rq4_agreement`.]

### 5.5 Degradation curves: P_alt and complexity stratification (E2.7)

The pool sampler (§3.5) drives a P_alt grid `∈ {0, .25, .5, .75, 1.0}`
that quantifies how candidate accuracy and SAE rate degrade as
alternative tools dilute the candidate's tool surface. Results are
stratified by complexity bin (`1 / 2 / 3-4 / 5+` required tools) with
macro and micro averages. Reports a per-strategy × per-level × P_alt
table and curve plots.

[Fig 5 here — P_alt degradation curves. See
`figures.md::fig:p_alt_degradation`.]

### 5.6 Living bench: decay over time (E1.5)

`dmcp refresh` re-executes each spec's reference trace against the
live substrate at a later time and classifies every call as identical /
drifted / broken / skipped. Reports per-server drift rates and a
decay table; spec staleness is gated by a configurable threshold.

[Fig 6 here — decay curve. See `figures.md::fig:decay_curve`.]

### 5.7 Leaderboard and capability profile (E4.7, pending)

≥ 5 candidate models (a GPT-class, Gemini, Claude Sonnet / Opus, an
open-weight 70B+, a tool-specialized model) under replay, 3 × per task.
Per-stratum capability profile = accuracy by (dynamism, complexity bin,
recovery_required, runtime_branching). Pending E3.1's substrate scale-up.

[Tbl 2 here — capability profile. See `figures.md::tab:capability_profile`.]

---

## §6 Discussion

### 6.1 Why trace-grounding works

The single sentence: *every tool in a recorded trace was actually
invoked, so "unnecessary tool" is impossible by construction.* The
forward-distilled spec compiles a real trajectory into its effects, then
asks the candidate to *produce those effects*, not *replay the
trajectory*. RQ2 quantifies the structural property; RQ1 quantifies
what happens if you forget it and revert to answer matching.

### 6.2 What dynamism explains and what it doesn't

RQ3's dominant `dynamism_live` driver matches the intuition that "the
world moves between distillation and evaluation." But dynamism is also
collinear with task content (`live_read` tasks tend to be the
information-seeking ones); the path forward is the larger substrate
(E3) where content and dynamism can be partially decorrelated. We treat
the RQ3 result as the empirical defense of the *stratification* choice,
not as a per-feature causal claim.

### 6.3 Where the answer string is still useful

DynamicMCPBench's refusal to grade the final answer is not a refusal to
*report* it. The candidate's `final_assistant_message` is stored,
inspectable, and surfaced in the report — it just doesn't move the
score. This separation lets the same artifacts feed downstream studies
(e.g. fluency, justification quality) without contaminating the trace
score.

### 6.4 Comparison shapes vs the headline

The graph-sampling and direct-generation baselines in §5.2 stay
*labeled* (`distiller_version="baseline-…"`) at every level — disk
format, CLI, report aggregator, regression-tested orthogonality guard.
This was deliberate so the RQ2 comparison cannot be confused for "AGB
without the graph"; the gap it measures is the *structural* one.

---

## §7 Limitations & conclusion

### 7.1 Limitations

- **Substrate scale.** The numbers in §5.1 / §5.2 / §5.3 are on the 16-
  server v3 substrate. The paper-target scale (≥ 100 servers, E3) is in
  progress; we re-derive every §5 number on the larger substrate before
  final submission. Until then RQ3's collinearity (state_coupling ≡
  dynamism_stateful in v3) limits per-feature decomposition.
- **Human consensus is pending.** RQ4 ships the harness and the
  pre-registered protocol, not the κ / α numbers. Until annotators
  complete the pass, §5.4 carries the placeholder verdict.
- **LLM-judge non-determinism.** Tier-2 is the only non-deterministic
  scoring path; we mitigate by pinning model + temperature and reporting
  Tier-1 numbers alongside Tier-2.
- **Distiller bias.** The distiller is an LLM; we pin it to a tool-call
  schema at `temperature=0`, but it can still under- or over-emit
  checkpoints in edge cases. The mitigation is the trace-vs-spec
  reviewable record (`TaskSpec.notes`) plus the manual review that
  graduated v3 → released.

### 7.2 Conclusion

We propose a benchmark generation and evaluation shape that **does not
grade the answer** and **does not require a tool-list ground truth**.
The trace is the primitive; effect checkpoints are the contract.
Empirically, the alternative shapes both produce rankings that disagree
sharply with the trace-grounded one (RQ1, RQ2). Trace-property
regression isolates *task dynamism* as the dominant failure driver
(RQ3). The remaining piece — scorer-vs-human calibration — is gated
behind a pre-registered annotation pass (RQ4). Code, manifests, and
released datasets ship as `dmcp` (current repository) and a
HuggingFace dataset (E5.3, pending the §5.7 leaderboard).

---

## Appendix: how this scaffold is regenerated

Empirical numbers in `draft.md` are drawn from
`docs/experiments/*_numbers.json`. The figure index in `figures.md` is
the input contract for E5.2 (auto-generated figures & tables). When E5.2
lands, edits to numbers / figures / tables happen by editing those JSONs
plus a regenerate command, never by editing prose.
