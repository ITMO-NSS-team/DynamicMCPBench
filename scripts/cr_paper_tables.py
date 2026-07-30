#!/usr/bin/env python3
"""Regenerate the camera-ready paper tables from committed numbers JSONs.

The camera-ready adds tables that were previously only reachable by reading an
experiment report and retyping a grid. Retyping is where a wrong digit enters a
paper and survives review, so the tables are generated:

    Generation funnel                -> docs/experiments/e9.2_numbers.json
    Human validation contingency     -> docs/experiments/e4.6_numbers.json
    Open-universe tool exposure      -> docs/experiments/data/e9.1_numbers.json
    Leave-own-family-out leaderboard -> docs/experiments/e9.3_numbers.json
    Benchmark decay per domain       -> docs/experiments/e9.3_numbers.json

`--check` re-emits every table and asserts that each numeric row appears in the
paper section that carries it, so a JSON that moves without the paper moving
(or the reverse) fails loudly instead of drifting.

The two E9.3 tables are derived rather than transcribed: the leave-own-family-out
ordering, its rank movements and its Spearman correlation are computed from the
headline and other-family columns, and the pooled decay row is recomputed by
call-weighting the per-server rows. Both are checked against the values the paper
claims, so a claim that stops following from the rows fails here.

Scope of v0: presentation and a consistency check. It adjudicates nothing and
introduces no measurement; every input figure it reads is already committed.

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
E9_3 = ROOT / "docs/experiments/e9.3_numbers.json"
APPENDIX = ROOT / "paper/sections/appendix.tex"
RESULTS = ROOT / "paper/sections/results.tex"

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


def _competition_ranks(scores: list[float]) -> list[int]:
    """1-based rank, best first; ties share the lower rank (1, 2, 2, 4)."""
    order = sorted(scores, reverse=True)
    return [order.index(s) + 1 for s in scores]


def _average_ranks(scores: list[float]) -> list[float]:
    """1-based rank, best first; ties share the mean of the ranks they span."""
    order = sorted(scores, reverse=True)
    return [(order.index(s) + 1 + len(order) - order[::-1].index(s)) / 2 for s in scores]


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman's rho via Pearson on average ranks (tie-correct)."""
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / (vx * vy) ** 0.5


def lofo_rows() -> list[str]:
    """Leaderboard reordered by leave-own-family-out score, with rank movement.

    Also asserts the two claims the paper makes about this table: the Spearman
    correlation with the headline ordering, and which pairs actually swap.
    """
    block = json.loads(E9_3.read_text())["lofo"]
    models = block["models"]
    head_rank = _competition_ranks([m["headline"] for m in models])
    lofo_rank = _competition_ranks([m["lofo"] for m in models])

    rho = _spearman([m["headline"] for m in models], [m["lofo"] for m in models])
    want_rho = block["expected"]["spearman"]
    assert round(rho, 3) == want_rho, f"Spearman {rho:.4f} != claimed {want_rho}"

    ranked = list(zip(models, head_rank, lofo_rank, strict=True))
    moved = {m["model"] for m, before, after in ranked if before != after}
    want_moved = {name for pair in block["expected"]["swapped_pairs"] for name in pair}
    assert moved == want_moved, f"rank movement {sorted(moved)} != claimed {sorted(want_moved)}"

    rows = []
    for m, before, after in sorted(ranked, key=lambda t: -t[0]["lofo"]):
        rank = str(after) if before == after else rf"${before} \to {after}$"
        star = "" if m["family_authored"] else r"$^{\dagger}$"
        rows.append(rf"{m['model']}{star} & {m['headline']:.1f} & {m['lofo']:.1f} & {rank} \\")
    return rows


def decay_rows() -> list[str]:
    """Per-server decay plus a pooled row recomputed by call-weighting the rows."""
    block = json.loads(E9_3.read_text())["decay"]
    rows = [
        rf"{r['server']} & {r['calls']} & {r['identical']}\% & {r['drifted']}\% & {r['broken']}\% \\"
        for r in block["rows"]
    ]
    calls = sum(r["calls"] for r in block["rows"])
    pooled = {
        k: round(sum(r["calls"] * r[k] for r in block["rows"]) / calls)
        for k in ("identical", "drifted", "broken")
    }
    want = block["pooled_expected"]
    assert {"calls": calls, **pooled} == want, f"pooled {calls, pooled} != claimed {want}"
    rows.append(
        rf"all & {calls} & \textbf{{{pooled['identical']}\%}} & "
        rf"{pooled['drifted']}\% & {pooled['broken']}\% \\"
    )
    return rows


TABLES = {
    "Generation funnel": (funnel_rows, APPENDIX),
    "Human validation contingency": (confusion_rows, APPENDIX),
    "Open-universe tool exposure": (exposure_rows, APPENDIX),
    "Leave-own-family-out leaderboard": (lofo_rows, RESULTS),
    "Benchmark decay per domain": (decay_rows, RESULTS),
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="assert every generated row appears in the paper section that carries it",
    )
    args = ap.parse_args()

    if not args.check:
        for title, (fn, target) in TABLES.items():
            print(f"% {title} -> {target.name}")
            for row in fn():
                print(f"    {row}")
            print()
        return 0

    sources = {p: _normalize(p.read_text()) for p in {t for _, t in TABLES.values()}}
    missing: list[tuple[str, str, str]] = []
    for title, (fn, target) in TABLES.items():
        for row in fn():
            if _normalize(row) not in sources[target]:
                missing.append((title, target.name, row))

    if missing:
        print(f"MISMATCH: {len(missing)} generated row(s) absent from the paper", file=sys.stderr)
        for title, name, row in missing:
            print(f"  [{title} -> {name}] {row}", file=sys.stderr)
        return 1

    total = sum(len(fn()) for fn, _ in TABLES.values())
    names = ", ".join(sorted(p.name for p in sources))
    print(f"OK: {total} generated rows across {len(TABLES)} tables match {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
