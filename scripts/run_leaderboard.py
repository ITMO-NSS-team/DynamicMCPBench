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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


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
    a = ap.parse_args()

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    models = [m for m in a.models.split(",") if m]
    pools = [p for p in a.pools.split(",") if p]
    p_alts = [x for x in a.p_alts.split(",") if x]
    desc_levels = [d for d in a.desc_levels.split(",") if d]
    eval_files: list[str] = []

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
                    if _run(cmd) == 0 and ev.exists():
                        eval_files.append(str(ev))

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
