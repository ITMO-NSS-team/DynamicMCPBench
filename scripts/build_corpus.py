#!/usr/bin/env python3
"""E3.9 corpus runner: a strategy-diverse, complexity-stratified TaskSpec corpus over a
manifest. Phase 1 goal-gen (every generation strategy × each complexity level) → goals;
Phase 2 generate (forward explore → distill) → traces + specs; Phase 3 coverage report.

Phase-level resumable (cached goals/specs are reused unless --force) and detached-friendly.
The FULL paper-scale run (~750-1000 specs, ≥150/cell) is launched from the experiment plan;
this runner is what executes it. Smoke it with a tiny --per-strategy on a few --server ids.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dmcp.goal_gen import GEN_STRATEGIES  # noqa: E402

DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--server", action="append", dest="servers", default=None)
    ap.add_argument("--strategies", default=",".join(GEN_STRATEGIES),
                    help="comma-separated generation strategies (default: all 15)")
    ap.add_argument("--complexities", default="simple,medium,hard")
    ap.add_argument("--per-strategy", type=int, default=4)
    ap.add_argument("--explore-model", default="anthropic/claude-haiku-4.5")
    ap.add_argument("--distill-model", default="anthropic/claude-haiku-4.5")
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument("--out", default="data/corpus")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    strategies = [s for s in a.strategies.split(",") if s]
    server_args: list[str] = []
    for s in a.servers or []:
        server_args += ["--server", s]

    # ---- Phase 1: goal-gen per complexity (all strategies in one call each) ----
    goals_full = out / "goals_full.json"
    if goals_full.exists() and not a.force:
        print(f"[phase1] reuse {goals_full}")
    else:
        import json

        merged: list[dict] = []
        seen: set[str] = set()
        for c in [x for x in a.complexities.split(",") if x]:
            gpath = out / f"goals_{c}.json"
            strat_args: list[str] = []
            for s in strategies:
                strat_args += ["--strategy", s]
            rc = _run([
                DMCP, "goal-gen", "-m", str(ROOT / a.manifest), *server_args, *strat_args,
                "--per-strategy", str(a.per_strategy), "--complexity", c, "-o", str(gpath),
            ])
            if rc != 0 or not gpath.exists():
                print(f"[phase1] goal-gen failed for complexity={c} (rc={rc})")
                continue
            for e in json.loads(gpath.read_text())["entries"]:
                if e["goal_id"] not in seen:
                    seen.add(e["goal_id"])
                    merged.append(e)
        goals_full.write_text(json.dumps({"goals_version": "0.1.0", "entries": merged}, indent=2))
        print(f"[phase1] {len(merged)} goals → {goals_full}")

    # ---- Phase 2: generate (explore + distill) ----
    traces = out / "traces.jsonl"
    specs = out / "specs.jsonl"
    if specs.exists() and not a.force:
        print(f"[phase2] reuse {specs}")
    else:
        _run([
            DMCP, "generate", str(goals_full), "-m", str(ROOT / a.manifest),
            "--explore-model", a.explore_model, "--distill-model", a.distill_model,
            "--budget", str(a.budget), "--traces-out", str(traces), "--specs-out", str(specs),
        ])

    # ---- Phase 3: coverage report ----
    _run([
        DMCP.replace("bin/dmcp", "bin/python") if DMCP.endswith("bin/dmcp") else "python",
        str(ROOT / "scripts" / "corpus_coverage.py"),
        "--traces", str(traces), "--specs", str(specs),
        "--manifest", str(ROOT / a.manifest), "-o", str(out / "coverage.md"),
    ])
    print(f"[done] corpus in {out}")


if __name__ == "__main__":
    main()
