#!/usr/bin/env python3
"""Apply the pre-registered decision rules of e9.1 to the measured cells.

The rules in `docs/experiments/e9.1-tool-exposure-matrix.md` were registered
before any cell was run. Applying them by eye invites the exact bias
pre-registration exists to prevent, so they are evaluated here mechanically:
this script reads the verdict files and prints positive / neutral / negative per
hypothesis, with the quantity each verdict turned on.

Where a rule says "pooled", pooling is over runs, not over per-cell percentages:
counts are summed and the rate recomputed, so a short cell cannot weigh as much
as a complete one. H1's rule names no pooling axis, so it is reported per model
*and* pooled, and disagreement between the two is itself reported.

Scope of v0: adjudication only. It runs nothing, calls no model, and must not be
edited to change a threshold after seeing data — that would void the registration.

Reproduce:
    uv run python scripts/cr_decide.py --evals 'evals/cr/*.jsonl' --corpus hfdl
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
    return (100 * max(0.0, c - h), 100 * min(1.0, c + h))


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def verdict(pos: bool, neg: bool) -> str:
    return "POSITIVE" if pos else ("NEGATIVE" if neg else "NEUTRAL")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--corpus", default="hfdl")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="adjudicate cells that are still filling (their verdicts are not registrable)",
    )
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

    released = {
        re.sub(r"[^a-z0-9]+", "-", p.stem[len("evals_") :].lower()).strip("-"): p
        for p in sorted((corpus / "leaderboard_e8.10d" / "verdicts").glob("evals_*.jsonl"))
    }
    base_cache: dict[str, dict[str, list[bool]]] = {}

    def baseline(model: str) -> dict[str, list[bool]]:
        if model not in base_cache:
            d: dict[str, list[bool]] = collections.defaultdict(list)
            if model in released:
                for r in load_jsonl(released[model]):
                    d[r["task_id"]].append(bool(r["passed"]))
            base_cache[model] = d
        return base_cache[model]

    # (model, cond) -> task_id -> first-attempt verdict
    cells: dict[tuple[str, str], dict[str, bool]] = collections.defaultdict(dict)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m or int(m["repeat"]) != 1:
            continue
        for r in load_jsonl(f):
            cells[(m["model"], m["cond"])].setdefault(r["task_id"], bool(r["passed"]))
    if not cells:
        raise SystemExit(f"no cells matched {args.evals}")

    # A cell still filling has a rate drawn from an arbitrary prefix of its tasks;
    # adjudicating it produces a verdict that changes as the run proceeds, which is
    # exactly what a pre-registered rule must not do. Drop such cells by default.
    expected = {json.loads(ln)["task_id"] for ln in Path(args.subset).read_text().splitlines() if ln.strip()}
    short = {k: len(set(v) & expected) for k, v in cells.items() if len(set(v) & expected) < len(expected)}
    if short:
        state = "ADJUDICATED ANYWAY" if args.allow_incomplete else "EXCLUDED"
        print(f"incomplete cells ({len(short)}) — {state}:")
        for (model, cond), have in sorted(short.items()):
            print(f"  {model:22} {cond:8} {have}/{len(expected)}")
        print()
        if not args.allow_incomplete:
            for key in short:
                del cells[key]

    def tally(model: str, cond: str, scope: str = "all") -> tuple[int, int, int]:
        """(open_passes, curated_passes, n) over tasks with a matched baseline."""
        base = baseline(model)
        ids = [t for t in cells[(model, cond)] if t in base and (scope == "all" or bucket(t) == scope)]
        o = sum(cells[(model, cond)][t] for t in ids)
        c = sum(base[t][0] for t in ids)
        return o, c, len(ids)

    models = sorted({m for m, _ in cells})
    print("=" * 78)
    print("e9.1 — pre-registered decision rules applied mechanically")
    print("=" * 78)

    # ---- H1: monotone in k, no recovery -------------------------------------
    print("\nH1 (retrieval budget): k=32 beats k=4 by >=10 pts, non-overlapping CIs,")
    print("    AND k=32 stays >=10 pts below curated. Negative if within 5 pts of curated.")
    h1_rows = []
    for model in models:
        if (model, "rag-4") not in cells or (model, "rag-32") not in cells:
            continue
        o4, _, n4 = tally(model, "rag-4")
        o32, c32, n32 = tally(model, "rag-32")
        if not (n4 and n32):
            continue
        p4, p32, pc = 100 * o4 / n4, 100 * o32 / n32, 100 * c32 / n32
        lo4, hi4 = wilson(o4, n4)
        lo32, hi32 = wilson(o32, n32)
        rise, deficit = p32 - p4, pc - p32
        disjoint = lo32 > hi4
        v = verdict(rise >= 10 and disjoint and deficit >= 10, deficit <= 5)
        h1_rows.append((model, rise, disjoint, deficit, v))
        print(
            f"  {model:22} k4={p4:5.1f} k32={p32:5.1f} rise={rise:+5.1f} "
            f"CIs_disjoint={str(disjoint):5} deficit_vs_curated={deficit:5.1f} -> {v}"
        )
    if h1_rows:
        o4 = sum(tally(m, "rag-4")[0] for m, *_ in h1_rows)
        n4 = sum(tally(m, "rag-4")[2] for m, *_ in h1_rows)
        o32 = sum(tally(m, "rag-32")[0] for m, *_ in h1_rows)
        c32 = sum(tally(m, "rag-32")[1] for m, *_ in h1_rows)
        n32 = sum(tally(m, "rag-32")[2] for m, *_ in h1_rows)
        p4, p32, pc = 100 * o4 / n4, 100 * o32 / n32, 100 * c32 / n32
        disjoint = wilson(o32, n32)[0] > wilson(o4, n4)[1]
        rise, deficit = p32 - p4, pc - p32
        v = verdict(rise >= 10 and disjoint and deficit >= 10, deficit <= 5)
        print(
            f"  {'POOLED':22} k4={p4:5.1f} k32={p32:5.1f} rise={rise:+5.1f} "
            f"CIs_disjoint={str(disjoint):5} deficit_vs_curated={deficit:5.1f} -> {v}"
        )
        per = {r[-1] for r in h1_rows}
        if len(per) > 1 or v not in per:
            print(f"  NOTE: per-model verdicts {sorted(per)} vs pooled {v} — rule names no pooling axis.")

    # ---- H2: gap concentrated in long chains --------------------------------
    print("\nH2 (depth): pooled over k, long-bucket gap exceeds short-bucket gap by >=15 pts.")
    print("    Negative if the short gap is larger.")
    gaps = {}
    for scope in (BUCKETS[0], BUCKETS[2]):
        o = c = n = 0
        for model, cond in cells:
            if not cond.startswith("rag-"):
                continue
            a, b, m_ = tally(model, cond, scope)
            o += a
            c += b
            n += m_
        gaps[scope] = (100 * (c - o) / n) if n else float("nan")
        print(
            f"    {scope:14} n={n:4d}  open={100 * o / max(n, 1):5.1f}  "
            f"curated={100 * c / max(n, 1):5.1f}  gap={gaps[scope]:5.1f}"
        )
    spread = gaps[BUCKETS[2]] - gaps[BUCKETS[0]]
    print(f"  long_gap - short_gap = {spread:+.1f} -> {verdict(spread >= 15, spread < 0)}")

    # ---- H3: hierarchical router vs flat top-k ------------------------------
    print("\nH3 (architecture): hier beats rag:8 by >=5 pts pooled over models, non-overlapping CIs.")
    oh = nh = o8 = n8 = 0
    for model in models:
        if (model, "hier") in cells and (model, "rag-8") in cells:
            a, _, m_ = tally(model, "hier")
            oh += a
            nh += m_
            a, _, m_ = tally(model, "rag-8")
            o8 += a
            n8 += m_
    if nh and n8:
        ph, p8 = 100 * oh / nh, 100 * o8 / n8
        loh, _ = wilson(oh, nh)
        _, hi8 = wilson(o8, n8)
        disjoint = loh > hi8
        margin = ph - p8
        print(f"  hier={ph:5.1f} (n={nh}) CI_lo={loh:5.1f}   rag8={p8:5.1f} (n={n8}) CI_hi={hi8:5.1f}")
        v3 = verdict(margin >= 5 and disjoint, -margin >= 5)
        print(f"  margin={margin:+.1f}  CIs_disjoint={disjoint} -> {v3}")
        if margin >= 5 and not disjoint:
            print("  NOTE: margin clears the threshold but the intervals touch — rule requires both.")

    # ---- H4: model ordering preserved ---------------------------------------
    print("\nH4 (model ordering): Spearman rho between curated and open orderings >=0.8.")
    for cond in sorted({c for _, c in cells}):
        entries = []
        for model in models:
            if (model, cond) not in cells:
                continue
            o, c, n = tally(model, cond)
            if n:
                entries.append((100 * o / n, 100 * c / n))
        if len(entries) < 3:
            print(f"  {cond:8} n_models={len(entries)} — not reported (rule needs >=3)")
            continue
        a = [e[0] for e in entries]
        b = [e[1] for e in entries]

        def rank(xs: list[float]) -> list[float]:
            order = sorted(range(len(xs)), key=lambda i: xs[i])
            out = [0.0] * len(xs)
            for pos, i in enumerate(order):
                out[i] = pos + 1
            return out

        ra, rb = rank(a), rank(b)
        n = len(a)
        ma, mb = sum(ra) / n, sum(rb) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
        den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
        rho = num / den if den else float("nan")
        print(f"  {cond:8} n_models={n}  rho={rho:+.3f} -> {verdict(rho >= 0.8, rho < 0.5)}")


if __name__ == "__main__":
    main()
