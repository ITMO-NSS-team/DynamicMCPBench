#!/usr/bin/env python3
"""E8.3 / B3: tool-scaling — accuracy / SAE vs candidate tool-surface size.

Sweeps `--pool-size` (or `--pool full`) across a fixed corpus and model in replay
mode, then aggregates per-N accuracy + SAE rate with Wilson 95% CIs. Produces
a markdown report + a numbers JSON suitable for the paper regenerator.

The dispatching shell-out to `dmcp eval` is paid LLM compute; the aggregation
half is pure Python and unit-tested directly. Smoke it with one tiny size and
a small spec slice; the full sweep is launched from the experiment plan.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"

DEFAULT_POOL_SIZES = "4,8,16,32,full"
FULL_SENTINEL = "full"


def _parse_sizes(spec: str) -> list[str]:
    """Validate and return the comma-separated size sweep as strings.

    Strings (not ints) because `full` is a valid cell. Each numeric token must
    parse as a positive int; `full` is the only allowed non-numeric.
    """
    out: list[str] = []
    for tok in (s.strip() for s in spec.split(",")):
        if not tok:
            continue
        if tok == FULL_SENTINEL:
            out.append(tok)
        else:
            n = int(tok)  # raises ValueError on garbage — caller surfaces it
            if n <= 0:
                raise ValueError(f"pool size must be > 0, got {n}")
            out.append(str(n))
    if not out:
        raise ValueError("at least one pool size is required")
    return out


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — same formula as dmcp.curves.proportion_ci."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _cell_metrics(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    passed = sum(1 for r in rows if r.get("passed"))
    sae = sum(1 for r in rows if r.get("had_sae"))
    acc_lo, acc_hi = _wilson(passed, n)
    sae_lo, sae_hi = _wilson(sae, n)
    return {
        "n": n,
        "passed": passed,
        "accuracy": (passed / n) if n else 0.0,
        "accuracy_ci": [acc_lo, acc_hi],
        "sae": sae,
        "sae_rate": (sae / n) if n else 0.0,
        "sae_ci": [sae_lo, sae_hi],
    }


def aggregate_sweep(cells: dict[str, list[dict]]) -> dict[str, Any]:
    """Compose per-pool-size cell metrics into the sweep payload.

    `cells` keys are pool-size labels ("4", "8", ..., "full"); rows are
    EvaluationResult dicts. Output rows are sorted by numeric size with
    "full" pinned last (it's the no-distractor ceiling, conceptually
    "infinite" surface relative to the sweep).
    """

    def order(label: str) -> tuple[int, int]:
        if label == FULL_SENTINEL:
            return (1, 0)  # tail
        return (0, int(label))

    points: list[dict[str, Any]] = []
    for label in sorted(cells, key=order):
        metrics = _cell_metrics(cells[label])
        metrics["pool_size"] = label
        points.append(metrics)
    return {"points": points, "n_cells": len(points)}


def _render_markdown(agg: dict[str, Any], *, model: str, specs_label: str) -> str:
    pts = agg["points"]
    if not pts:
        return "# Tool-scaling sweep\n\n_No EvaluationResult rows found._\n"
    lines = [
        "# Tool-scaling sweep",
        "",
        f"model = `{model}` specs = `{specs_label}` n_cells = {agg['n_cells']}",
        "",
        "| pool_size | n | accuracy [95% CI] | SAE rate [95% CI] |",
        "|---|---|---|---|",
    ]
    for p in pts:
        alo, ahi = p["accuracy_ci"]
        slo, shi = p["sae_ci"]
        lines.append(
            f"| {p['pool_size']} | {p['n']} | "
            f"{p['accuracy'] * 100:.1f}% [{alo * 100:.1f}-{ahi * 100:.1f}] | "
            f"{p['sae_rate'] * 100:.1f}% [{slo * 100:.1f}-{shi * 100:.1f}] |"
        )
    return "\n".join(lines) + "\n"


def _eval_cmd(
    *,
    specs: Path,
    manifest: Path,
    model: str,
    reference_traces: Path,
    pool_label: str,
    p_alt: float,
    budget: int,
    repeat: int,
    out_path: Path,
) -> list[str]:
    """Build the `dmcp eval` invocation for one pool-size cell.

    `pool_label="full"` flips `--pool full` and drops `--pool-size`/`--p-alt`;
    numeric labels use `--pool target` with the size + alternative density.
    """
    cmd = [
        DMCP,
        "eval",
        str(specs),
        "-m",
        str(manifest),
        "--model",
        model,
        "--replay",
        "--reference-traces",
        str(reference_traces),
        "--budget",
        str(budget),
        "--repeat",
        str(repeat),
        "-o",
        str(out_path),
    ]
    if pool_label == FULL_SENTINEL:
        cmd += ["--pool", "full"]
    else:
        cmd += [
            "--pool",
            "target",
            "--pool-size",
            str(pool_label),
            "--p-alt",
            str(p_alt),
        ]
    return cmd


def _run_cell(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True, help="TaskSpec JSONL")
    ap.add_argument("--reference-traces", required=True, help="Reference traces JSONL for replay")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--model", required=True, help="Candidate model id (single model per sweep)")
    ap.add_argument(
        "--pool-sizes",
        default=DEFAULT_POOL_SIZES,
        help="Comma-separated pool-size sweep (use 'full' for the no-distractor ceiling).",
    )
    ap.add_argument(
        "--p-alt", type=float, default=0.5, help="P_alt for target-pool cells (ignored for full)."
    )
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument("--repeat", type=int, default=1, help="pass^k repetitions per spec.")
    ap.add_argument("--out", default="reports/tool_scaling", help="Output directory for per-cell evals.")
    ap.add_argument("--report", default=None, help="Markdown report path (default <out>/tool_scaling.md).")
    ap.add_argument("--json", default=None, help="Numbers JSON path (paper renderer input).")
    ap.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip the dmcp eval dispatch; aggregate over existing eval_pool*.jsonl files only.",
    )
    a = ap.parse_args()

    sizes = _parse_sizes(a.pool_sizes)
    specs = Path(a.specs)
    manifest = Path(a.manifest)
    reference_traces = Path(a.reference_traces)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cells: dict[str, list[dict]] = {}
    for label in sizes:
        eval_path = out_dir / f"eval_pool{label}.jsonl"
        if not a.skip_eval:
            cmd = _eval_cmd(
                specs=specs,
                manifest=manifest,
                model=a.model,
                reference_traces=reference_traces,
                pool_label=label,
                p_alt=a.p_alt,
                budget=a.budget,
                repeat=a.repeat,
                out_path=eval_path,
            )
            rc = _run_cell(cmd)
            if rc != 0:
                print(f"[warn] cell pool_size={label} exited {rc}; continuing", flush=True)
        cells[label] = _read_jsonl(eval_path)

    agg = aggregate_sweep(cells)
    md = _render_markdown(agg, model=a.model, specs_label=specs.name)

    report_path = Path(a.report) if a.report else (out_dir / "tool_scaling.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")
    print(f"wrote {report_path}")

    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": a.model, "specs": specs.name, **agg}
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {jp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
