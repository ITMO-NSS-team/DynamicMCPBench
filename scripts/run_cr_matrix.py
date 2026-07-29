#!/usr/bin/env python3
"""Run the camera-ready tool-exposure matrix, sharded across OpenRouter key lanes.

Each cell is one (model, exposure-condition) pair evaluated in deterministic
replay over a fixed task subset (`scripts/cr_subset.py`). Cells run one at a
time; within a cell the subset is split into shards that run concurrently, each
shard pinned to an `OPENROUTER_API_KEY*` lane from `.env` so rate limits and
spend spread across accounts. Nothing here touches live MCP servers — every run
is `--replay --reference-traces`, so results stay machine-independent.

Condition syntax: `rag:K` (embedding top-K over the pool), `hier` (router picks a
server, then its tools), `flat` (whole pool in one list). Pool defaults to
`full` (the entire catalog reconstructed from the reference traces).

Scope of v0: orchestration and resume only. It computes no metrics — scoring is
`dmcp eval`'s job and comparison is `scripts/cr_compare.py`'s.

Reproduce:
    uv run python scripts/run_cr_matrix.py --models minimax/minimax-m3 \
        --conditions rag:4,rag:8,rag:16,rag:32,hier --repeat 1
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import re
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_lanes(env_path: pathlib.Path) -> list[str]:
    """Lane keys from .env, primary first. Values never leave this process."""
    found: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = (p.strip() for p in line.split("=", 1))
            if re.fullmatch(r"OPENROUTER_API_KEY(_[2-8])?", k) and v:
                found[k] = v
    for i in range(1, 9):
        k = "OPENROUTER_API_KEY" if i == 1 else f"OPENROUTER_API_KEY_{i}"
        if os.environ.get(k):
            found[k] = os.environ[k]
    ordered = ["OPENROUTER_API_KEY"] + [f"OPENROUTER_API_KEY_{i}" for i in range(2, 9)]
    lanes = [found[k] for k in ordered if k in found]
    # Keys may be duplicated across labels; a duplicate is one lane, not two.
    return list(dict.fromkeys(lanes))


def condition_flags(cond: str, pool: str) -> list[str]:
    if cond == "flat":
        arch, extra = "flat", []
    elif cond == "hier":
        arch, extra = "hier", []
    elif cond.startswith("rag:"):
        arch, extra = "rag", ["--rag-k", cond.split(":", 1)[1]]
    else:
        raise SystemExit(f"unknown condition {cond!r} (want flat | hier | rag:K)")
    return ["--pool", pool, "--architecture", arch, *extra]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def shard_paths(out_dir: pathlib.Path, cell: str, n: int) -> list[pathlib.Path]:
    return [out_dir / f"{cell}.shard{i}.jsonl" for i in range(n)]


def done_ids(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text().splitlines():
        if line.strip():
            ids.add(json.loads(line)["task_id"])
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--corpus", default="hfdl", help="dir holding traces.jsonl")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--models", required=True, help="comma-separated OpenRouter model ids")
    ap.add_argument("--conditions", required=True, help="comma-separated: flat | hier | rag:K")
    ap.add_argument("--pool", default="full")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument("--shards", type=int, default=6, help="concurrent shards per cell")
    ap.add_argument("--lanes", default="", help="1-based lane numbers to use, e.g. 1,2,3 (default: all)")
    ap.add_argument("--out-dir", default="evals/cr")
    ap.add_argument("--log-dir", default="evals/cr/logs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lanes = read_lanes(ROOT / ".env")
    if args.lanes:
        want = [int(x) for x in args.lanes.split(",") if x.strip()]
        bad = [i for i in want if not 1 <= i <= len(lanes)]
        if bad:
            raise SystemExit(f"lane(s) {bad} out of range — {len(lanes)} lane(s) available")
        lanes = [lanes[i - 1] for i in want]
    if not lanes:
        raise SystemExit("no OPENROUTER_API_KEY* lane found in .env or environment")

    subset = pathlib.Path(args.subset)
    specs = [ln for ln in subset.read_text().splitlines() if ln.strip()]
    out_dir = pathlib.Path(args.out_dir)
    log_dir = pathlib.Path(args.log_dir)
    shard_dir = out_dir / "shards"
    for d in (out_dir, log_dir, shard_dir):
        d.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    print(f"{len(specs)} tasks · {len(models)} models · {len(conditions)} conditions · {len(lanes)} lanes")

    for model, cond in itertools.product(models, conditions):
        cell = f"{slug(model.split('/')[-1])}__{slug(cond)}__r{args.repeat}"
        outs = shard_paths(out_dir, cell, args.shards)
        procs: list[tuple[subprocess.Popen, pathlib.Path, pathlib.Path]] = []
        started = time.time()

        for i, out in enumerate(outs):
            chunk = specs[i :: args.shards]
            shard_in = shard_dir / f"{cell}.in{i}.jsonl"
            remaining = [ln for ln in chunk if json.loads(ln)["task_id"] not in done_ids(out)]
            if not remaining:
                continue
            shard_in.write_text("\n".join(remaining) + "\n")
            cmd = [
                "uv", "run", "dmcp", "eval", str(shard_in),
                "--manifest", args.manifest,
                "--replay", "--reference-traces", str(pathlib.Path(args.corpus) / "traces.jsonl"),
                "--model", model,
                *condition_flags(cond, args.pool),
                "--budget", str(args.budget),
                "--repeat", str(args.repeat),
                "-o", str(out), "--resume",
            ]  # fmt: skip
            if args.dry_run:
                print("  would run:", " ".join(cmd), f"[lane {i % len(lanes) + 1}]")
                continue
            log = log_dir / f"{cell}.shard{i}.log"
            env = {**os.environ, "OPENROUTER_API_KEY": lanes[i % len(lanes)]}
            fh = log.open("w")
            procs.append((subprocess.Popen(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT), out, log))
            time.sleep(2)

        if args.dry_run:
            continue
        if not procs:
            print(f"[{cell}] already complete — skipped")
            continue
        print(f"[{cell}] {len(procs)} shards running…", flush=True)
        failed = [log for p, _, log in procs if p.wait() != 0]
        rows = sum(len(done_ids(o)) for o in outs)
        mins = (time.time() - started) / 60
        status = f"{len(failed)} shard(s) FAILED — see {failed[0]}" if failed else "ok"
        print(f"[{cell}] {rows} results in {mins:.1f} min — {status}", flush=True)


if __name__ == "__main__":
    main()
