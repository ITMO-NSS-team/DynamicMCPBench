#!/usr/bin/env python3
"""E8.9 — launch ONLY the gemma + qwen3.6 curve units, in parallel with the
already-running ablations.

Scratch ops launcher (not committed): the main run_e8.9_sweeps.py would also try
to (re)run the in-flight ablation units, which have no output yet, so a second
full orchestrator would double-run them. This one targets only the two new
models' 10 curve units, skips any that already have output, and caps concurrency
so the 2 live ablation procs are never starved/oversubscribed (<= 8 total).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
OUT = ROOT / "reports" / "e8.9"

SPECS = str(ROOT / "data" / "leaderboard_350" / "specs.jsonl")
REF = str(ROOT / "data" / "merged_hf" / "traces.jsonl")
MAN = str(ROOT / "manifests" / "servers.json")

NEW_MODELS = {
    "gemma-4-31b-it": "google/gemma-4-31b-it",
    "qwen3.6-35b-a3b": "qwen/qwen3.6-35b-a3b",
}
P_ALTS = ["0.0", "0.25", "0.5", "0.75", "1.0"]
MAX_CONC = 6  # 2 ablations already running -> keep total dmcp procs <= 8


def _keys() -> list[str]:
    out = []
    for k in [os.environ.get("OPENROUTER_API_KEY")] + [
        os.environ.get(f"OPENROUTER_API_KEY_{i}") for i in range(2, 9)
    ]:
        if k and k not in out:
            out.append(k)
    if not out:
        raise SystemExit("no OPENROUTER_API_KEY* in env — `set -a; source .env; set +a` first")
    return out


def _units() -> list[tuple[Path, list[str]]]:
    units: list[tuple[Path, list[str]]] = []
    for slug, model in NEW_MODELS.items():
        for p in P_ALTS:
            out = OUT / f"curve_{slug}_p{p}.json"
            units.append(
                (
                    out,
                    [DMCP, "curve", SPECS, "--model", model, "--manifest", MAN,
                     "--reference-traces", REF, "--p-alts", p, "--pool-size", "8",
                     "--budget", "12", "--output", str(out)],
                )
            )  # fmt: skip
    return units


def main() -> None:
    keys = _keys()[:MAX_CONC]
    free_keys = list(keys)
    todo = [(o, c) for o, c in _units() if not (o.exists() and o.stat().st_size > 0)]
    print(f"{len(_units())} new-model curve units, {len(_units()) - len(todo)} done, "
          f"{len(todo)} to run, {len(keys)} keys (cap {MAX_CONC})")  # fmt: skip

    running: list[tuple[subprocess.Popen, Path, str]] = []
    while todo or running:
        while todo and free_keys:
            out, cmd = todo.pop(0)
            key = free_keys.pop()
            env = {**os.environ, "OPENROUTER_API_KEY": key}
            log = out.with_suffix(".log")
            # fd must outlive the subprocess, so a `with` would close it too early.
            proc = subprocess.Popen(cmd, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)  # noqa: SIM115
            running.append((proc, out, key))
            print(f"  ▶ {out.name}")
        time.sleep(5)
        for proc, out, key in list(running):
            if proc.poll() is not None:
                ok = out.exists() and out.stat().st_size > 0
                print(f"  {'✓' if ok else '✗'} {out.name} (rc={proc.returncode})")
                running.remove((proc, out, key))
                free_keys.append(key)
    remaining = [o for o, _ in _units() if not (o.exists() and o.stat().st_size > 0)]
    print(f"DONE. {len(_units()) - len(remaining)}/{len(_units())} new-model units have output"
          + (f"; MISSING: {[o.name for o in remaining]}" if remaining else " (all complete)"))  # fmt: skip


if __name__ == "__main__":
    main()
