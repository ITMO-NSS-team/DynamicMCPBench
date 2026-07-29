#!/usr/bin/env python3
"""Measure how much model-discriminating signal each exposure condition retains.

H4 asks whether the *ordering* of models survives open exposure. Rank correlation
is blind to how far apart the models are, so a condition can preserve the
leaderboard perfectly while compressing the field into noise — H4 can pass on
exactly the condition where the benchmark stops telling models apart. This script
measures the quantity H4 does not: the spread.

Three views, all over the same pre-registered 150 tasks:

  spread    — max minus min pass rate across models. How much room the condition
              leaves between the best and worst candidate.
  top_margin— best model minus second best. Whether the leader is still visibly
              the leader.
  loss      — curated minus open, per model, ranked against curated skill. If
              loss rises with capability, the condition is *regressive*: it takes
              more from stronger models, because the ceiling it imposes is shared
              (see cr_recall.py — reachability is identical across candidates).

Only cells covering all 150 tasks are used; a partial cell's rate is an arbitrary
prefix of the task order.

Scope of v0: descriptive. It adjudicates nothing and is explicitly *not*
pre-registered — it was written after seeing H4's verdicts, and any report using
it must say so.

Reproduce:
    uv run python scripts/cr_spread.py
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
# The four models the matrix was registered over. Later cells (the extended panel)
# sit on disk beside them, so the default must name the registered set explicitly —
# globbing every cell would silently widen the scope of a committed table.
REGISTERED_MODELS = ("claude-haiku-4-5", "kimi-k2-6", "minimax-m3", "qwen3-7-max")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def spearman(a: list[float], b: list[float]) -> float:
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
    return num / den if den else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", default="evals/cr/*.jsonl")
    ap.add_argument("--corpus", default="hfdl")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_spread.json")
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

    released = {
        re.sub(r"[^a-z0-9]+", "-", p.stem[len("evals_") :].lower()).strip("-"): p
        for p in sorted((Path(args.corpus) / "leaderboard_e8.10d" / "verdicts").glob("evals_*.jsonl"))
    }
    models = sorted({m for m, _ in cells})
    if args.models == "all":
        print(f"spread over ALL {len(models)} models — EXPLORATORY, not the registered scope\n")
    else:
        models = [m for m in models if m in REGISTERED_MODELS]
    curated: dict[str, float] = {}
    for model in models:
        if model not in released:
            continue
        d: dict[str, bool] = {}
        for r in load_jsonl(released[model]):
            if r["task_id"] in want:
                d.setdefault(r["task_id"], bool(r["passed"]))
        if len(d) == len(want):
            curated[model] = 100 * sum(d.values()) / len(d)

    def rate(model: str, cond: str) -> float | None:
        v = cells.get((model, cond))
        return 100 * sum(v.values()) / len(v) if v and len(v) == len(want) else None

    def describe(d: dict[str, float]) -> tuple[float, float]:
        v = sorted(d.values(), reverse=True)
        return (v[0] - v[-1], v[0] - v[1] if len(v) > 1 else float("nan"))

    out: dict[str, dict] = {}
    cur_spread, cur_margin = describe(curated) if len(curated) > 1 else (float("nan"),) * 2
    print(
        f"curated reference over all {len(curated)} models: "
        f"spread={cur_spread:.1f} top_margin={cur_margin:.1f}"
    )
    print(
        f"\n{'condition':10} {'n':>2} {'spread':>7} {'cur_sub':>8} {'retained':>9} "
        f"{'top_margin':>11} {'rho(skill,loss)':>16}"
    )
    for cond in COND_ORDER:
        d = {m: r for m in models if (r := rate(m, cond)) is not None and m in curated}
        if len(d) < 2:
            continue
        spread, margin = describe(d)
        ms = sorted(d)
        rho = spearman([curated[m] for m in ms], [curated[m] - d[m] for m in ms])
        # The curated reference must cover the SAME models as the condition. A cell
        # missing the strongest candidate has a mechanically smaller spread, and
        # dividing it by the all-model curated spread would report that absence as
        # lost discriminative power.
        sub_spread, sub_margin = describe({m: curated[m] for m in ms})
        retained = 100 * spread / sub_spread if sub_spread else float("nan")
        out[cond] = {
            "models": len(d),
            "model_ids": ms,
            "spread": round(spread, 1),
            "curated_spread_same_models": round(sub_spread, 1),
            "retained_pct_of_curated_spread": round(retained, 1),
            "top_margin": round(margin, 1),
            "curated_top_margin_same_models": round(sub_margin, 1),
            "rho_skill_vs_loss": round(rho, 3),
            "loss": {m: round(curated[m] - d[m], 1) for m in ms},
        }
        print(
            f"{cond:10} {len(d):2d} {spread:7.1f} {sub_spread:8.1f} "
            f"{retained:8.0f}% {margin:11.1f} {rho:16.3f}"
        )
    print(
        f"\n{'curated':10} {len(curated):2d} {cur_spread:7.1f} {cur_spread:8.1f} "
        f"{100:8.0f}% {cur_margin:11.1f}"
    )
    print("\ncur_sub = curated spread over exactly the models present in that row;")
    print("retained divides by it, so a row missing a model is not penalised for the absence.")
    print("\nrho(skill,loss) = Spearman between curated pass rate and curated-minus-open loss.")
    print("+1.0 means the condition is perfectly regressive: it costs stronger models more.")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(
                {"curated": {"spread": round(cur_spread, 1), "top_margin": round(cur_margin, 1)}, **out},
                indent=2,
            )
        )
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
