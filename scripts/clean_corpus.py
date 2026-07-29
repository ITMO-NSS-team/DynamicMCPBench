#!/usr/bin/env python3
"""Drop self-inconsistent specs from a corpus (deterministic, no LLM).

A spec is *self-inconsistent* when its own gold/reference trace fails one of its
required checkpoints — a demanded tool is absent or was called with non-matching
args (``tool_effect``), or a demanded value never appears in a successful call
result (``value_produced``). A candidate can only replay the gold's world, so such
a task is unpassable by construction (the "wall" where every model fails). This
filter removes exactly those via ``dmcp.evaluator.reference_unsatisfied_checkpoints``
and writes a TSV report of what was dropped and why.

Run it on your corpus BEFORE evaluation and before merging into the shared dataset:

  uv run python scripts/clean_corpus.py \\
      --specs data/<corpus>/specs_valid.jsonl --traces data/<corpus>/traces.jsonl \\
      --out-specs data/<corpus>/specs_clean.jsonl --report data/<corpus>/dropped.tsv

``--dry-run`` reports the count + writes the report without producing cleaned specs.
Specs whose source trace is missing are kept (can't be checked) and counted separately.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dmcp.evaluator import reference_unsatisfied_checkpoints
from dmcp.spec import TaskSpec
from dmcp.trace import Trace


def _load_traces(path: Path) -> dict[str, Trace]:
    traces: dict[str, Trace] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                t = Trace.model_validate_json(line)
            except Exception:
                continue
            traces[str(t.trace_id)] = t
    return traces


def main() -> None:
    ap = argparse.ArgumentParser(description="Drop self-inconsistent (tool-absent) specs from a corpus.")
    ap.add_argument("--specs", required=True, type=Path, help="TaskSpec JSONL")
    ap.add_argument("--traces", required=True, type=Path, help="reference traces JSONL")
    ap.add_argument(
        "--out-specs", type=Path, default=None, help="cleaned specs (default: <specs>.clean.jsonl)"
    )
    ap.add_argument("--report", type=Path, default=None, help="dropped TSV (default: <specs>.dropped.tsv)")
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write cleaned specs")
    a = ap.parse_args()

    traces = _load_traces(a.traces)
    kept_lines: list[str] = []
    kept = orphan = 0
    dropped: list[tuple[str, str]] = []  # (task_id, checkpoint_ids)

    with a.specs.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            spec = TaskSpec.model_validate_json(line)
            ref = traces.get(str(spec.source_trace_id))
            if ref is None:
                orphan += 1
                kept += 1
                kept_lines.append(line if line.endswith("\n") else line + "\n")
                continue
            absent = reference_unsatisfied_checkpoints(spec, ref)
            if absent:
                dropped.append((str(spec.task_id), ",".join(absent)))
            else:
                kept += 1
                kept_lines.append(line if line.endswith("\n") else line + "\n")

    report = a.report or a.specs.with_suffix(".dropped.tsv")
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as fh:
        fh.write("task_id\tself_inconsistent_checkpoints\treason\n")
        for tid, cps in dropped:
            fh.write(f"{tid}\t{cps}\tgold trace fails this required checkpoint (effect never produced)\n")

    total = kept + len(dropped)
    print(f"[clean] specs={total} kept={kept} dropped={len(dropped)} orphan_trace={orphan}")
    print(f"[clean] dropped report -> {report}")
    if a.dry_run:
        print("[clean] dry-run: cleaned specs not written.")
        return
    out = a.out_specs or a.specs.with_suffix(".clean.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(kept_lines), encoding="utf-8")
    print(f"[clean] cleaned specs ({kept}) -> {out}")


if __name__ == "__main__":
    main()
