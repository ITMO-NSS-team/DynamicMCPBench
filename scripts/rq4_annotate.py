#!/usr/bin/env python3
"""RQ4 annotator CLI — build human-readable worksheets + ingest filled verdicts.

The `dmcp rq4-subset` harness emits a bare annotation template (one row per
task × candidate × rater with empty verdict fields). Human raters, though,
need to *read* the task prompt, the candidate agent's actual tool calls, and
its final answer to judge pass/fail. This script turns the subset + captured
candidate traces into a packet each rater can work from, and ingests their
filled answers back into the JSONL `dmcp rq4-agreement` consumes.

Two modes:

  build   subset + candidate traces + a rater roster -> per-rater Markdown
          worksheet (to read) + per-rater CSV (to fill) + the canonical
          annotation template JSONL + cells.json (the ordered cell list).

  ingest  filled per-rater CSVs -> evals/rq4_annotations.filled.jsonl
          (the AnnotationRow schema; un-filled rows are skipped).

Cell→rater assignment is a deterministic split: the ordered cell list is cut
into len(raters)//3 contiguous blocks, each annotated by a disjoint triple,
so every cell gets exactly 3 independent votes (odd -> no ties) and the human
load is evenly shared. See docs/experiments/RQ4_ANNOTATOR_GUIDE.md.

Scope: annotation instrumentation only — never touches the scorer
(CLAUDE.md hard invariant 1, memory/feedback_agb_orthogonality.md).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _final_message(trace: dict) -> str:
    exp = (trace.get("seed_metadata") or {}).get("exploration") or {}
    return str(exp.get("final_message") or "").strip()


def _render_steps(trace: dict) -> str:
    """Human-readable rendering of the candidate's agent-issued tool calls."""
    lines: list[str] = []
    n = 0
    for s in trace.get("steps") or []:
        if s.get("step_kind") != "call_tool_agent":
            continue
        n += 1
        tool = f"{s.get('server_id', '')}__{s.get('tool_name', '')}"
        args = json.dumps(s.get("arguments") or {}, ensure_ascii=False)
        if len(args) > 600:
            args = args[:600] + " …(truncated)"
        status = s.get("status", "?")
        res = s.get("result")
        res_str = json.dumps(res, ensure_ascii=False) if res is not None else ""
        if len(res_str) > 800:
            res_str = res_str[:800] + " …(truncated)"
        lines.append(f"{n}. `{tool}`\n   - args: `{args}`\n   - result [{status}]: {res_str or '—'}")
    if not lines:
        return "_(the agent made no tool calls)_"
    return "\n".join(lines)


def _triples(raters: list[str]) -> list[list[str]]:
    if len(raters) % 3 != 0:
        raise SystemExit(f"need a rater count divisible by 3 for 3-votes/cell; got {len(raters)}")
    return [raters[i : i + 3] for i in range(0, len(raters), 3)]


def build(a: argparse.Namespace) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    subset = {r["task_id"]: r for r in _load_jsonl(Path(a.subset))}
    assign = json.loads(Path(a.assignment).read_text())
    cell_order: list[str] = assign["cell_order"]

    # one candidate trace per task (its assigned model), keyed by task_id
    traces: dict[str, dict] = {}
    for ct in a.candidate_traces:
        for t in _load_jsonl(Path(ct)):
            tid = (t.get("seed_metadata") or {}).get("task_id") or t.get("task_id")
            if tid:
                traces[str(tid)] = t

    raters = a.raters
    triples = _triples(raters)
    n_blocks = len(triples)
    # contiguous block split of the ordered cell list
    cells: list[dict] = []
    for idx, tid in enumerate(cell_order):
        tr = traces.get(tid)
        if tr is None:
            continue  # no trace captured for this task — skip the cell
        block = (idx * n_blocks) // len(cell_order)
        cells.append(
            {
                "cell_id": len(cells) + 1,
                "task_id": tid,
                "candidate_trace_id": str(tr.get("trace_id") or ""),
                "candidate_model": str((tr.get("seed_metadata") or {}).get("llm_model") or ""),
                "block": block,
                "raters": triples[block],
            }
        )

    (out / "cells.json").write_text(json.dumps(cells, indent=1))

    # canonical annotation template JSONL (one row per cell × its 3 raters)
    tmpl = out / "rq4_annotations.template.jsonl"
    with tmpl.open("w", encoding="utf-8") as f:
        for c in cells:
            for rater in c["raters"]:
                f.write(
                    json.dumps(
                        {
                            "task_id": c["task_id"],
                            "candidate_trace_id": c["candidate_trace_id"],
                            "candidate_model": c["candidate_model"],
                            "rater_id": rater,
                            "verdict": "",
                            "justification": "",
                            "minutes_spent": 0.0,
                            "annotated_at": None,
                        }
                    )
                    + "\n"
                )

    # per-rater Markdown worksheet + fillable CSV
    for rater in raters:
        mine = [c for c in cells if rater in c["raters"]]
        md = [
            f"# RQ4 annotation worksheet — rater `{rater}`",
            "",
            f"You have **{len(mine)} cells**. For each: read the prompt, the agent's tool calls "
            "and their results, and its final answer, then mark **pass** or **fail** in "
            f"`rq4_annotations_{rater}.csv` (column `verdict`). See RQ4_ANNOTATOR_GUIDE.md.",
            "",
            "**pass** = the agent actually accomplished the task *as evidenced by the tool "
            "calls and results* — not just a plausible-sounding final answer.",
            "",
        ]
        for c in mine:
            sub = subset.get(c["task_id"], {})
            tr = traces[c["task_id"]]
            md += [
                f"## Cell {c['cell_id']} — `{c['task_id'][:8]}` — model `{c['candidate_model']}`",
                "",
                f"**Prompt:** {sub.get('prompt', '(missing)')}",
                "",
                "**Agent tool calls:**",
                "",
                _render_steps(tr),
                "",
                f"**Agent final answer:** {_final_message(tr) or '_(none)_'}",
                "",
                f"→ record verdict for cell {c['cell_id']} in your CSV.",
                "",
                "---",
                "",
            ]
        (out / f"rq4_worksheet_{rater}.md").write_text("\n".join(md), encoding="utf-8")

        with (out / f"rq4_annotations_{rater}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "cell_id",
                    "task_id",
                    "candidate_trace_id",
                    "candidate_model",
                    "verdict",
                    "justification",
                    "minutes_spent",
                ]
            )
            for c in mine:
                w.writerow(
                    [c["cell_id"], c["task_id"], c["candidate_trace_id"], c["candidate_model"], "", "", ""]
                )

    print(f"built {len(cells)} cells over {len(raters)} raters ({n_blocks} triples)")
    print(f"  per-rater worksheets + CSVs + template → {out}/")
    for i, tri in enumerate(triples):
        block_cells = [c for c in cells if c["block"] == i]
        print(f"  block {i}: raters {tri} → {len(block_cells)} cells")


def ingest(a: argparse.Namespace) -> None:
    rows: list[dict] = []
    skipped = 0
    for csv_path in a.csvs:
        rater = Path(csv_path).stem.replace("rq4_annotations_", "")
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                verdict = (r.get("verdict") or "").strip().lower()
                if verdict not in ("pass", "fail"):
                    skipped += 1
                    continue
                rows.append(
                    {
                        "task_id": r["task_id"],
                        "candidate_trace_id": r["candidate_trace_id"],
                        "candidate_model": r.get("candidate_model", ""),
                        "rater_id": rater,
                        "verdict": verdict,
                        "justification": r.get("justification", ""),
                        "minutes_spent": float(r["minutes_spent"]) if r.get("minutes_spent") else 0.0,
                        "annotated_at": None,
                    }
                )
    outp = Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"ingested {len(rows)} filled verdicts ({skipped} blank/invalid skipped) → {outp}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    b = sub.add_parser("build", help="build per-rater worksheets + CSVs + template")
    b.add_argument("--subset", default="evals/rq4_subset.jsonl")
    b.add_argument("--assignment", default="evals/rq4_gen/assignment.json")
    b.add_argument("--candidate-traces", nargs="+", required=True)
    b.add_argument("--raters", nargs="+", required=True, help="rater ids (count divisible by 3)")
    b.add_argument("--out", default="evals/rq4_annotation")
    b.set_defaults(func=build)

    g = sub.add_parser("ingest", help="merge filled per-rater CSVs into annotations JSONL")
    g.add_argument("csvs", nargs="+", help="filled rq4_annotations_<rater>.csv files")
    g.add_argument("--out", default="evals/rq4_annotations.filled.jsonl")
    g.set_defaults(func=ingest)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
