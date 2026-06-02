#!/usr/bin/env python3
"""E4.9: generation-strategy ablation + gen x eval-condition SAE heatmap.

Joins each EvaluationResult -> its TaskSpec -> the source trace (goal_tags -> generation
strategy), then reports SAE-rate / pass-rate / pass^k PER GENERATION STRATEGY, plus a 2-D
generation-strategy x eval-condition SAE matrix (eval condition = each eval file's label,
e.g. model__pool__p0.5). Answers: which generation strategy, under which eval setup, most
provokes server-attribution error.

Usage:
  uv run python scripts/strategy_ablation.py --evals 'reports/leaderboard/eval_*.jsonl' \\
      --specs data/corpus/specs.jsonl --traces data/corpus/traces.jsonl -o reports/strategy_ablation.md
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _goal_tags(trace: dict) -> list[str]:
    found: list[str] = []

    def walk(o):
        if found:
            return
        if isinstance(o, dict):
            gt = o.get("goal_tags")
            if isinstance(gt, list):
                found.extend(str(x) for x in gt)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(trace)
    return found


def _strategy(tags: list[str]) -> str:
    return next((t.split(":", 1)[1] for t in tags if t.startswith("strategy:")), "?")


def _read(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", required=True, help="glob of EvaluationResult jsonl files")
    ap.add_argument("--specs", required=True)
    ap.add_argument("--traces", required=True)
    ap.add_argument("-o", "--out", default="reports/strategy_ablation.md")
    ap.add_argument(
        "--json", default=None, help="also emit machine-readable numbers JSON (paper renderer input)"
    )
    a = ap.parse_args()

    specs = {s["task_id"]: s for s in _read(ROOT / a.specs)}
    tags_for_trace = {t.get("trace_id"): _goal_tags(t) for t in _read(ROOT / a.traces)}

    def strat_of(task_id: str) -> str:
        sp = specs.get(task_id)
        return _strategy(tags_for_trace.get(sp.get("source_trace_id"), [])) if sp else "?"

    by_strat = collections.defaultdict(lambda: {"n": 0, "pass": 0, "sae": 0})
    matrix = collections.defaultdict(lambda: {"n": 0, "sae": 0})  # (strategy, condition) -> SAE
    passk = collections.defaultdict(list)  # (strategy, model, cond, task) -> [passed,...]
    conditions: set[str] = set()

    for f in sorted(glob.glob(str(ROOT / a.evals))):
        cond = Path(f).stem.replace("eval_", "")
        conditions.add(cond)
        for r in _read(f):
            st = strat_of(r["task_id"])
            sae = bool(r.get("had_sae"))
            by_strat[st]["n"] += 1
            by_strat[st]["pass"] += bool(r.get("passed"))
            by_strat[st]["sae"] += sae
            matrix[(st, cond)]["n"] += 1
            matrix[(st, cond)]["sae"] += sae
            passk[(st, r.get("candidate_model"), cond, r["task_id"])].append(bool(r.get("passed")))

    pk = collections.defaultdict(lambda: [0, 0])  # strategy -> [all-pass groups, total groups]
    for (st, _m, _c, _t), passes in passk.items():
        pk[st][1] += 1
        pk[st][0] += all(passes)

    def pct(num, den):
        return f"{100 * num / den:.0f}%" if den else "-"

    lines = ["# Generation-strategy ablation (E4.9)", ""]
    lines += [
        "## Per generation strategy",
        "",
        "| strategy | n | pass-rate | SAE-rate | pass^k |",
        "|---|---|---|---|---|",
    ]
    for st, d in sorted(by_strat.items(), key=lambda kv: -kv[1]["sae"]):
        passk_rate = pct(pk[st][0], pk[st][1])
        lines.append(
            f"| {st} | {d['n']} | {pct(d['pass'], d['n'])} | {pct(d['sae'], d['n'])} | {passk_rate} |"
        )

    conds = sorted(conditions)
    lines += [
        "",
        "## SAE-rate: generation strategy x eval condition",
        "",
        "| strategy \\ condition | " + " | ".join(conds) + " |",
        "|" + "---|" * (len(conds) + 1),
    ]
    for st in sorted({s for s, _ in matrix}):
        cells = [pct(matrix[(st, c)]["sae"], matrix[(st, c)]["n"]) for c in conds]
        lines.append(f"| {st} | " + " | ".join(cells) + " |")

    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"strategy ablation -> {outp}")
    print("strategies:", {s: d["n"] for s, d in by_strat.items()})

    if a.json:
        ratio = lambda n, d: n / d if d else None  # noqa: E731
        numbers = {
            "strategies": [
                {
                    "strategy": st,
                    "n": d["n"],
                    "pass_rate": ratio(d["pass"], d["n"]),
                    "sae_rate": ratio(d["sae"], d["n"]),
                    "pass_k": ratio(pk[st][0], pk[st][1]),
                }
                for st, d in sorted(by_strat.items(), key=lambda kv: -kv[1]["sae"])
            ],
            "conditions": conds,
            "matrix": [
                {"strategy": st, "condition": c, "n": v["n"], "sae_rate": ratio(v["sae"], v["n"])}
                for (st, c), v in sorted(matrix.items())
            ],
        }
        jp = ROOT / a.json
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8")
        print(f"numbers -> {jp}")


if __name__ == "__main__":
    main()
