#!/usr/bin/env python3
"""Reconcile e8.11's open-universe table with the e9.1 exposure matrix.

Both report `qwen/qwen3.7-max` under `--pool full --architecture rag --rag-k 8`
over "150 tasks, 50/50/50 by chain depth, seed 0" drawn from the same released
750-task slice, and they disagree: e8.11 says 36.7 retrieval against 57.3
curated, e9.1 says 30.7 against 54.0. Both curated figures come from the *same*
released verdicts file, so identical draws would give identical curated rates.
They differ, so the draws differ — and the question this script answers is whether
that gap is ordinary sampling variation or a discrepancy the paper must explain.

Method: rebuild the slice and the depth buckets exactly as `cr_subset.py` does,
confirm the committed `cr150` is reproducible from seed 0, then redraw the
balanced 150 two thousand times and locate both curated figures in the resulting
distribution. Finally compare the *paired* quantity each report actually claims —
the deficit, retrieval minus curated — which is insensitive to draw difficulty.

Scope of v0: this one reconciliation. It recomputes nothing about retrieval
itself; e8.11's raw shards are git-ignored and no longer on disk, so the
retrieval rate is taken from its committed report. Deterministic: no LLM calls,
no network, no wall-clock — reads only committed and released artifacts.

Reproduce:
    uv run python scripts/cr_reconcile_e811.py
"""

from __future__ import annotations

import collections
import glob
import json
import random
import statistics
from pathlib import Path

BUCKETS = ("short (1-2)", "medium (3-4)", "long (5+)")
CORPUS = Path("hfdl")
DRAWS = 2000

# Headline numbers as committed in each report.
E811_CURATED, E811_RETRIEVAL = 57.3, 36.7
E91_CURATED, E91_RETRIEVAL = 54.0, 30.7


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def bucket(n: int) -> str:
    return BUCKETS[0] if n <= 2 else (BUCKETS[1] if n <= 4 else BUCKETS[2])


def balanced_draw(seed: int, by_bucket: dict[str, list[str]], per: int = 50) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    for b in BUCKETS:
        out.extend(rng.sample(sorted(by_bucket[b]), per))
    return out


def main() -> None:
    specs = {s["task_id"]: s for s in load_jsonl(CORPUS / "specs.jsonl")}
    depth = {
        t["trace_id"]: sum(1 for s in t.get("steps", []) if s.get("kind") == "call_tool_agent")
        for t in load_jsonl(CORPUS / "traces.jsonl")
    }

    verdict_dir = CORPUS / "leaderboard_api" / "verdicts"
    files = sorted(glob.glob(str(verdict_dir / "*.jsonl")))
    slice_ids: set[str] | None = None
    for f in files:
        seen = {r["task_id"] for r in load_jsonl(f)}
        slice_ids = seen if slice_ids is None else (slice_ids & seen)
    if slice_ids is None:
        raise SystemExit(f"no released verdicts under {verdict_dir}")
    pool = sorted(t for t in slice_ids if t in specs)

    by_bucket: dict[str, list[str]] = collections.defaultdict(list)
    for tid in pool:
        by_bucket[bucket(depth.get(specs[tid].get("source_trace_id"), 0))].append(tid)

    qw: dict[str, bool] = {}
    for r in load_jsonl(verdict_dir / "evals_qwen3.7-max.jsonl"):
        qw.setdefault(r["task_id"], bool(r["passed"]))

    print(f"released slice: {len(pool)} tasks over {len(files)} models")
    for b in BUCKETS:
        ids = [t for t in by_bucket[b] if t in qw]
        print(f"  {b:14} pool={len(ids):4d}  qwen curated={100 * sum(qw[t] for t in ids) / len(ids):5.1f}")
    print(f"  whole slice  n={len(pool):4d}  qwen curated={100 * sum(qw[t] for t in pool) / len(pool):5.1f}")

    committed = {r["task_id"] for r in load_jsonl("manifests/subsets/cr150.jsonl")}
    rebuilt = set(balanced_draw(0, by_bucket))
    print(f"\ncr150 == cr_subset.py(seed=0)?  {rebuilt == committed}")
    print(f"  committed curated = {100 * sum(qw[t] for t in committed) / len(committed):.1f}")

    rates = [100 * sum(qw[t] for t in balanced_draw(s, by_bucket)) / 150 for s in range(DRAWS)]
    mean, sd = statistics.mean(rates), statistics.pstdev(rates)
    srt = sorted(rates)
    p025, p975 = srt[int(0.025 * len(srt))], srt[int(0.975 * len(srt))]

    def pct(x: float) -> float:
        return 100 * sum(1 for v in rates if v <= x) / len(rates)

    print(f"\n{DRAWS} balanced redraws of the same slice — qwen curated:")
    print(f"  mean={mean:.1f}  sd={sd:.2f}  range=[{min(rates):.1f}, {max(rates):.1f}]")
    print(f"  95% of draws fall in [{p025:.1f}, {p975:.1f}]")
    print(f"  e9.1  curated {E91_CURATED:.1f} -> percentile {pct(E91_CURATED):5.1f}")
    print(f"  e8.11 curated {E811_CURATED:.1f} -> percentile {pct(E811_CURATED):5.1f}")
    print(
        f"  separation = {E811_CURATED - E91_CURATED:.1f} points = {(E811_CURATED - E91_CURATED) / sd:.2f} sd"
    )

    d811 = E811_RETRIEVAL - E811_CURATED
    d91 = E91_RETRIEVAL - E91_CURATED
    print("\npaired deficit (retrieval - curated) — the quantity each report actually claims:")
    print(f"  e8.11 : {E811_RETRIEVAL:.1f} - {E811_CURATED:.1f} = {d811:+.1f}")
    print(f"  e9.1  : {E91_RETRIEVAL:.1f} - {E91_CURATED:.1f} = {d91:+.1f}")
    print(f"  they differ by {abs(d811 - d91):.1f} points")


if __name__ == "__main__":
    main()
