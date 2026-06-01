# Team rule: stay orthogonal to AgentGraphBench (AGB)

**Type:** feedback / hard constraint. **Audience:** every Claude working in this
repo. Referenced from `README.md` and `CLAUDE.md`.

## Why this rule exists

AGB is the team's *already-submitted* NeurIPS paper and it owns the **graph
lane**: tool-dependency-graph construction from JSON schemas, nine topology
motifs, subgraph sampling, a multi-stage validation pipeline, and a ground-truth
*tool set* (denoised by judges). Reviewers in this area know AGB. DynamicMCPBench
is a deliberate structural pivot to a *different organizing object*. If our
design drifts back toward AGB's, the contribution collapses into "AGB without the
graph" — a rejection. So every choice must stay orthogonal.

## The four pillars (never violate)

| Dimension | AGB (don't do this here) | DynamicMCPBench (do this) |
|---|---|---|
| Organizing object | tool dependency graph + motifs | **execution trace** (real trajectory) |
| Generation direction | backward: sample subgraph → back-instruct | **forward: explore live → distill from a success** |
| Substrate | static cached catalog (StableToolBench) | **live, stateful, crawled servers** |
| Ground truth | GT tool set (denoised) | **reference trace → effect checkpoints; no GT tool list** |
| Eval signal | tool-selection recall on a candidate list | **trace/effect alignment + intermediate state** |
| Final answer | checked | **deliberately not checked** (robust to live data) |
| Difficulty axis | graph motif class + subgraph size | **emergent trace complexity + dynamism level** |

**How to apply:** the connective thesis is that AGB *diagnosed* the disease (GT
tool lists are ~50% noise) and we offer a *different cure* (trace-grounding makes
the "unnecessary tool" problem impossible by construction — every tool in a trace
was actually invoked). Cite AGB approvingly; never re-implement it.

## Pre-empt the three reviewer objections (keep these answers true in code)

1. **"Isn't this just AGB without the graph?"** No — removing the graph forces a
   different generator (forward exploration), a different ground truth (trace, not
   tool set), and a different evaluation (effect alignment, not recall). Don't add
   a graph back.
2. **"Isn't this just MCPEval?"** No — MCPEval *generates then verifies*
   (generate-then-check). We *explore then distill* (the trace is the primitive,
   not a verification afterthought), score effects/state (not tool-call matching
   against a generated plan), and explicitly refuse to grade the final answer.
3. **"Traces have multiple valid paths — is that fair?"** Yes, by design — that
   is the central contribution. We never require step-for-step reproduction. The
   reference trace compiles into effect checkpoints (+ equivalence sets), causal
   ordering only where a real dependency exists, and minefields. Any trajectory
   satisfying the checkpoints without tripping a minefield passes.

## Concrete do-nots for contributors

- Do **not** add a tool dependency graph, motif sampler, or back-instruction path.
- Do **not** add final-answer string comparison to the scorer.
- Do **not** replace the live substrate with a frozen catalog as the *source of
  truth* (caching for deterministic replay is fine and expected).
- Do **not** annotate or score a ground-truth *tool list*.

## Baselines vs headline (update 2026-06-01)

"Realize ideas from all docs" includes building the **graph** (PDF) and
**sampling** (MVP) approaches — but **only as clearly-labeled comparison
baselines / experimental arms**, never as the project's headline. RQ2 explicitly
needs a backward graph-sampling generator and a direct-generation generator to
compare against forward exploration, so building them is expected. Sampling also
re-enters as an **eval-side distractor / tool-pool sampler** (controls semantic
density around a trace's required tools), which is what makes SAE and P_alt
degradation curves measurable — without making graph-based *task generation* the
primary path. The headline/positioning is unchanged: **trace, not graph; forward,
not backward; effect, not answer; live, not static cache.**
