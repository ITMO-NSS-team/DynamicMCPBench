#!/usr/bin/env python3
"""E4.7 leaderboard runner: evaluate >=5 candidate models IN AGENT MODE across pool modes
(gold/target/full) and the P_alt grid, then aggregate into a leaderboard. The candidate
actively plans + calls tools; --replay serves a deterministic world (the reference traces)
so models are comparable. Reuses `dmcp eval` + `dmcp report`.

Smoke it with one --model on the demo specs; the full >=5-model run is launched from the
experiment plan.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"


def _run(cmd: list[str], *, env_override: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(cmd), flush=True)
    env = None
    if env_override:
        import os as _os

        env = _os.environ.copy()
        env.update(env_override)
    return subprocess.run(cmd, check=False, env=env).returncode


def _slug(s: str) -> str:
    return s.replace("/", "_").replace(":", "_").replace(".", "-")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True)
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--models", required=True, help="comma-separated OpenRouter model ids")
    ap.add_argument("--pools", default="gold,target,full")
    ap.add_argument("--p-alts", default="0,0.5,1.0", help="P_alt grid for the target pool")
    ap.add_argument("--pool-size", type=int, default=8)
    ap.add_argument("--repeat", type=int, default=5, help="pass^k repetitions")
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument("--reference-traces", default=None, help="enable deterministic replay")
    ap.add_argument("--out", default="reports/leaderboard")
    ap.add_argument(
        "--json", default=None, help="also emit per-model leaderboard numbers JSON (paper renderer input)"
    )
    ap.add_argument(
        "--desc-levels",
        default="raw",
        help="comma list of description-normalization levels to sweep (raw,a,b); 'raw' = no normalization",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Run up to N eval cells in parallel, each pinned to a different provider API key "
            "(FREE_MODELS_API_KEY[_2,_3,...] / OPENROUTER_API_KEY[_2,_3,...]). Default 1."
        ),
    )
    ap.add_argument(
        "--key-offset",
        type=int,
        default=0,
        help=(
            "Skip the first N keys in the provider key pool — lets parallel runners (e.g. a "
            "concurrent corpus build + this leaderboard) use disjoint key slices and avoid "
            "rate-limit contention."
        ),
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Per-cell skip: drop a (model × pool × p_alt × desc_level) cell whose eval JSONL "
            "already exists with rows; partial cells re-launch with --resume passed through to "
            "dmcp eval (which keys on task_id)."
        ),
    )
    a = ap.parse_args()

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    models = [m for m in a.models.split(",") if m]
    pools = [p for p in a.pools.split(",") if p]
    p_alts = [x for x in a.p_alts.split(",") if x]
    desc_levels = [d for d in a.desc_levels.split(",") if d]

    # Build (model × pool × p_alt × desc_level) cells once so the parallel
    # dispatcher can submit each as one unit. Each cell knows its eval path
    # (output JSONL) and the dmcp eval command it will run.
    cells: list[dict] = []
    for model in models:
        for pool in pools:
            grid = p_alts if pool == "target" else ["-"]
            for pa in grid:
                for dl in desc_levels:
                    tag = (
                        f"{_slug(model)}__{pool}"
                        + (f"__p{pa}" if pool == "target" else "")
                        + ("" if dl == "raw" else f"__d{dl}")
                    )
                    ev = out / f"eval_{tag}.jsonl"
                    cmd = [
                        DMCP,
                        "eval",
                        str(ROOT / a.specs),
                        "-m",
                        str(ROOT / a.manifest),
                        "--model",
                        model,
                        "--pool",
                        pool,
                        "--repeat",
                        str(a.repeat),
                        "--budget",
                        str(a.budget),
                        "-o",
                        str(ev),
                    ]
                    if pool == "target":
                        cmd += ["--p-alt", str(pa), "--pool-size", str(a.pool_size)]
                    if dl != "raw":
                        cmd += ["--desc-level", dl]
                    if a.reference_traces:
                        cmd += ["--replay", "--reference-traces", str(ROOT / a.reference_traces)]
                    if a.resume:
                        cmd += ["--resume"]
                    cells.append({"tag": tag, "ev": ev, "cmd": cmd, "model": model})

    # Discover provider key pool. Same numbered-sibling convention used by
    # cost_calibration.py and build_corpus.py. --key-offset slices the pool
    # so two parallel runners (e.g. a concurrent build_corpus + this) can
    # claim disjoint keys and avoid rate-limit contention.
    from dotenv import load_dotenv

    from dmcp.providers import pool_keys, resolve

    load_dotenv(override=False)
    provider = resolve(models[0]) if models else None
    key_env_var = provider.api_key_env if provider else ""
    all_keys = pool_keys(provider) if provider else []
    keys = all_keys[max(0, int(a.key_offset)) :]
    requested = max(1, int(a.concurrency))
    lanes = max(1, min(requested, len(keys) or requested))
    if keys and requested > lanes:
        print(f"[warn] requested --concurrency {requested} but only {lanes} key(s) after offset; capping")
    if not keys and provider:
        # Fall back to whatever .env exposes (no env_override) — keeps the
        # sequential, single-key path working without forcing a key pool.
        keys = [""]

    def _cell_run(cell: dict, key: str) -> tuple[str, int]:
        ev = cell["ev"]
        # Per-cell resume: if the file already exists and has rows, skip the
        # dispatch entirely. Partial files re-launch with --resume on dmcp eval.
        if a.resume and ev.exists() and ev.stat().st_size > 0:
            try:
                rows = sum(1 for line in ev.read_text(encoding="utf-8").splitlines() if line.strip())
            except OSError:
                rows = 0
            if rows > 0:
                print(f"[resume] cell {cell['tag']}: {rows} row(s) already present (passing --resume)")
        env_override = {key_env_var: key} if key and key_env_var else None
        rc = _run(cell["cmd"], env_override=env_override)
        return cell["tag"], rc

    if lanes <= 1 or not keys:
        for cell in cells:
            _cell_run(cell, keys[0] if keys else "")
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(
            f"[dispatch] running {len(cells)} cell(s) over {lanes} lane(s) (keys after offset={a.key_offset})"
        )
        with ThreadPoolExecutor(max_workers=lanes) as ex:
            futs = {
                ex.submit(_cell_run, cell, keys[i % len(keys)]): cell["tag"] for i, cell in enumerate(cells)
            }
            for fut in as_completed(futs):
                tag = futs[fut]
                _, rc = fut.result()
                if rc != 0:
                    print(f"[warn] cell {tag} exited {rc}; continuing")

    eval_files = [str(c["ev"]) for c in cells if c["ev"].exists()]

    if not eval_files:
        print("no eval outputs produced")
        return
    report_cmd = [DMCP, "report", "--specs", str(ROOT / a.specs), "-o", str(out / "leaderboard.md")]
    for ev in eval_files:
        report_cmd += ["--evals", ev]
    _run(report_cmd)
    print(f"[done] {len(eval_files)} eval runs → {out / 'leaderboard.md'}")

    if a.json:
        import collections

        agg = collections.defaultdict(lambda: {"n": 0, "pass": 0, "sae": 0})
        passk = collections.defaultdict(list)  # (model, file, task) -> [passed]
        for ev in eval_files:
            for ln in Path(ev).read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                m = r.get("candidate_model") or "?"
                agg[m]["n"] += 1
                agg[m]["pass"] += bool(r.get("passed"))
                agg[m]["sae"] += bool(r.get("had_sae"))
                passk[(m, ev, r.get("task_id"))].append(bool(r.get("passed")))
        pk = collections.defaultdict(lambda: [0, 0])
        for (m, _ev, _t), passes in passk.items():
            pk[m][1] += 1
            pk[m][0] += all(passes)
        numbers = {
            "models": [
                {
                    "model": m,
                    "n": d["n"],
                    "pass_rate": d["pass"] / d["n"] if d["n"] else None,
                    "sae_rate": d["sae"] / d["n"] if d["n"] else None,
                    "pass_k": pk[m][0] / pk[m][1] if pk[m][1] else None,
                }
                for m, d in sorted(
                    agg.items(), key=lambda kv: -(kv[1]["pass"] / kv[1]["n"] if kv[1]["n"] else 0)
                )
            ]
        }
        jp = ROOT / a.json
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8")
        print(f"numbers → {jp}")


if __name__ == "__main__":
    main()
