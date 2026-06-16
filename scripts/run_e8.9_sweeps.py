#!/usr/bin/env python3
"""E8.9 SAE sweeps — outage-resilient runner (G3.1 P_alt curves + G3.2 ablation).

`dmcp curve` / `dmcp ablate` write only at the very end and don't checkpoint,
so a kill/outage mid-run loses everything. This runner breaks the work into
small units that each save their own output file, and **skips units whose
output already exists** — so an interruption only loses the in-flight units
and a plain re-run resumes from where it stopped.

Units:
  - curve: one (model × single P_alt point) per file → curve_<model>_p<p>.json
  - ablate: one model per file → ablate_<model>.json

Concurrency = number of OpenRouter keys, each running unit gets a distinct key
(no key shared between concurrent units). Run with:

    set -a; source .env; set +a
    uv run python scripts/run_e8.9_sweeps.py
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
OUT = ROOT / "reports" / "e8.9"
OUT.mkdir(parents=True, exist_ok=True)

SPECS = str(ROOT / "data" / "leaderboard_350" / "specs.jsonl")
REF = str(ROOT / "data" / "merged_hf" / "traces.jsonl")
MAN = str(ROOT / "manifests" / "servers.json")

CURVE_MODELS = {
    "glm-5.1": "z-ai/glm-5.1",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "qwen3.7-max": "qwen/qwen3.7-max",
}
P_ALTS = ["0.0", "0.25", "0.5", "0.75", "1.0"]
ABLATE_MODELS = {
    "glm-5.1": "z-ai/glm-5.1",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
}


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
    for slug, model in CURVE_MODELS.items():
        for p in P_ALTS:
            out = OUT / f"curve_{slug}_p{p}.json"
            units.append(
                (
                    out,
                    [DMCP, "curve", SPECS, "--model", model, "--manifest", MAN,
                     "--reference-traces", REF, "--p-alts", p, "--pool-size", "8",
                     "--budget", "12", "--output", str(out)],
                )
            )
    for slug, model in ABLATE_MODELS.items():
        out = OUT / f"ablate_{slug}.json"
        units.append(
            (
                out,
                [DMCP, "ablate", SPECS, "--model", model, "--manifest", MAN,
                 "--reference-traces", REF, "--pool-size", "8", "--budget", "12",
                 "--output", str(out)],
            )
        )
    return units


def main() -> None:
    keys = _keys()
    free_keys = list(keys)
    todo = [(o, c) for o, c in _units() if not (o.exists() and o.stat().st_size > 0)]
    done_already = len(_units()) - len(todo)
    print(f"{len(_units())} units total, {done_already} already done, {len(todo)} to run, {len(keys)} keys")

    running: list[tuple[subprocess.Popen, Path, str]] = []
    while todo or running:
        while todo and free_keys:
            out, cmd = todo.pop(0)
            key = free_keys.pop()
            env = {**os.environ, "OPENROUTER_API_KEY": key}
            log = out.with_suffix(".log")
            proc = subprocess.Popen(cmd, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
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
    print(f"DONE. {len(_units()) - len(remaining)}/{len(_units())} units have output"
          + (f"; MISSING: {[o.name for o in remaining]}" if remaining else " (all complete)"))


if __name__ == "__main__":
    main()
