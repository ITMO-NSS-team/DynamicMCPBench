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


def _run(cmd: list[str], *, env_override: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(cmd), flush=True)
    env = None
    if env_override:
        import os as _os

        env = _os.environ.copy()
        env.update(env_override)
    return subprocess.run(cmd, check=False, env=env).returncode


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
    ap.add_argument("--surfaces", default=None, help="Pre-captured surfaces JSON for goal-gen")
    ap.add_argument(
        "--goalgen-models",
        default=None,
        help="Comma panel of goal-gen models (cross-family; overrides --goalgen-model)",
    )
    ap.add_argument(
        "--goalgen-model", default=None, help="Model that authors the goals (recorded in provenance)"
    )
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
    ap.add_argument(
        "--explore-timeout",
        type=float,
        default=600.0,
        help="Per-goal explore subprocess timeout (s), forwarded to dmcp generate",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Per-shard resume: pass --resume to the inner `dmcp generate` so it skips goal_ids "
            "already represented in specs_shard_<i>.jsonl (via provenance.goal_id)."
        ),
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Run up to N Phase-2 shards in parallel, each pinned to a different provider API "
            "key (FREE_MODELS_API_KEY[_2,_3,...] / OPENROUTER_API_KEY[_2,_3,...]). Default 1."
        ),
    )
    ap.add_argument(
        "--key-offset",
        type=int,
        default=0,
        help=(
            "Skip the first N keys in the provider key pool — lets parallel runners (e.g. "
            "this build_corpus + a concurrent run_leaderboard) use disjoint key slices and "
            "avoid rate-limit contention."
        ),
    )
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
        # NOTE: `json` is imported at module scope. Re-importing here would
        # make Python treat `json` as a function-local, shadowing the module
        # binding throughout `main()` — and any unentered branch (e.g. Phase 1
        # reuse → Phase 2 generate) would crash on UnboundLocalError. Don't.
        merged: list[dict] = []
        seen: set[str] = set()
        goalgen_panel = [
            x.strip() for x in (a.goalgen_models or a.goalgen_model or "").split(",") if x.strip()
        ] or [None]
        gg_surfaces_args = ["--surfaces", str(ROOT / a.surfaces)] if a.surfaces else []
        strat_args = []
        for s in strategies:
            strat_args += ["--strategy", s]
        for c in [x for x in a.complexities.split(",") if x]:
            for gm in goalgen_panel:
                gslug = (gm or "default").replace("/", "_").replace(".", "-")
                gpath = out / f"goals_{c}_{gslug}.json"
                per_strat = max(1, a.per_strategy // len(goalgen_panel))
                gg_model_args = ["--model", gm] if gm else []
                rc = _run(
                    [
                        DMCP,
                        "goal-gen",
                        "-m",
                        str(ROOT / a.manifest),
                        *server_args,
                        *strat_args,
                        *gg_model_args,
                        *gg_surfaces_args,
                        "--per-strategy",
                        str(per_strat),
                        "--complexity",
                        c,
                        "-o",
                        str(gpath),
                    ]
                )
                if rc != 0 or not gpath.exists():
                    print(f"[phase1] goal-gen failed for complexity={c} model={gm} (rc={rc})")
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
    # Coarse reuse fires only when neither --force nor --resume is set: --resume
    # delegates the skip decision to the inner shard's per-goal logic, which is
    # finer-grained and catches the case where specs.jsonl carries only partial
    # progress from a previous run.
    if specs.exists() and not a.force and not a.resume:
        print(f"[phase2] reuse {specs}")
    else:
        explorer_panel = [m for m in (a.explorer_models or "").split(",") if m]
        distiller_panel = [m for m in (a.distiller_candidates or "").split(",") if m]
        if explorer_panel and distiller_panel:
            assignments = assign_shards(explorer_panel, distiller_panel)
            entries = json.loads(goals_full.read_text())["entries"]
            shards = shard_goals(entries, len(assignments))

            # Resolve provider key pool for parallel shard dispatch. Free /
            # paid both supported — same numbered-sibling env convention.
            # Parent process must load_dotenv explicitly (dmcp.llm only does
            # so inside the subprocess, which is too late for us to read here).
            from dotenv import load_dotenv

            from dmcp.providers import pool_keys, resolve

            load_dotenv(override=False)
            provider = resolve(explorer_panel[0])
            key_env_var = provider.api_key_env
            all_keys = pool_keys(provider)
            if not all_keys:
                raise SystemExit(f"no API keys found for provider {provider.name!r} (env {key_env_var})")
            # Slice off the first N keys when --key-offset > 0 so a concurrent
            # process (e.g. a leaderboard run) can claim them instead.
            keys = all_keys[max(0, int(a.key_offset)) :]
            if not keys:
                raise SystemExit(
                    f"--key-offset {a.key_offset} consumed every key (pool size {len(all_keys)})"
                )
            requested = max(1, int(a.concurrency))
            lanes = max(1, min(requested, len(keys)))
            if requested > lanes:
                print(f"[warn] requested --concurrency {requested} but only {lanes} key(s); capping")

            def _run_shard(shard_idx: int, assignment, goals_subset: list[dict], key: str) -> int:
                if not goals_subset:
                    return 0
                shard_goals_path = out / f"goals_shard_{shard_idx}.json"
                shard_goals_path.write_text(
                    json.dumps({"goals_version": "0.1.0", "entries": goals_subset}, indent=2)
                )
                shard_traces = out / f"traces_shard_{shard_idx}.jsonl"
                shard_specs = out / f"specs_shard_{shard_idx}.jsonl"
                print(
                    f"[phase2] shard {shard_idx}: {len(goals_subset)} goals "
                    f"explorer={assignment.explorer_model} ({assignment.explorer_family}) "
                    f"distiller={assignment.distiller_model} ({assignment.distiller_family}) "
                    f"key=<{key_env_var}#{keys.index(key) + 1}>",
                    flush=True,
                )
                gen_cmd = [
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
                    "--explore-timeout",
                    str(a.explore_timeout),
                    "--traces-out",
                    str(shard_traces),
                    "--specs-out",
                    str(shard_specs),
                ]
                if a.resume:
                    gen_cmd.append("--resume")
                rc = _run(gen_cmd, env_override={key_env_var: key})
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
                print(f"[phase2] shard {shard_idx}: stamped provenance on {touched} specs", flush=True)
                return rc

            shard_args = list(enumerate(zip(assignments, shards, strict=True)))
            if lanes <= 1:
                for shard_idx, (assignment, goals_subset) in shard_args:
                    _run_shard(shard_idx, assignment, goals_subset, keys[0])
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                print(f"[phase2] dispatching {len(shard_args)} shard(s) over {lanes} parallel lane(s)")
                with ThreadPoolExecutor(max_workers=lanes) as ex:
                    futs = {
                        ex.submit(
                            _run_shard,
                            shard_idx,
                            assignment,
                            goals_subset,
                            keys[i % len(keys)],
                        ): shard_idx
                        for i, (shard_idx, (assignment, goals_subset)) in enumerate(shard_args)
                    }
                    for fut in as_completed(futs):
                        shard_idx = futs[fut]
                        fut.result()  # propagate any uncaught exception
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
                    "--explore-timeout",
                    str(a.explore_timeout),
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
