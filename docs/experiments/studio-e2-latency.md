# Studio-E2 — per-stage latency budget (booth)

**Status:** done. The REPLAY booth path is effectively instant (every stage
< 1.4 ms compute; cold-start to first verdict ≈ 1.3 ms vs. a 30 s target), so the
booth runs REPLAY for every stage. Live per-stage timing is not reported: live
exploration is blocked upstream (see *Known blocker* in
`dmcp-studio/PROGRESS.md`) and is not on the booth's critical path.

## Question / hypothesis

Which stages can run LIVE in the booth, and which must be pre-cached (REPLAY)?
Concretely: is the REPLAY studio path fast enough to be interactive, and does it
meet the demo's cold-start-to-first-verdict target?

## Method

- **What is timed:** request **compute** through the real FastAPI routes
  (`servers`, `goal`, `explore`, `distill`, `score`, `leaderboard`) via the
  in-process `TestClient` with **SSE pacing disabled** (`delay=0`) — so we
  measure the system's compute, not the cosmetic ~0.45 s/call inter-event delay
  the booth UI adds for readability. 200 iterations/stage, median + p95.
- Plus the deterministic **evaluator compute** over the 118-pair E1 battery (the
  graded path), and the **cold fixture load** (cleared `lru_cache`).
- Deterministic, no network, no LLM. Measured on the development machine (Apple
  Silicon, macOS); absolute numbers are hardware-dependent but the order of
  magnitude (sub-millisecond) is the point.

**Reproduce:**

```bash
uv run python dmcp-studio/experiments/e2_latency.py
# → dmcp-studio/experiments/results/e2_latency.json
```

## Decision rule (pre-registered)

- A stage runs **LIVE** in the booth iff its latency is reliably < 10 s;
  otherwise **REPLAY**.
- Every REPLAY stage must be interactive: p95 compute < **2 s**; and
  cold-start to first verdict < **30 s** (the A5 acceptance bar).
- **Positive** if the REPLAY stages clear both bars (→ booth runs REPLAY).

## Data

Median / p95 request compute (ms), pacing disabled, n = 200:

| stage | median (ms) | p95 (ms) | booth mode |
|---|---|---|---|
| servers | 0.66 | 0.74 | replay |
| goal | 0.47 | 0.53 | replay |
| explore (SSE) | 0.87 | 0.96 | replay |
| distill | 0.48 | 0.52 | replay |
| score (SSE) | 0.99 | 1.06 | replay |
| leaderboard | 0.69 | 0.75 | replay |

- evaluator / pair (n = 118): median **0.021 ms**, p95 0.025 ms.
- cold fixture load: **0.30 ms**; cold-start → first verdict: **≈ 1.3 ms**.
- slowest action p95 **1.06 ms** ≪ 2 s bar; first verdict **≈ 1.3 ms** ≪ 30 s bar.

## Result

**Positive.** Every REPLAY stage clears the interactive bar by ~3 orders of
magnitude, and cold-start to first verdict beats the 30 s target by ~4 orders.

## Conclusion & implication

The REPLAY booth path carries no meaningful latency — the only time a visitor
perceives is the deliberate, configurable SSE pacing (~0.45 s/call, so the
explore/score animations read as ~3 s). The booth therefore runs **REPLAY for
every stage**: this is forced by the live-explore blocker, but the numbers show
it is also the right call independent of it (deterministic, instant, on-thesis).
LIVE exploration, when restored, would be dominated by LLM/network seconds —
exactly why it is "proof," not the booth's critical path. This is the paper's E2
result (`paper_demo/tables/latency.tex`).
