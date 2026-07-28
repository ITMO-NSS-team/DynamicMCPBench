#!/usr/bin/env python3
"""Ask whether open-exposure failures are stochastic or structural, using pass^3.

The matrix measures one attempt per task. That cannot distinguish two very
different worlds: an agent that fails because the required tool was never on
screen, and an agent that fails because it happened to pick badly this time. The
first is a ceiling and retries cannot move it; the second is variance and retries
can.

`dmcp eval --repeat 3` writes one record per attempt (`repeat_index` 0..2), so
three quantities are available per task:

  pass^3        — passed on every attempt. Reliability.
  pass@3        — passed on at least one attempt. What retries can buy.
  mean attempt  — the single-attempt rate, over 3x the data.

Crossed with `cr_recall.py`'s reachability map, the prediction is sharp and
falsifiable: on tasks whose required tools were never retrieved, `pass@3` should
barely exceed the single-attempt rate — no number of retries conjures a tool that
is not in the pool — while on reachable tasks retries should buy real headroom.
If instead the unreachable half shows large headroom, the reachability map is not
measuring what we claim it measures, and the whole decomposition is in doubt.

The `mean attempt` column doubles as a validity check: it is an independent
re-measurement of the `r1` cell in the matrix and should land within sampling
error of it.

Only tasks with all 3 attempts are counted; a task with 1 of 3 recorded would
otherwise deflate pass^3 for a reason that has nothing to do with the agent.

Scope of v0: descriptive. pass^3 was pre-registered as a measurement but carries
no pre-registered decision rule, so this script adjudicates nothing (that is
`cr_decide.py`) and any report using it must say the analysis is exploratory.

Reproduce:
    uv run python scripts/cr_recall.py --corpus hfdl --k 4,8,16,32   # writes the map
    uv run python scripts/cr_passk.py
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
from pathlib import Path

CELL_RE = re.compile(r"^(?P<model>.+?)__(?P<cond>.+?)__r(?P<repeat>\d+)\.shard\d+\.jsonl$")
COND_K = {"rag-4": "4", "rag-8": "8", "rag-16": "16", "rag-32": "32"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--recall", default="evals/cr/recall_per_task.json")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_passk.json")
    args = ap.parse_args()

    want = {json.loads(ln)["task_id"] for ln in Path(args.subset).read_text().splitlines() if ln.strip()}
    reach = json.loads(Path(args.recall).read_text())

    # (model, cond) -> task -> {repeat_index: passed}
    cells: dict[tuple[str, str], dict[str, dict[int, bool]]] = collections.defaultdict(
        lambda: collections.defaultdict(dict)
    )
    single: dict[tuple[str, str], dict[str, bool]] = collections.defaultdict(dict)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m:
            continue
        rep = int(m["repeat"])
        if rep not in (1, args.repeat):
            continue
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r["task_id"] not in want:
                continue
            if rep == 1:
                single[(m["model"], m["cond"])].setdefault(r["task_id"], bool(r["passed"]))
            else:
                cells[(m["model"], m["cond"])][r["task_id"]][int(r.get("repeat_index", 0))] = bool(
                    r["passed"]
                )

    out: dict[str, dict] = {}
    header = (
        f"{'model':18} {'cond':7} {'reach':>6} {'n':>4} "
        f"{'pass^3':>7} {'pass@3':>7} {'attempt':>8} {'headroom':>9} {'r1':>6}"
    )
    print(header)
    print("-" * len(header))
    for (model, cond), tasks in sorted(cells.items()):
        k = COND_K.get(cond)
        groups: dict[bool, list[list[bool]]] = collections.defaultdict(list)
        for tid, runs in tasks.items():
            if len(runs) != args.repeat:
                continue
            ok = reach[k][str(tid)] if k else True
            groups[ok].append([runs[i] for i in sorted(runs)])
        for ok in (True, False):
            v = groups.get(ok)
            if not v:
                continue
            n = len(v)
            hat = 100 * sum(1 for r in v if all(r)) / n
            at = 100 * sum(1 for r in v if any(r)) / n
            mean = 100 * sum(sum(r) for r in v) / (n * args.repeat)
            r1 = single.get((model, cond), {})
            r1_sub = [p for t, p in r1.items() if (reach[k][str(t)] if k else True) is ok]
            r1_pct = 100 * sum(r1_sub) / len(r1_sub) if r1_sub else float("nan")
            out[f"{model}|{cond}|{'reachable' if ok else 'unreachable'}"] = {
                "tasks": n,
                f"pass_hat_{args.repeat}": round(hat, 1),
                f"pass_at_{args.repeat}": round(at, 1),
                "mean_attempt": round(mean, 1),
                "retry_headroom": round(at - mean, 1),
                "single_run_r1": round(r1_pct, 1) if r1_sub else None,
            }
            print(
                f"{model:18} {cond:7} {'yes' if ok else 'NO':>6} {n:4d} "
                f"{hat:7.1f} {at:7.1f} {mean:8.1f} {at - mean:9.1f} {r1_pct:6.1f}"
            )

    print("\nheadroom = pass@3 - mean attempt: what retrying buys.")
    print("A reachability ceiling is not a variance problem, so the NO rows should show little.")
    print("r1 = the matrix cell on the same tasks; it and 'attempt' measure the same quantity twice.")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
