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
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dmcp.families import assign_shards, family_of  # noqa: E402
from dmcp.goal_gen import GEN_STRATEGIES  # noqa: E402

DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"


def shard_goals(entries: list[dict], n_shards: int) -> list[list[dict]]:
    """Deterministic round-robin partition of goals into N shards.

    Round-robin so each shard sees a balanced mix of strategies/complexities —
    a contiguous split would put all early-strategy goals in shard 0 and bias
    the per-family corpus.
    """
    if n_shards <= 0:
        raise ValueError("n_shards must be > 0")
    out: list[list[dict]] = [[] for _ in range(n_shards)]
    for i, e in enumerate(entries):
        out[i % n_shards].append(e)
    return out


def stamp_provenance_in_jsonl(specs_path: Path, overrides: dict) -> int:
    """Overlay `overrides` into each spec's `provenance` dict in place.

    Used after a `dmcp generate` shard finishes — the distiller already stamped
    explorer/distiller families, this layer adds shard id + validator-ready
    fields. Returns the number of rows touched. No-op when the file is missing.
    """
    if not specs_path.exists():
        return 0
    lines = specs_path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        prov = d.get("provenance") or {}
        prov.update(overrides)
        d["provenance"] = prov
        out_lines.append(json.dumps(d))
    specs_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return len(out_lines)


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--server", action="append", dest="servers", default=None)
    ap.add_argument(
        "--strategies",
        default=",".join(GEN_STRATEGIES),
        help="comma-separated generation strategies (default: all 15)",
    )
    ap.add_argument("--complexities", default="simple,medium,hard")
    ap.add_argument("--per-strategy", type=int, default=4)
    ap.add_argument(
        "--explore-model",
        default="anthropic/claude-haiku-4.5",
        help="Single-model exploration (used only when --explorer-models is absent).",
    )
    ap.add_argument(
        "--distill-model",
        default="anthropic/claude-haiku-4.5",
        help="Single-model distillation (used only when --explorer-models is absent).",
    )
    ap.add_argument(
        "--explorer-models",
        default=None,
        help=(
            "Comma-separated explorer panel (E8.6). Goals are round-robin sharded across these; "
            "each shard pairs with a cross-family distiller from --distiller-candidates."
        ),
    )
    ap.add_argument(
        "--distiller-candidates",
        default=None,
        help=(
            "Comma-separated distiller candidates; per shard, the picker takes the first "
            "non-explorer-family one."
        ),
    )
    ap.add_argument(
        "--validator-model",
        default=None,
        help=(
            "Optional 4th-family validator (e.g. qwen/qwen3.7-max). Stamps each spec via "
            "`dmcp validate-corpus`."
        ),
    )
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
            rc = _run(
                [
                    DMCP,
                    "goal-gen",
                    "-m",
                    str(ROOT / a.manifest),
                    *server_args,
                    *strat_args,
                    "--per-strategy",
                    str(a.per_strategy),
                    "--complexity",
                    c,
                    "-o",
                    str(gpath),
                ]
            )
            if rc != 0 or not gpath.exists():
                print(f"[phase1] goal-gen failed for complexity={c} (rc={rc})")
                continue
            for e in json.loads(gpath.read_text())["entries"]:
                if e["goal_id"] not in seen:
                    seen.add(e["goal_id"])
                    merged.append(e)
        goals_full.write_text(json.dumps({"goals_version": "0.1.0", "entries": merged}, indent=2))
        print(f"[phase1] {len(merged)} goals → {goals_full}")

    # ---- Phase 2: generate (explore + distill); cross-family panel when requested ----
    traces = out / "traces.jsonl"
    specs = out / "specs.jsonl"
    if specs.exists() and not a.force:
        print(f"[phase2] reuse {specs}")
    else:
        explorer_panel = [m for m in (a.explorer_models or "").split(",") if m]
        distiller_panel = [m for m in (a.distiller_candidates or "").split(",") if m]
        if explorer_panel and distiller_panel:
            assignments = assign_shards(explorer_panel, distiller_panel)
            entries = json.loads(goals_full.read_text())["entries"]
            shards = shard_goals(entries, len(assignments))
            for shard_idx, (assignment, goals_subset) in enumerate(zip(assignments, shards, strict=True)):
                if not goals_subset:
                    continue
                shard_goals_path = out / f"goals_shard_{shard_idx}.json"
                shard_goals_path.write_text(
                    json.dumps({"goals_version": "0.1.0", "entries": goals_subset}, indent=2)
                )
                shard_traces = out / f"traces_shard_{shard_idx}.jsonl"
                shard_specs = out / f"specs_shard_{shard_idx}.jsonl"
                print(
                    f"[phase2] shard {shard_idx}: {len(goals_subset)} goals "
                    f"explorer={assignment.explorer_model} ({assignment.explorer_family}) "
                    f"distiller={assignment.distiller_model} ({assignment.distiller_family})"
                )
                rc = _run(
                    [
                        DMCP,
                        "generate",
                        str(shard_goals_path),
                        "-m",
                        str(ROOT / a.manifest),
                        "--explore-model",
                        assignment.explorer_model,
                        "--distill-model",
                        assignment.distiller_model,
                        "--budget",
                        str(a.budget),
                        "--traces-out",
                        str(shard_traces),
                        "--specs-out",
                        str(shard_specs),
                    ]
                )
                if rc != 0:
                    print(f"[phase2] shard {shard_idx} exited {rc}; continuing")
                touched = stamp_provenance_in_jsonl(
                    shard_specs,
                    {
                        "shard_id": shard_idx,
                        "explorer_model": assignment.explorer_model,
                        "explorer_family": assignment.explorer_family,
                        "distiller_model": assignment.distiller_model,
                        "distiller_family": assignment.distiller_family,
                    },
                )
                print(f"[phase2] shard {shard_idx}: stamped provenance on {touched} specs")
            # Concatenate shard outputs into the canonical corpus files.
            with traces.open("w", encoding="utf-8") as ft, specs.open("w", encoding="utf-8") as fs:
                for shard_idx in range(len(assignments)):
                    sp = out / f"traces_shard_{shard_idx}.jsonl"
                    if sp.exists():
                        ft.write(sp.read_text(encoding="utf-8"))
                    sp = out / f"specs_shard_{shard_idx}.jsonl"
                    if sp.exists():
                        fs.write(sp.read_text(encoding="utf-8"))
        else:
            _run(
                [
                    DMCP,
                    "generate",
                    str(goals_full),
                    "-m",
                    str(ROOT / a.manifest),
                    "--explore-model",
                    a.explore_model,
                    "--distill-model",
                    a.distill_model,
                    "--budget",
                    str(a.budget),
                    "--traces-out",
                    str(traces),
                    "--specs-out",
                    str(specs),
                ]
            )

    # ---- Phase 2b: validator pass (4th-family) ----
    if a.validator_model and specs.exists():
        print(f"[phase2b] validator: {a.validator_model} ({family_of(a.validator_model)}) over {specs.name}")
        rc = _run(
            [
                DMCP,
                "validate-corpus",
                str(specs),
                "--validator-model",
                a.validator_model,
                "--output",
                str(specs),
            ]
        )
        if rc != 0:
            print(f"[phase2b] validator exited {rc}; continuing")

    # ---- Phase 3: coverage report ----
    _run(
        [
            DMCP.replace("bin/dmcp", "bin/python") if DMCP.endswith("bin/dmcp") else "python",
            str(ROOT / "scripts" / "corpus_coverage.py"),
            "--traces",
            str(traces),
            "--specs",
            str(specs),
            "--manifest",
            str(ROOT / a.manifest),
            "-o",
            str(out / "coverage.md"),
        ]
    )
    print(f"[done] corpus in {out}")


if __name__ == "__main__":
    main()
