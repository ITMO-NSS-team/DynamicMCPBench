#!/usr/bin/env python3
"""E4.10: difficulty curve — agent pass-rate / SAE / pass^k vs difficulty bin (the measured
trace_depth), per candidate model. Shows the expected monotone degradation from simple
single-tool tasks to long chains of similar tools.

Usage:
  uv run python scripts/difficulty_curve.py --evals 'reports/leaderboard/eval_*.jsonl' \\
      --specs data/corpus/specs.jsonl -o reports/difficulty_curve.md
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _bin(depth: int) -> str:
    return "1-2 (simple)" if depth <= 2 else ("3-4 (medium)" if depth <= 4 else "5+ (hard)")


_ORDER = {"1-2 (simple)": 0, "3-4 (medium)": 1, "5+ (hard)": 2}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", required=True)
    ap.add_argument("--specs", required=True)
    ap.add_argument("-o", "--out", default="reports/difficulty_curve.md")
    a = ap.parse_args()

    depth_of = {
        s["task_id"]: (s.get("complexity") or {}).get("trace_depth", len(s.get("servers_used", [])))
        for s in _read(ROOT / a.specs)
    }

    cell = collections.defaultdict(lambda: {"n": 0, "pass": 0, "sae": 0})  # (model, bin)
    passk = collections.defaultdict(list)  # (model, bin, task) -> [passed]
    models: set[str] = set()
    for f in sorted(glob.glob(str(ROOT / a.evals))):
        for r in _read(f):
            d = depth_of.get(r["task_id"])
            if d is None:
                continue
            b = _bin(d)
            m = r.get("candidate_model") or "?"
            models.add(m)
            cell[(m, b)]["n"] += 1
            cell[(m, b)]["pass"] += bool(r.get("passed"))
            cell[(m, b)]["sae"] += bool(r.get("had_sae"))
            passk[(m, b, r["task_id"])].append(bool(r.get("passed")))

    pk = collections.defaultdict(lambda: [0, 0])
    for (m, b, _t), passes in passk.items():
        pk[(m, b)][1] += 1
        pk[(m, b)][0] += all(passes)

    def pct(n, d):
        return f"{100 * n / d:.0f}%" if d else "-"

    bins = sorted({b for _m, b in cell}, key=lambda b: _ORDER.get(b, 9))
    lines = ["# Difficulty curve (E4.10)", "", "Pass-rate / SAE-rate / pass^k vs trace-depth bin.", ""]
    for m in sorted(models):
        lines += [
            f"## {m}",
            "",
            "| difficulty | n | pass-rate | SAE-rate | pass^k |",
            "|---|---|---|---|---|",
        ]
        for b in bins:
            d = cell[(m, b)]
            if not d["n"]:
                continue
            pkr = pct(pk[(m, b)][0], pk[(m, b)][1])
            lines.append(f"| {b} | {d['n']} | {pct(d['pass'], d['n'])} | {pct(d['sae'], d['n'])} | {pkr} |")
        lines.append("")

    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"difficulty curve -> {outp}")
    print("bins:", bins, "models:", sorted(models))


if __name__ == "__main__":
    main()
