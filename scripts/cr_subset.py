#!/usr/bin/env python3
"""Rebuild the depth-balanced task subset used by the open-universe experiments.

The camera-ready tool-exposure matrix (`docs/experiments/e9.1-*`) reuses the
slice introduced by `e8.11`: tasks drawn from the released 750-task leaderboard
slice, balanced across reference-chain depth (short 1-2, medium 3-4, long 5+),
sampled with a fixed seed so every condition is scored over identical task ids.

The 750-task slice itself is recovered from the released per-run verdicts
(`leaderboard_api/verdicts/*.jsonl`): a task belongs to the slice iff
every model in the leaderboard has a verdict for it. Chain depth is the number
of `call_tool_agent` steps in the spec's source trace.

Scope of v0: subset selection only. It does not run or score anything, makes no
network or LLM calls, and never inspects candidate behaviour — the sample must
not depend on how any model performed.

Reproduce:
    uv run python scripts/cr_subset.py --corpus hfdl --n-per-bucket 50 \
        --out manifests/subsets/cr150.jsonl
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import random
from pathlib import Path

BUCKETS = ("short (1-2)", "medium (3-4)", "long (5+)")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def depth_bucket(n: int) -> str:
    return BUCKETS[0] if n <= 2 else (BUCKETS[1] if n <= 4 else BUCKETS[2])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="hfdl", help="dir holding specs.jsonl, traces.jsonl, verdicts")
    ap.add_argument("--verdicts", default="", help="glob of leaderboard verdicts (default: <corpus>/…)")
    ap.add_argument("--n-per-bucket", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--ids-out", default="", help="optional path for the bare task-id list")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    specs = {s["task_id"]: s for s in load_jsonl(corpus / "specs.jsonl")}
    depth = {
        t["trace_id"]: sum(1 for s in t.get("steps", []) if s.get("kind") == "call_tool_agent")
        for t in load_jsonl(corpus / "traces.jsonl")
    }

    pattern = args.verdicts or str(corpus / "leaderboard_api" / "verdicts" / "*.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no verdict files matched {pattern}")
    slice_ids: set[str] | None = None
    for f in files:
        seen = {r["task_id"] for r in load_jsonl(f)}
        slice_ids = seen if slice_ids is None else (slice_ids & seen)
    assert slice_ids is not None
    pool = sorted(t for t in slice_ids if t in specs)

    by_bucket: dict[str, list[str]] = collections.defaultdict(list)
    for task_id in pool:
        n = depth.get(specs[task_id].get("source_trace_id"), 0)
        by_bucket[depth_bucket(n)].append(task_id)

    rng = random.Random(args.seed)
    chosen: list[str] = []
    for b in BUCKETS:
        candidates = sorted(by_bucket[b])
        if len(candidates) < args.n_per_bucket:
            raise SystemExit(f"bucket {b!r} has {len(candidates)} tasks < {args.n_per_bucket}")
        chosen.extend(rng.sample(candidates, args.n_per_bucket))
    chosen.sort()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(specs[t]) for t in chosen) + "\n")
    if args.ids_out:
        Path(args.ids_out).write_text("\n".join(chosen) + "\n")

    print(f"leaderboard slice: {len(pool)} tasks over {len(files)} models")
    for b in BUCKETS:
        print(f"  {b:14} pool={len(by_bucket[b]):4d}  sampled={args.n_per_bucket}")
    print(f"wrote {out} ({len(chosen)} specs, seed={args.seed})")


if __name__ == "__main__":
    main()
