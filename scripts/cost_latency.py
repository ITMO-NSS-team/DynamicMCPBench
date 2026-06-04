#!/usr/bin/env python3
"""E8.1 / B1: cost-vs-accuracy Pareto + $/correct + latency from EvaluationResult JSONLs.

Aggregator over `evals/*.jsonl` (each line an `EvaluationResult` carrying
`summary.cost = {prompt_tokens, completion_tokens, cost_usd, wall_ms_total,
latencies_ms, unknown_price}` injected by `dmcp/evaluator.py`). Groups by
`candidate_model`, computes accuracy + total $ + $/correct + p50/p95 latency,
and emits a markdown report + a JSON suitable for `paper/regenerate.py`.

Pure post-hoc analysis — runs locally, no LLM calls, no network. Smoke it
with `--evals tests/data/cost_latency_fixture.jsonl --json -` (`-` to stdout).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def _iter_eval_rows(paths: list[Path]):
    for p in paths:
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def aggregate(paths: list[Path]) -> dict[str, Any]:
    """One row per `candidate_model`; sorted by `cost_per_correct` ascending."""
    per_model: dict[str, dict[str, Any]] = {}
    for row in _iter_eval_rows(paths):
        model = row.get("candidate_model") or "(unknown)"
        passed = bool(row.get("passed"))
        summary = row.get("summary") or {}
        cost_info = summary.get("cost") or {}
        m = per_model.setdefault(
            model,
            {
                "model": model,
                "runs": 0,
                "passed": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
                "wall_ms_total": 0.0,
                "latencies_ms": [],
                "unknown_price": False,
            },
        )
        m["runs"] += 1
        m["passed"] += int(passed)
        m["prompt_tokens"] += int(cost_info.get("prompt_tokens") or 0)
        m["completion_tokens"] += int(cost_info.get("completion_tokens") or 0)
        m["cost_usd"] += float(cost_info.get("cost_usd") or 0.0)
        m["wall_ms_total"] += float(cost_info.get("wall_ms_total") or 0.0)
        m["latencies_ms"].extend(float(x) for x in (cost_info.get("latencies_ms") or []))
        if cost_info.get("unknown_price"):
            m["unknown_price"] = True

    rows: list[dict[str, Any]] = []
    for m in per_model.values():
        runs = m["runs"]
        passed = m["passed"]
        accuracy = (passed / runs) if runs else 0.0
        cost = round(float(m["cost_usd"]), 6)
        rows.append(
            {
                "model": m["model"],
                "runs": runs,
                "passed": passed,
                "accuracy": round(accuracy, 4),
                "cost_usd": cost,
                "cost_per_correct_usd": round(cost / passed, 6) if passed else None,
                "prompt_tokens": m["prompt_tokens"],
                "completion_tokens": m["completion_tokens"],
                "wall_ms_total": round(float(m["wall_ms_total"]), 3),
                "wall_ms_per_run": round(float(m["wall_ms_total"]) / runs, 3) if runs else 0.0,
                "latency_p50_ms": round(_percentile(m["latencies_ms"], 50), 3),
                "latency_p95_ms": round(_percentile(m["latencies_ms"], 95), 3),
                "unknown_price": bool(m["unknown_price"]),
            }
        )
    rows.sort(key=lambda r: (r["cost_per_correct_usd"] is None, r["cost_per_correct_usd"] or 0.0))
    return {"models": rows, "n_models": len(rows)}


def _pareto_frontier(rows: list[dict[str, Any]]) -> list[str]:
    """Models on the accuracy-vs-cost Pareto frontier (higher acc OR lower cost dominates)."""
    frontier: list[str] = []
    ordered = sorted(rows, key=lambda r: r["cost_usd"])
    best_acc = -1.0
    for r in ordered:
        if r["accuracy"] > best_acc:
            frontier.append(r["model"])
            best_acc = r["accuracy"]
    return frontier


def render_markdown(agg: dict[str, Any]) -> str:
    rows = agg["models"]
    if not rows:
        return "# Cost / latency Pareto\n\n_No EvaluationResult rows with cost info found._\n"
    frontier = set(_pareto_frontier(rows))
    lines = [
        "# Cost / latency Pareto",
        "",
        f"n_models = {agg['n_models']} (sorted by $/correct ascending)",
        "",
        "| model | runs | acc | $ total | $/correct | p50 ms | p95 ms | on frontier |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cpc = "—" if r["cost_per_correct_usd"] is None else f"${r['cost_per_correct_usd']:.4f}"
        on = "★" if r["model"] in frontier else ""
        warn = " ⚠ price unknown" if r["unknown_price"] else ""
        lines.append(
            f"| `{r['model']}`{warn} | {r['runs']} | {r['accuracy'] * 100:.1f}% | "
            f"${r['cost_usd']:.4f} | {cpc} | "
            f"{r['latency_p50_ms']:.0f} | {r['latency_p95_ms']:.0f} | {on} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--evals",
        action="append",
        required=True,
        help="Repeatable: path to an EvaluationResult JSONL file.",
    )
    ap.add_argument("--out", default="reports/cost_latency.md", help="Markdown output path.")
    ap.add_argument(
        "--json",
        default=None,
        help="Optional JSON numbers path (use '-' for stdout). Suitable for paper renderer input.",
    )
    a = ap.parse_args()

    paths = [Path(p) for p in a.evals]
    agg = aggregate(paths)
    md = render_markdown(agg)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    sys.stderr.write(f"wrote {out}\n")

    if a.json:
        payload = json.dumps(agg, indent=2)
        if a.json == "-":
            sys.stdout.write(payload + "\n")
        else:
            jp = Path(a.json)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(payload + "\n", encoding="utf-8")
            sys.stderr.write(f"wrote {jp}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
