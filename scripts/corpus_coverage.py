#!/usr/bin/env python3
"""E6.3: corpus coverage report. Bins TaskSpecs by generation-strategy / depth-bin /
dynamism / intra-vs-inter-server / server-tier. Joins each spec to its source trace
(which carries `goal_tags` via the generate `extra_seed`) to recover the strategy.

Usage:
  uv run python scripts/corpus_coverage.py --traces traces/generated.jsonl \\
      --specs specs/generated.jsonl --manifest manifests/servers.json -o reports/corpus_coverage.md
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _goal_tags(trace: dict) -> list[str]:
    """Recover the goal_tags stashed into the trace via generate's extra_seed."""
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


def _tag(tags: list[str], prefix: str) -> str:
    return next((t.split(":", 1)[1] for t in tags if t.startswith(prefix + ":")), "?")


def _depth_bin(d: int) -> str:
    return "1-2 (simple)" if d <= 2 else ("3-4 (medium)" if d <= 4 else "5+ (hard)")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default="traces/generated.jsonl")
    ap.add_argument("--specs", default="specs/generated.jsonl")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("-o", "--out", default="reports/corpus_coverage.md")
    a = ap.parse_args()

    traces = _read_jsonl(ROOT / a.traces)
    specs = _read_jsonl(ROOT / a.specs)
    tags_for_trace = {t.get("trace_id"): _goal_tags(t) for t in traces}
    tier_for = {}
    try:
        for e in json.loads((ROOT / a.manifest).read_text())["servers"]:
            tier = _tag(e.get("tags", []), "tier")
            tier_for[e["server_id"]] = (
                tier if tier != "?" else ("substrate" if "substrate" in e.get("tags", []) else "crawled")
            )
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass

    by_strategy = collections.Counter()
    by_depth = collections.Counter()
    by_dyn = collections.Counter()
    by_scope = collections.Counter()
    by_tier = collections.Counter()
    by_complexity = collections.Counter()
    strat_x_depth = collections.Counter()
    for s in specs:
        gtags = tags_for_trace.get(s.get("source_trace_id"), [])
        strat = _tag(gtags, "strategy")
        comp = _tag(gtags, "complexity")
        servers = s.get("servers_used", [])
        scope = "cross-server" if (len(servers) > 1 or "cross-server" in gtags) else "intra-server"
        depth = (s.get("complexity") or {}).get("trace_depth", len(servers))
        dyn = s.get("dynamism", "?")
        by_strategy[strat] += 1
        by_depth[_depth_bin(depth)] += 1
        by_dyn[dyn] += 1
        by_scope[scope] += 1
        by_complexity[comp] += 1
        strat_x_depth[(strat, _depth_bin(depth))] += 1
        for sid in servers:
            by_tier[tier_for.get(sid, "?")] += 1

    def _tbl(title, counter):
        rows = "\n".join(f"| {k} | {v} |" for k, v in sorted(counter.items(), key=lambda kv: -kv[1]))
        return f"### {title}\n\n| key | tasks |\n|---|---|\n{rows}\n"

    out = [
        "# Corpus coverage report (E6.3)",
        "",
        f"{len(specs)} TaskSpecs distilled from {len(traces)} traces.",
        "",
        _tbl("By generation strategy", by_strategy),
        _tbl("By trace-depth bin", by_depth),
        _tbl("By dynamism", by_dyn),
        _tbl("By scope (intra vs inter-server)", by_scope),
        _tbl("By server tier (tool occurrences)", by_tier),
        _tbl("By complexity knob", by_complexity),
        "### Strategy × depth-bin\n",
        "| strategy | depth-bin | tasks |\n|---|---|---|",
        *[f"| {st} | {db} | {n} |" for (st, db), n in sorted(strat_x_depth.items())],
    ]
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"coverage: {len(specs)} specs -> {outp}")
    print("strategies:", dict(by_strategy))
    print("depth bins:", dict(by_depth))
    print("scope:", dict(by_scope))


if __name__ == "__main__":
    main()
