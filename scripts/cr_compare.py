#!/usr/bin/env python3
"""Compare every camera-ready tool-exposure cell against the curated baseline.

Generalises `scripts/rag_compare.py` from one cell to the whole matrix produced by
`scripts/run_cr_matrix.py`: any number of models, retrieval budgets and
architectures, at one or several attempts. Cells are identified by the eval
filenames the runner writes (`<model>__<condition>__r<repeat>.shard<i>.jsonl`).

Baseline is the released per-run verdicts for the same model on the same task ids
(`<corpus>/leaderboard_e8.10d/verdicts/evals_<model>.jsonl`), matched
task-for-task, so no baseline compute is spent. Tasks still running are simply
absent from both sides.

Scope of v0: aggregation and reporting. It runs nothing and calls no model; every
number is derived from committed verdict files.

Reproduce:
    uv run python scripts/cr_compare.py --evals 'evals/cr/*.jsonl' --corpus hfdl
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import re
from pathlib import Path

BUCKETS = ("short (1-2)", "medium (3-4)", "long (5+)")
CELL_RE = re.compile(r"^(?P<model>.+?)__(?P<cond>.+?)__r(?P<repeat>\d+)\.shard\d+\.jsonl$")


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


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        out = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    if n < 2:
        return float("nan")
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--corpus", default="hfdl")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    specs = {s["task_id"]: s for s in load_jsonl(corpus / "specs.jsonl")}
    depth = {
        t["trace_id"]: sum(1 for s in t.get("steps", []) if s.get("kind") == "call_tool_agent")
        for t in load_jsonl(corpus / "traces.jsonl")
    }

    def bucket(task_id: str) -> str:
        n = depth.get(specs.get(task_id, {}).get("source_trace_id"), 0)
        return BUCKETS[0] if n <= 2 else (BUCKETS[1] if n <= 4 else BUCKETS[2])

    # cell -> task_id -> [passed per attempt]; cell -> cost
    cells: dict[tuple[str, str, int], dict[str, list[bool]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    cost: dict[tuple[str, str, int], float] = collections.defaultdict(float)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m:
            continue
        key = (m["model"], m["cond"], int(m["repeat"]))
        for r in load_jsonl(f):
            cells[key][r["task_id"]].append(bool(r["passed"]))
            cost[key] += (r.get("summary", {}).get("cost") or {}).get("cost_usd") or 0.0
    if not cells:
        raise SystemExit(f"no cell files matched {args.evals}")

    # Cell filenames carry the runner's slug (`kimi-k2.6` → `kimi-k2-6`), while the
    # released verdicts keep the raw model name. Resolve by slugging both sides.
    verdict_dir = corpus / "leaderboard_e8.10d" / "verdicts"
    released = {
        re.sub(r"[^a-z0-9]+", "-", p.stem[len("evals_") :].lower()).strip("-"): p
        for p in sorted(verdict_dir.glob("evals_*.jsonl"))
    }
    baselines: dict[str, dict[str, list[bool]]] = {}

    def baseline(model: str) -> dict[str, list[bool]]:
        if model not in baselines:
            d: dict[str, list[bool]] = collections.defaultdict(list)
            p = released.get(model)
            if p is None:
                print(f"WARNING: no released verdicts for {model!r} — cell has no baseline")
            else:
                for r in load_jsonl(p):
                    d[r["task_id"]].append(bool(r["passed"]))
            baselines[model] = d
        return baselines[model]

    # A shard that dies mid-cell (provider timeout) leaves its tasks absent rather
    # than failed, so a cell can be silently short. Cells scored over different
    # task sets are not comparable — say so loudly instead of averaging anyway.
    subset_lines = Path(args.subset).read_text().splitlines()
    expected = {json.loads(ln)["task_id"] for ln in subset_lines if ln.strip()}
    incomplete = {
        k: sorted(expected - set(v)) for k, v in cells.items() if len(set(v) & expected) < len(expected)
    }
    if incomplete:
        print(f"INCOMPLETE CELLS ({len(incomplete)}) — not comparable until filled:")
        for (model, cond, repeat), missing in sorted(incomplete.items()):
            n_have = len(expected) - len(missing)
            print(f"  {model:22} {cond:8} r{repeat}  {n_have}/{len(expected)} ({len(missing)} missing)")
        print("  fill with: uv run python scripts/run_cr_matrix.py … (--resume is automatic)\n")

    rows = []
    for (model, cond, repeat), results in sorted(cells.items()):
        base = baseline(model)
        for scope in ("all", *BUCKETS):
            ids = [t for t in sorted(results) if t in base and (scope == "all" or bucket(t) == scope)]
            if not ids:
                continue
            n = len(ids)
            first = sum(results[t][0] for t in ids)
            allk = sum(all(results[t]) for t in ids)
            b_first = sum(base[t][0] for t in ids)
            b_mean = sum(sum(base[t]) / len(base[t]) for t in ids)
            lo, hi = wilson(first, n)
            rows.append(
                {
                    "model": model,
                    "condition": cond,
                    "attempts": repeat,
                    "scope": scope,
                    "n": n,
                    "open_first": round(100 * first / n, 1),
                    "open_ci": [round(100 * lo, 1), round(100 * hi, 1)],
                    "open_pass_all": round(100 * allk / n, 1) if repeat > 1 else None,
                    "curated_first": round(100 * b_first / n, 1),
                    "curated_mean": round(100 * b_mean / n, 1),
                    "delta": round(100 * (first - b_first) / n, 1),
                }
            )

    hdr = (
        f"{'model':22} {'cond':8} {'att':>3} {'scope':14} {'n':>4} "
        f"{'open%':>7} {'95% CI':>14} {'cur%':>7} {'delta':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        lo, hi = r["open_ci"]
        tag = "" if r["open_pass_all"] is None else f"  pass^{r['attempts']}={r['open_pass_all']:.1f}"
        print(
            f"{r['model']:22} {r['condition']:8} {r['attempts']:3d} {r['scope']:14} {r['n']:4d} "
            f"{r['open_first']:7.1f} {f'[{lo:.1f}, {hi:.1f}]':>14} {r['curated_first']:7.1f} "
            f"{r['delta']:+7.1f}{tag}"
        )

    overall = {(r["model"], r["condition"], r["attempts"]): r for r in rows if r["scope"] == "all"}
    print("\nspend per cell (USD):")
    for key in sorted(cost):
        tasks = len(cells[key])
        print(f"  {key[0]:22} {key[1]:8} r{key[2]}  {cost[key]:7.2f}  ({tasks} tasks)")
    print(f"  {'TOTAL':22} {'':8}    {sum(cost.values()):7.2f}")

    # Model-ordering preservation (H4), per condition, when ≥3 models ran it.
    ranks = collections.defaultdict(list)
    for (model, cond, repeat), r in overall.items():
        ranks[(cond, repeat)].append((model, r["open_first"], r["curated_first"]))
    print("\nmodel-ordering preservation (Spearman open vs curated):")
    for key, entries in sorted(ranks.items()):
        if len(entries) < 3:
            print(f"  {key[0]:8} r{key[1]}  n_models={len(entries)} — not reported (<3)")
            continue
        rho = spearman([e[1] for e in entries], [e[2] for e in entries])
        print(f"  {key[0]:8} r{key[1]}  n_models={len(entries)}  rho={rho:+.3f}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "rows": rows,
                    "spend_usd": {f"{k[0]}|{k[1]}|r{k[2]}": round(v, 4) for k, v in cost.items()},
                },
                indent=2,
            )
        )
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
