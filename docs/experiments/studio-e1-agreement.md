# Studio-E1 — studio-vs-batch verdict agreement

**Status:** done. The DMCP Studio backend reproduces the batch pipeline's
deterministic Tier-1 verdicts exactly (118/118 overall, 708/708 per-checkpoint).

## Question / hypothesis

DMCP Studio (the demo-track system) scores a candidate through
`backend/dmcp_adapter.py::score_pair` → `dmcp.evaluator.evaluate`. The batch
pipeline scores through the `dmcp eval` CLI → the same `evaluate`. The studio
adds a layer the batch path does not: it serializes the `TaskSpec` and candidate
`Trace` to JSON over HTTP and reshapes the result into a `ScoreDone`. **Does
that wrapping + JSON round-trip ever change the deterministic Tier-1 verdict?**
It must not — the demo's credibility rests on showing the *real* scorer.

## Method

- **Pairs:** the showcase `TaskSpec` (AAPL/MSFT/GOOGL, 6 checkpoints incl. one
  `download`/`get_price_history` equivalence set) × **118 deterministic
  candidate traces** built programmatically: every subset of the five
  tool-effect checkpoints, both price-history equivalence tools, the
  value-checkpoint met/unmet, two arg/server perturbations (wrong-server SAE,
  wrong `period` arg), and 20 *passing variants* with benign perturbations
  (reordered steps, duplicate/extra successful calls, either equivalence tool)
  that must not change the verdict. No LLM, no network, fully reproducible.
- **Studio side:** `dmcp_adapter.score_pair` (the exact core the `/api/score`
  route runs) → overall `passed` + every per-checkpoint pass/fail.
- **Batch side:** the real `dmcp eval <specs> --candidate-traces <cands>` CLI as
  a **subprocess** (independent process; reads/writes JSONL on disk; full
  ingestion machinery) → the `EvaluationResult` per candidate trace.
- **Match:** by `candidate_trace_id`; compare overall `passed` and per-checkpoint
  `passed`. (SAE subtype depends on `server_tags` but the Tier-1 *verdict* does
  not; E1 compares the verdict.)

**Reproduce:**

```bash
uv run python dmcp-studio/experiments/e1_agreement.py
# → dmcp-studio/experiments/results/e1_agreement.json
```

## Decision rule (pre-registered)

Tier-1 is deterministic, so the bar is **exact**: agreement must be **100%** on
both the overall verdict and every per-checkpoint verdict. **Any** discrepancy
is classified **negative** — a bug in the studio's wrapping to be fixed, not a
tolerance to accept.

## Data

| metric | value |
|---|---|
| candidate pairs | 118 (22 pass / 96 fail) |
| overall verdict agreement | **100.0 %** (118/118) |
| per-checkpoint agreement | **100.0 %** (708/708) |
| disagreements | 0 |

The 22/96 pass/fail split confirms the battery exercises real verdict variety
(not a degenerate all-pass or all-fail set); the 708 per-checkpoint comparisons
span met and unmet for every checkpoint, including both equivalence-set tools.

## Result

**Positive.** Exact agreement on both the overall verdict and all per-checkpoint
verdicts, meeting the pre-registered 100% bar.

## Conclusion & implication

The studio's JSON round-trip and `ScoreDone` shaping do not perturb the
deterministic Tier-1 verdict: the demo shows the pipeline's own scorer, not a
re-implementation. This is the paper's E1 credibility result
(`paper_demo/tables/agreement.tex`). Tier-2 (the non-deterministic LLM
equivalence judge) is off the demo's critical path and out of scope here.
