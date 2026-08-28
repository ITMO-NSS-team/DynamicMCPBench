"""Compare retrieval-over-full-catalog against the released curated-pool baseline.

Condition under test: `dmcp eval --pool full --architecture rag --rag-k 8`, i.e.
the candidate is offered only the top-k tools retrieved from the *entire* catalog
instead of a curated pool of required tools plus eight distractors.

Baseline: the released per-run verdicts for the same model on the same task_ids
(leaderboard_api/verdicts), so no baseline compute is spent. Comparison is
matched task-for-task; tasks still running are simply absent from both sides.

Reproduce:
    uv run python scripts/rag_compare.py --model qwen3.7-max
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
from pathlib import Path


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.7-max")
    ap.add_argument("--evals", default="evals/rag_shard*.jsonl")
    ap.add_argument("--specs", default="../hfdl/specs.jsonl")
    ap.add_argument("--traces", default="../hfdl/traces.jsonl")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    specs = {s["task_id"]: s for s in load_jsonl(args.specs)}
    depth: dict[str, int] = {}
    for tr in load_jsonl(args.traces):
        depth[tr["trace_id"]] = sum(1 for s in tr.get("steps", []) if s.get("kind") == "call_tool_agent")

    def bucket(task_id: str) -> str:
        sp = specs.get(task_id, {})
        n = depth.get(sp.get("source_trace_id"), 0)
        return "short (1-2)" if n <= 2 else ("medium (3-4)" if n <= 4 else "long (5+)")

    rag: dict[str, bool] = {}
    for f in sorted(glob.glob(args.evals)):
        for r in load_jsonl(f):
            rag[r["task_id"]] = bool(r["passed"])
    if not rag:
        raise SystemExit("no results yet")

    base = collections.defaultdict(list)
    for r in load_jsonl(f"hfdl/leaderboard_api/verdicts/{args.model}.jsonl"):
        if r["task_id"] in rag:
            base[r["task_id"]].append(bool(r["passed"]))

    common = sorted(set(rag) & set(base))
    rows = []
    for scope in ("all", "short (1-2)", "medium (3-4)", "long (5+)"):
        ids = [t for t in common if scope == "all" or bucket(t) == scope]
        if not ids:
            continue
        n = len(ids)
        r_k = sum(rag[t] for t in ids)
        b_first = sum(base[t][0] for t in ids)
        b_mean = sum(sum(base[t]) / len(base[t]) for t in ids)
        rows.append(
            {
                "scope": scope,
                "n": n,
                "retrieval_full": round(100 * r_k / n, 1),
                "retrieval_ci": [round(100 * x, 1) for x in wilson(r_k, n)],
                "curated_first_attempt": round(100 * b_first / n, 1),
                "curated_mean_of_3": round(100 * b_mean / n, 1),
                "delta_vs_first": round(100 * (r_k - b_first) / n, 1),
            }
        )

    w = max(len(r["scope"]) for r in rows)
    cond = "--pool full --architecture rag --rag-k 8"
    print(f"model={args.model}  matched tasks={len(common)}  (condition: {cond})\n")
    print(f"{'scope'.ljust(w)}   n   retrieval%   95% CI          curated%(1st)  curated%(mean3)  delta")
    for r in rows:
        lo, hi = r["retrieval_ci"]
        print(
            f"{r['scope'].ljust(w)} {r['n']:3d}      {r['retrieval_full']:5.1f}   "
            f"[{lo:4.1f}, {hi:4.1f}]        {r['curated_first_attempt']:5.1f}          "
            f"{r['curated_mean_of_3']:5.1f}      {r['delta_vs_first']:+5.1f}"
        )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"model": args.model, "rows": rows}, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
