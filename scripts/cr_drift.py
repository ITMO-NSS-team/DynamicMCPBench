#!/usr/bin/env python3
"""Did the live servers drift between a cell's original run and its gap fill?

Several cells were not evaluated in one continuous stretch — some were lost
mid-flight to provider `APITimeoutError` and resumed hours later, others simply
paused. That is a benign accident for a static benchmark and a real question for
this one: the tasks run against *live* MCP servers, which is why `dmcp refresh`
exists at all. A cell whose tasks were executed across a 3-hour gap is exposed to
whatever changed in between, and if the tasks after the gap scored systematically
differently, every interrupted cell would be a blend of two substrates.

The script does not care why a cell paused; it finds the discontinuity in the
evaluation timestamps and asks whether it left a mark.

The naive check — compare the recovered tasks to the rest of the cell — is
confounded: the recovered tasks are exactly those on the shards that died, a
task-id-determined subset, not a random one, so they may simply be easier or
harder. The control here removes that. Every other model ran the *same* tasks
under the *same* condition without interruption, so the composition effect is
directly measurable:

    excess = (late - early) in the recovered cell
           - (late - early) averaged over uninterrupted cells of that condition

Under no drift, excess is zero. Cells are pooled because any single recovery is
far too small to resolve anything; the pooled Wilson interval is printed so the
power of the test is visible rather than assumed.

Scope of v0: a validity check, not a result. It is not pre-registered, it grades
nothing, and a null here is evidence of nothing having gone wrong — not evidence
that live-server drift is unimportant in general.

Reproduce:
    uv run python scripts/cr_drift.py
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import math
import re
from pathlib import Path

CELL_RE = re.compile(r"^(?P<model>.+?)__(?P<cond>.+?)__r(?P<repeat>\d+)\.shard\d+\.jsonl$")


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, c - h), 100 * min(1.0, c + h))


def when(rec: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(rec["evaluated_at"].replace("Z", "+00:00"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--gap-min", type=float, default=60.0, help="minutes that mark a recovery")
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_drift.json")
    args = ap.parse_args()

    want = {json.loads(ln)["task_id"] for ln in Path(args.subset).read_text().splitlines() if ln.strip()}

    # One record per task: for repeat>1 cells this keeps the first attempt, so
    # every cell is compared on the same single-attempt quantity.
    cells: dict[tuple[str, str, str], dict[str, dict]] = collections.defaultdict(dict)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m:
            continue
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r["task_id"] in want and "evaluated_at" in r:
                cells[(m["model"], m["cond"], m["repeat"])].setdefault(r["task_id"], r)

    # A cell is "recovered" if its evaluation times contain a gap wider than the
    # threshold; the tasks after the widest such gap are the recovered ones.
    split: dict[tuple[str, str, str], tuple[set[str], set[str], float]] = {}
    for key, recs in cells.items():
        ts = sorted(when(r) for r in recs.values())
        if len(ts) < 4:
            continue
        gaps = [(ts[i + 1] - ts[i]).total_seconds() / 60 for i in range(len(ts) - 1)]
        widest = max(gaps)
        if widest < args.gap_min:
            split[key] = (set(recs), set(), widest)
            continue
        cut = ts[gaps.index(widest) + 1]
        late = {t for t, r in recs.items() if when(r) >= cut}
        split[key] = (set(recs) - late, late, widest)

    def rate(key: tuple[str, str, str], tasks: set[str]) -> tuple[int, int]:
        recs = cells[key]
        sel = [recs[t]["passed"] for t in tasks if t in recs]
        return (sum(bool(x) for x in sel), len(sel))

    rows: list[dict] = []
    for key, (early, late, widest) in sorted(split.items()):
        if not late:
            continue
        model, cond, rep = key
        ke, ne = rate(key, early)
        kl, nl = rate(key, late)
        if not ne or not nl:
            continue
        observed = 100 * kl / nl - 100 * ke / ne
        # Composition control: uninterrupted cells of the same condition+repeat,
        # scored on the identical early/late task split. A control must cover all
        # 150 tasks — a partial cell overlaps the two halves unevenly, so its
        # late-minus-early would measure its own coverage, not task difficulty.
        deltas = []
        for other, (_, olate, _) in split.items():
            if other == key or olate or other[1] != cond or other[2] != rep:
                continue
            if len(cells[other]) != len(want):
                continue
            oke, one = rate(other, early)
            okl, onl = rate(other, late)
            if one and onl:
                deltas.append(100 * okl / onl - 100 * oke / one)
        expected = sum(deltas) / len(deltas) if deltas else float("nan")
        lo, hi = wilson(kl, nl)
        rows.append(
            {
                "cell": f"{model}|{cond}|r{rep}",
                "gap_min": round(widest, 0),
                "n_early": ne,
                "n_late": nl,
                "late_pass": round(100 * kl / nl, 1),
                "late_ci95": [round(lo, 1), round(hi, 1)],
                "observed_delta": round(observed, 1),
                "expected_delta_from_composition": round(expected, 1),
                "excess": round(observed - expected, 1),
                "controls": len(deltas),
            }
        )

    header = f"{'cell':34} {'gap':>5} {'n_late':>7} {'obs':>7} {'ctrl':>7} {'excess':>7} {'ctrls':>6}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['cell']:34} {r['gap_min']:5.0f} {r['n_late']:7d} "
            f"{r['observed_delta']:+7.1f} {r['expected_delta_from_composition']:+7.1f} "
            f"{r['excess']:+7.1f} {r['controls']:6d}"
        )
    if not rows:
        print("(no recovered cells found — nothing was interrupted)")

    pooled = None
    usable = [r for r in rows if r["controls"]]
    if usable:
        nl = sum(r["n_late"] for r in usable)
        excess = sum(r["excess"] * r["n_late"] for r in usable) / nl
        # Half-width of the pooled late-subset interval, as a floor on resolvable effect.
        k = sum(round(r["late_pass"] * r["n_late"] / 100) for r in usable)
        lo, hi = wilson(k, nl)
        pooled = {
            "n_late": nl,
            "excess_pooled": round(excess, 1),
            "resolvable_at_95pct": round((hi - lo) / 2, 1),
        }
        print(
            f"\npooled over {len(usable)} recovered cells: n_late={nl} "
            f"excess={excess:+.1f} pts, resolvable at 95% only above ~{(hi - lo) / 2:.0f} pts"
        )
        print("excess = recovered cell's late-minus-early, net of the same split measured")
        print("on uninterrupted cells of that condition. Zero means no detectable drift.")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps({"cells": rows, "pooled": pooled}, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
