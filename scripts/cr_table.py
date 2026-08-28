#!/usr/bin/env python3
"""Emit the e9.1 matrix as markdown, so the report's numbers are never retyped.

Every figure in `docs/experiments/e9.1-tool-exposure-matrix.md` should be
derivable from the verdict files by running a command. Hand-transcribing a 4x7
grid of rates with confidence intervals is where a wrong digit enters a paper and
survives review, so the table is generated instead.

Rates are computed over the pre-registered 150-task subset only, and a cell that
does not cover all 150 is printed with its coverage rather than a rate: a partial
cell's rate is an arbitrary prefix of the task order and comparing it to a
complete one is meaningless.

`repeat > 1` files are excluded here. They measure pass^k, a different quantity,
and averaging them into a single-attempt cell would silently inflate n.

Scope of v0: presentation. It adjudicates nothing (that is `cr_decide.py`) and
computes no new quantity.

Reproduce:
    uv run python scripts/cr_table.py
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import re
from pathlib import Path

CELL_RE = re.compile(r"^(?P<model>.+?)__(?P<cond>.+?)__r(?P<repeat>\d+)\.shard\d+\.jsonl$")
COND_ORDER = ("rag-4", "rag-8", "rag-16", "rag-32", "hier", "flat")
# The four models the matrix was registered over. Extended-panel cells sit on disk
# beside them, so the default must name the registered set explicitly — globbing
# every cell would silently widen the scope of a committed table.
REGISTERED_MODELS = ("claude-haiku-4-5", "kimi-k2-6", "minimax-m3", "qwen3-7-max")
COND_LABEL = {
    "rag-4": "`rag:4`",
    "rag-8": "`rag:8`",
    "rag-16": "`rag:16`",
    "rag-32": "`rag:32`",
    "hier": "`hier`",
    "flat": "`flat`",
}


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--corpus", default="hfdl")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_numbers.json")
    ap.add_argument(
        "--models",
        default="registered",
        help="'registered' (the four models the matrix was registered over) or 'all'.",
    )
    args = ap.parse_args()

    want = {json.loads(ln)["task_id"] for ln in Path(args.subset).read_text().splitlines() if ln.strip()}

    cells: dict[tuple[str, str], dict[str, bool]] = collections.defaultdict(dict)
    for f in sorted(glob.glob(args.evals)):
        m = CELL_RE.match(Path(f).name)
        if not m or int(m["repeat"]) != 1:
            continue
        for r in load_jsonl(f):
            if r["task_id"] in want:
                cells[(m["model"], m["cond"])].setdefault(r["task_id"], bool(r["passed"]))

    # Curated reference from the released leaderboard, restricted to the same tasks.
    released = {
        re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-"): p
        for p in sorted((Path(args.corpus) / "leaderboard_api" / "verdicts").glob("*.jsonl"))
    }
    models = sorted({m for m, _ in cells})
    if args.models == "all":
        print(f"tabulating ALL {len(models)} models — EXPLORATORY, not the registered scope\n")
    else:
        models = [m for m in models if m in REGISTERED_MODELS]
        cells = {(m, c): v for (m, c), v in cells.items() if m in REGISTERED_MODELS}
    for model in models:
        if model in released:
            d: dict[str, bool] = {}
            for r in load_jsonl(released[model]):
                if r["task_id"] in want:
                    d.setdefault(r["task_id"], bool(r["passed"]))
            cells[(model, "curated")] = d

    conds = [c for c in ("curated", *COND_ORDER) if any((m, c) in cells for m in models)]
    out: dict[str, dict] = {}

    def fmt(model: str, cond: str) -> str:
        v = cells.get((model, cond))
        if not v:
            return "—"
        n = len(v)
        k = sum(v.values())
        if n < len(want):
            return f"_{n}/{len(want)}_"
        lo, hi = wilson(k, n)
        out[f"{model}|{cond}"] = {
            "pass_pct": round(100 * k / n, 1),
            "passed": k,
            "n": n,
            "ci95": [round(lo, 1), round(hi, 1)],
        }
        return f"{100 * k / n:.1f} [{lo:.0f}–{hi:.0f}]"

    label = {"curated": "curated (`--pool target`)"}
    width = max(len(label.get(c, COND_LABEL.get(c, c))) for c in conds)
    head = f"| {'exposure'.ljust(width)} | " + " | ".join(m for m in models) + " |"
    print(head)
    print(f"|{'-' * (width + 2)}|" + "|".join("---" for _ in models) + "|")
    for cond in conds:
        row = " | ".join(fmt(m, cond) for m in models)
        print(f"| {label.get(cond, COND_LABEL.get(cond, cond)).ljust(width)} | {row} |")
    print("\nPass rate % with Wilson 95% CI, n=150 pre-registered tasks.")
    print("Italic `n/150` marks a cell still filling; `—` a cell not run.")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
