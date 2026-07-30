# Benchmark decay / living-benchmark snapshot

- status: done (2026-06-17)
- result: **positive** — re-executing recorded reference effects against the
  live servers shows substantial decay (only 36% reproduce identically),
  substantiating the cached-replay design.
- **superseded by `e9.8-wide-decay-sweep.md`** for the headline and the paper
  table. This snapshot covers 22 traces on three server families; E9.8 re-runs
  the protocol across 113 servers in 12 domains and reports 32.6% identical, so
  the number here replicates but the sample is narrow. Two claims below are
  corrected there: the 32% `broken` rate is a loose upper bound (attributable
  breakage is 0.4% once E9.12's classifier separates unattributable failures),
  and the wikipedia rate-limiting artifact is designed out by sharding workers
  over servers rather than specs. Kept as the narrow prior it is compared against.

## Question

Does the benchmark "decay" — i.e., do the recorded reference effects stop
reproducing as the live servers change over time? If so, by how much? This is
the empirical case for scoring against cached reference traces under
deterministic replay rather than re-scoring live.

## Method

`dmcp refresh` re-executes each spec's recorded successful tool calls against
the live servers in the manifest and classifies every call: **identical** (live
result equals the recording), **drifted** (call succeeds, result differs),
**broken** (call no longer succeeds after retry), **skipped** (`stateful_write`
servers). No LLM is involved.

Reference traces come from the released corpus (`data/merged_hf`, recorded early
June 2026). We filter to traces whose servers are reliably launchable
pip-installed binaries (wikipedia, arxiv, yfinance; git/sqlite get skipped),
avoiding the `npx`-launched servers that hang on startup. A balanced sample of
31 traces is run, each in an isolated subprocess with a 140 s timeout
(`scripts/run_decay.py`) so a hung/rate-limited server marks just that spec
rather than crashing the batch (raw `dmcp refresh` crashes the whole run on one
hung call). Reproduce:

```bash
uv run python scripts/run_decay.py SPECS TRACES manifests/local.json 140
```

## Data

22 of 31 traces completed (126 tool-call re-executions); 9 wikipedia traces
timed out under API rate-limiting and are excluded.

| server (live_read) | calls | identical | drifted | broken |
|---|---|---|---|---|
| yfinance | 18 | 6% | 94% | 0% |
| arxiv | 105 | 40% | 22% | 38% |
| wikipedia | 3 | 67% | 33% | 0% |
| **all** | **126** | **36%** | **33%** | **32%** |

## Result

**Positive.** Only 36% of recorded effects still reproduce identically; a third
have drifted (live data changed) and a third no longer succeed. The per-server
spread matches intuition: live financial data drifts on almost every call,
scholarly metadata is a mix of stable/drifted/broken, and the sampled
encyclopedic content is mostly stable. This is the empirical justification for
deterministic cached replay: re-scoring against the live world would make a
model's pass/fail depend on when it was run.

## Caveats

- **Wikipedia rate-limiting:** the public API throttled repeated requests, so 9
  of 10 wikipedia traces timed out and are excluded; their timeouts are an
  artifact of our request rate, not server decay (wikipedia's true drift is
  likely closer to the 1 completed trace, 33%).
- **`broken` is an upper bound:** with a single retry, transient network
  failures count as broken, so the 32% overstates persistent breakage.
- Modest, uneven N per server (arxiv dominates); this is a demonstration of
  decay, not a precise per-server rate.
