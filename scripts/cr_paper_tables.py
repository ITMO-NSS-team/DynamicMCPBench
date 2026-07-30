#!/usr/bin/env python3
"""Regenerate the three camera-ready appendix tables from committed numbers JSONs.

The camera-ready adds three appendix sections whose tables were previously only
reachable by reading an experiment report and retyping a grid. Retyping is where
a wrong digit enters a paper and survives review, so the tables are generated:

    Generation funnel                -> docs/experiments/e9.2_numbers.json
    Human validation contingency     -> docs/experiments/e4.6_numbers.json
    Open-universe tool exposure      -> docs/experiments/data/e9.1_numbers.json

`--check` re-emits every table and asserts that each numeric row appears in
`paper/sections/appendix.tex`, so a JSON that moves without the paper moving
(or the reverse) fails loudly instead of drifting.

Scope of v0: presentation and a consistency check. It computes no new quantity
and adjudicates nothing; every figure it prints is already committed.

Reproduce:
    uv run python scripts/cr_paper_tables.py            # print the LaTeX
    uv run python scripts/cr_paper_tables.py --check    # verify against the paper
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E9_2 = ROOT / "docs/experiments/e9.2_numbers.json"
E4_6 = ROOT / "docs/experiments/e4.6_numbers.json"
E9_1 = ROOT / "docs/experiments/data/e9.1_numbers.json"
PAPER = ROOT / "paper/sections/appendix.tex"

MODELS = ("claude-haiku-4-5", "kimi-k2-6", "minimax-m3", "qwen3-7-max")
CONDITIONS = (
    ("curated", r"curated (\(\approx\)8 tools)"),
    ("rag-4", r"\texttt{rag:4}"),
    ("rag-8", r"\texttt{rag:8}"),
    ("rag-16", r"\texttt{rag:16}"),
    ("rag-32", r"\texttt{rag:32}"),
    ("hier", r"\texttt{hier}"),
    ("flat", r"\texttt{flat} (1{,}168)"),
)


def _thousands(n: int) -> str:
    """LaTeX-safe thousands separator matching the paper's convention."""
    return f"{n:,}".replace(",", "{,}")


def funnel_rows() -> list[str]:
    f = json.loads(E9_2.read_text())["funnel"]
    goals = f["goals_issued"]
    traces = f["traces_recorded"]
    specs = f["specs_parsed"]
    valid = f["validator_valid"]
    return [
        rf"Goals issued              & {_thousands(goals)}   & --- \\",
        rf"Trajectories recorded     & {_thousands(traces)} & incl.\ retries \\",
        rf"Specifications parsed     & {_thousands(specs)}   & {100 * specs / traces:.1f}\% \\",
        rf"Validator-valid           & {_thousands(valid)}   & {100 * valid / specs:.1f}\% \\",
    ]


def confusion_rows() -> list[str]:
    s = json.loads(E4_6.read_text())["scorer_vs_human"]
    auto_pass, auto_fail = s["fp_d"], s["fn_d"]
    pass_fail, fail_pass = s["fp_n"], s["fn_n"]
    pass_pass = auto_pass - pass_fail
    fail_fail = auto_fail - fail_pass
    return [
        rf"automatic pass & {pass_pass} & {pass_fail}  & {auto_pass} \\",
        rf"automatic fail & {fail_pass} & {fail_fail} & {auto_fail} \\",
        rf"total          & {pass_pass + fail_pass} & {pass_fail + fail_fail} "
        rf"& {auto_pass + auto_fail} \\",
    ]


def exposure_rows() -> list[str]:
    m = json.loads(E9_1.read_text())
    rows = []
    for cond, label in CONDITIONS:
        cells = []
        for model in MODELS:
            v = m.get(f"{model}|{cond}")
            cells.append(f"{v['pass_pct']:.1f}" if v else "---")
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    return rows


TABLES = {
    "Generation funnel": funnel_rows,
    "Human validation contingency": confusion_rows,
    "Open-universe tool exposure": exposure_rows,
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="assert every generated row appears in paper/sections/appendix.tex",
    )
    args = ap.parse_args()

    if not args.check:
        for title, fn in TABLES.items():
            print(f"% {title}")
            for row in fn():
                print(f"    {row}")
            print()
        return 0

    paper = _normalize(PAPER.read_text())
    missing: list[tuple[str, str]] = []
    for title, fn in TABLES.items():
        for row in fn():
            if _normalize(row) not in paper:
                missing.append((title, row))

    if missing:
        print(f"MISMATCH: {len(missing)} generated row(s) absent from {PAPER.name}", file=sys.stderr)
        for title, row in missing:
            print(f"  [{title}] {row}", file=sys.stderr)
        return 1

    total = sum(len(fn()) for fn in TABLES.values())
    print(f"OK: {total} generated rows across {len(TABLES)} tables match {PAPER.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
