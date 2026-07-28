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

**The zero on the unreachable half is not a finding.** `cr_recall.py` marks a task
unreachable exactly when some `tool_effect` checkpoint has no member of its
`equivalence_set` in the pool; that checkpoint then cannot pass, and passing needs
all of them. So `pass@3 = 0` there is very nearly entailed by the definitions, and
the table prints it as a consistency check, not as evidence. Its only empirical
content is narrow: a task could in principle be satisfied by a tool reached
server-internally rather than by the agent, and across these attempts that never
happened.

What the repeats actually buy is the informative quantity, and it is not entailed
by anything:

  recovered = (pass@3 - single attempt) / (curated - single attempt)

the share of the exposure deficit that triple the attempt budget wins back. If
open exposure were mostly bad luck, three attempts would recover most of it.

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
    ap.add_argument("--corpus", default="hfdl")
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
                # First record wins, matching the single-attempt path above. A cell
                # refilled with `--resume` can hold more than one record for the same
                # (task_id, repeat_index) — resume skips per task, not per attempt, so a
                # re-shard rewrites attempts that already landed. Keeping the first means
                # the original run's verdicts stand and a refill only closes real gaps.
                cells[(m["model"], m["cond"])][r["task_id"]].setdefault(
                    int(r.get("repeat_index", 0)), bool(r["passed"])
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
    print("The NO rows are a consistency check, not evidence: an unreachable task's")
    print("tool_effect checkpoint cannot pass, so 0.0 there is entailed by the definitions.")
    print("r1 = the matrix cell on the same tasks; it and 'attempt' measure the same quantity twice.")

    # The quantity that is NOT entailed: how much of the exposure deficit three
    # attempts win back. Computed over all tasks in the cell, not per reachability.
    released = {
        re.sub(r"[^a-z0-9]+", "-", p.stem[len("evals_") :].lower()).strip("-"): p
        for p in sorted((Path(args.corpus) / "leaderboard_e8.10d" / "verdicts").glob("evals_*.jsonl"))
    }
    print(f"\n{'model':18} {'cond':7} {'n':>4} {'1 try':>7} {'pass@3':>7} {'curated':>8} {'recovered':>10}")
    print("-" * 66)
    for (model, cond), tasks in sorted(cells.items()):
        full = {t: r for t, r in tasks.items() if len(r) == args.repeat}
        if len(full) != len(want) or model not in released:
            continue
        cur: dict[str, bool] = {}
        for ln in Path(released[model]).read_text().splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r["task_id"] in want:
                    cur.setdefault(r["task_id"], bool(r["passed"]))
        if len(cur) != len(want):
            continue
        n = len(full)
        one = 100 * sum(sum(r.values()) for r in full.values()) / (n * args.repeat)
        at = 100 * sum(1 for r in full.values() if any(r.values())) / n
        cu = 100 * sum(cur.values()) / len(cur)
        rec = 100 * (at - one) / (cu - one) if cu > one else float("nan")
        out[f"{model}|{cond}|recovery"] = {
            "single_attempt": round(one, 1),
            f"pass_at_{args.repeat}": round(at, 1),
            "curated": round(cu, 1),
            "recovered_pct_of_deficit": round(rec, 1),
        }
        print(f"{model:18} {cond:7} {n:4d} {one:7.1f} {at:7.1f} {cu:8.1f} {rec:9.0f}%")
    print("\nrecovered = (pass@3 - 1 try) / (curated - 1 try): the share of the exposure")
    print("deficit that triple the attempt budget wins back. Low means structural, not luck.")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
