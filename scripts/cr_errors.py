#!/usr/bin/env python3
"""Split e9.1 failures by reachability to read the mechanism off the error codes.

`scripts/cr_recall.py` establishes *whether* a task's required tools were on
screen; the matrix establishes *whether* the agent passed. Crossing the two over
failures only asks a sharper question: when an agent fails, does the error
taxonomy know why?

It does, and the two mechanisms of the decomposition separate cleanly:

  E6 tool_blindness      — the retrieval signature. High when the tool was absent.
  E7 argument_hallucination — the selection signature. Rises when it was present.
  E3 incomplete_aggregation — exposure-invariant; a property of the tasks.

The `flat` row is the load-bearing one: every task there is reachable by
construction (`--pool full`), so its elevated E6 cannot be a retrieval miss. That
residual is distraction, expressed as blindness in the presence of the tool.

Only failures are tabulated. Successes have few errors by construction and mixing
them in would confound "which errors does exposure cause" with "how often does
exposure let the agent finish".

Scope of v0: read-only aggregation over existing verdict files and the recall
map. It grades nothing, calls no model, and adds no compute cost.

Reproduce:
    uv run python scripts/cr_recall.py --corpus hfdl --k 4,8,16,32   # writes the map
    uv run python scripts/cr_errors.py
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
from pathlib import Path

CELL_RE = re.compile(r"^(?P<model>.+?)__(?P<cond>.+?)__r1\.shard\d+\.jsonl$")
CODES = ("E3", "E4", "E6", "E7")
# `flat` exposes the whole pool, which under --pool full always contains the
# required tools, so it has no unreachable half to split off.
COND_K = {"rag-4": "4", "rag-8": "8", "rag-16": "16", "rag-32": "32"}


def check_map(evals: str, reach: dict) -> dict:
    """Validate the split predicate before splitting anything by it.

    The map is replayed offline and the live run embeds its own text, so the two
    can disagree at the top-k boundary. Only one direction is a contradiction:
    an unreachable task cannot pass, because some tool_effect checkpoint has no
    callable member. Reachable-and-failed is ordinary. So counting passes on the
    unreachable side measures the map's false-negative rate directly.
    """
    tot: collections.Counter = collections.Counter()
    bad: collections.Counter = collections.Counter()
    offenders: dict[str, set[str]] = collections.defaultdict(set)
    for f in sorted(glob.glob(evals)):
        m = re.match(r"^(?P<model>.+?)__(?P<cond>.+?)__r\d+\.shard\d+\.jsonl$", Path(f).name)
        if not m or m["cond"] not in COND_K:
            continue
        k = COND_K[m["cond"]]
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            t = str(r["task_id"])
            if t not in reach[k] or reach[k][t]:
                continue
            tot[k] += 1
            if r["passed"]:
                bad[k] += 1
                offenders[k].add(t)
    n, b = sum(tot.values()), sum(bad.values())
    print(f"map check — attempts on tasks the map calls unreachable: {n}, of which passed: {b}")
    for k in sorted(tot, key=int):
        if bad[k]:
            print(f"  k={k}: {bad[k]}/{tot[k]} — tasks {sorted(offenders[k])}")
    print(f"  false-negative rate {100 * b / n if n else 0:.2f}% — the split below inherits this.\n")
    return {
        "attempts_on_unreachable": n,
        "passed_anyway": b,
        "false_negative_pct": round(100 * b / n, 3) if n else 0.0,
        "offending_tasks": {k: sorted(v) for k, v in offenders.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--recall", default="evals/cr/recall_per_task.json")
    ap.add_argument("--conditions", default="rag-8,rag-32,flat")
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_errors.json")
    args = ap.parse_args()

    reach = json.loads(Path(args.recall).read_text())
    want = args.conditions.split(",")
    map_check = check_map(args.evals, reach)

    # (model, cond, reachable) -> [(calls, ok_calls, taxonomy_counts)] over failures
    rows: dict[tuple[str, str, bool], list[tuple[int, int, dict]]] = collections.defaultdict(list)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m or m["cond"] not in want:
            continue
        k = COND_K.get(m["cond"])
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r["passed"]:
                continue
            s = r.get("summary", {})
            counts = (s.get("error_taxonomy") or {}).get("counts", {}) or {}
            ok = reach[k][str(r["task_id"])] if k else True
            rows[(m["model"], m["cond"], ok)].append(
                (s.get("agent_call_count", 0), s.get("agent_call_success_count", 0), counts)
            )

    out: dict[str, dict] = {}
    header = f"{'model':18} {'cond':7} {'reach':>6} {'n':>4} {'calls':>6} {'ok':>5}  " + "  ".join(
        f"{c:>4}" for c in CODES
    )
    print(header)
    print("-" * len(header))
    for (model, cond, ok), v in sorted(rows.items()):
        n = len(v)
        per = {c: sum(t.get(c, 0) for _, _, t in v) / n for c in CODES}
        out[f"{model}|{cond}|{'reachable' if ok else 'unreachable'}"] = {
            "failures": n,
            "calls_mean": round(sum(a for a, _, _ in v) / n, 2),
            "calls_ok_mean": round(sum(b for _, b, _ in v) / n, 2),
            **{c: round(per[c], 3) for c in CODES},
        }
        print(
            f"{model:18} {cond:7} {'yes' if ok else 'NO':>6} {n:4d} "
            f"{sum(a for a, _, _ in v) / n:6.1f} {sum(b for _, b, _ in v) / n:5.1f}  "
            + "  ".join(f"{per[c]:4.2f}" for c in CODES)
        )

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps({"map_check": map_check, **out}, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
