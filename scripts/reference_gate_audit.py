#!/usr/bin/env python3
"""Audit a corpus against the reference-validation gate (E9.10) — deterministic, no LLM.

The gate (``dmcp.evaluator.reference_unsatisfied_checkpoints``) asks one question of
every spec: *does the exploration that claims to have solved this task actually produce
every effect the task requires?* This script applies it to a whole corpus, classifies
each failure by cause, and — when leaderboard verdicts are supplied — measures what the
flagged tasks do to reported results.

Failure buckets (a spec takes the worst bucket among its failed checkpoints):

* ``tool_effect``      — a required tool was never called, or called with args the
  checkpoint's predicate rejects. Already filtered by ``scripts/clean_corpus.py``.
* ``value_nowhere``    — a required value appears in no successful call result and in
  no final message: the effect was never produced at all.
* ``value_misscoped``  — the value exists in the reference, but not in the location the
  checkpoint scopes it to (e.g. demanded of the final message, present only in a tool
  result, or split across two results when one is required to carry it all).
* ``no_final_message`` — the checkpoint scopes to the final assistant message and the
  trace records none; the reference status is unknowable rather than wrong.

Usage:

  uv run python scripts/reference_gate_audit.py \\
      --specs hfdl/specs.jsonl --traces hfdl/traces.jsonl \\
      --verdicts hfdl/leaderboard_api/verdicts \\
      --out docs/experiments/e9.10_numbers.json

Scope of v0 / out of scope: reports, never mutates. Dropping the flagged specs is
``scripts/clean_corpus.py``; rejecting them at birth is the gate in ``dmcp generate``.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path

from dmcp.evaluator import (
    _eval_checkpoint,
    _final_assistant_message,
    _render_step_result,
    _value_predicate_matches,
)
from dmcp.spec import TaskSpec, ValueProducedCheckpoint
from dmcp.trace import StepKind, StepStatus, Trace

BUCKET_ORDER = ["tool_effect", "value_nowhere", "value_misscoped", "no_final_message"]


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - margin) / denom * 100, (centre + margin) / denom * 100)


def _load_traces(path: Path) -> dict[str, Trace]:
    out: dict[str, Trace] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                t = Trace.model_validate_json(line)
            except Exception:
                continue
            out[str(t.trace_id)] = t
    return out


def classify(spec: TaskSpec, ref: Trace) -> str | None:
    """Worst bucket among the spec's reference-unsatisfied checkpoints, None if clean."""
    calls = [s for s in ref.steps if s.kind is StepKind.call_tool_agent]
    ok = [s for s in calls if s.status is StepStatus.success]
    final = _final_assistant_message(ref)
    everywhere = "\n".join(_render_step_result(s) for s in ok) + "\n" + final
    seen: set[str] = set()
    for cp in spec.checkpoints:
        if _eval_checkpoint(cp, calls, ref).passed:
            continue
        if not isinstance(cp, ValueProducedCheckpoint):
            seen.add("tool_effect")
        elif cp.scope == "final_assistant_message" and not final:
            seen.add("no_final_message")
        elif _value_predicate_matches(cp.predicate, everywhere):
            seen.add("value_misscoped")
        else:
            seen.add("value_nowhere")
    for b in BUCKET_ORDER:
        if b in seen:
            return b
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit a corpus against the reference-validation gate.")
    ap.add_argument("--specs", required=True, type=Path)
    ap.add_argument("--traces", required=True, type=Path)
    ap.add_argument("--verdicts", type=Path, default=None, help="dir of per-model verdict jsonl (optional)")
    ap.add_argument("--out", type=Path, default=None, help="numbers JSON")
    a = ap.parse_args()

    traces = _load_traces(a.traces)
    buckets: dict[str, str | None] = {}
    orphan = 0
    with a.specs.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            spec = TaskSpec.model_validate_json(line)
            ref = traces.get(str(spec.source_trace_id))
            if ref is None:
                orphan += 1
                continue
            buckets[str(spec.task_id)] = classify(spec, ref)

    counts = collections.Counter(b or "clean" for b in buckets.values())
    total = len(buckets)
    flagged = total - counts["clean"]
    print(f"specs audited: {total}  (orphan, no reference trace: {orphan})")
    print(f"reference-consistent : {counts['clean']} ({counts['clean'] / total:.1%})")
    print(f"flagged by the gate  : {flagged} ({flagged / total:.1%})")
    for b in BUCKET_ORDER:
        if counts[b]:
            print(f"  {b:<17}: {counts[b]:>4} ({counts[b] / total:.1%})")

    numbers: dict[str, object] = {
        "specs_audited": total,
        "orphan_specs": orphan,
        "reference_consistent": counts["clean"],
        "flagged": flagged,
        "by_bucket": {b: counts[b] for b in BUCKET_ORDER if counts[b]},
    }

    if a.verdicts is not None:
        runs: dict[str, list[bool]] = collections.defaultdict(list)
        per_model: dict[tuple[str, str], list[bool]] = collections.defaultdict(list)
        for p in sorted(a.verdicts.glob("*.jsonl")):
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    runs[r["task_id"]].append(bool(r["passed"]))
                    per_model[(r["candidate_model"], r["task_id"])].append(bool(r["passed"]))
        scored = [t for t in runs if t in buckets]
        clean_ids = {t for t in scored if buckets[t] is None}
        flagged_ids = {t for t in scored if buckets[t] is not None}
        models = sorted({m for m, _ in per_model})

        print(f"\nevaluation slice: {len(scored)} tasks, {len(models)} models")
        print(f"{'group':<12} {'tasks':>6} {'runs':>7} {'pass':>7} {'never solved':>14} {'95% CI':>16}")
        wall = {}
        for name, ids in (("consistent", clean_ids), ("flagged", flagged_ids)):
            nruns = sum(len(runs[t]) for t in ids)
            npass = sum(sum(runs[t]) for t in ids)
            never = sum(1 for t in ids if not any(runs[t]))
            lo, hi = _wilson(never, len(ids))
            wall[name] = {"tasks": len(ids), "runs": nruns, "pass_rate": npass / nruns * 100, "never": never}
            print(
                f"{name:<12} {len(ids):>6} {nruns:>7} {npass / nruns:>6.1%} "
                f"{never / len(ids):>13.1%} {f'[{lo:.1f}, {hi:.1f}]':>16}"
            )
        total_never = sum(1 for t in scored if not any(runs[t]))
        print(
            f"never-solved wall: {total_never}/{len(scored)} = {total_never / len(scored):.1%}; "
            f"flagged tasks are {len(flagged_ids) / len(scored):.1%} of the slice and "
            f"{wall['flagged']['never'] / total_never:.1%} of the wall"
        )

        def rate(model: str, ids: set[str]) -> tuple[float, float]:
            res = [(t, per_model[(model, t)]) for t in ids if (model, t) in per_model]
            runs_ = sum(len(r) for _, r in res)
            ok = sum(sum(r) for _, r in res)
            p3 = sum(1 for _, r in res if len(r) >= 3 and all(r))
            return (ok / runs_ * 100 if runs_ else 0.0, p3 / len(res) * 100 if res else 0.0)

        print(f"\n{'model':<34} {'pass all':>9} {'pass kept':>10} {'p^3 all':>9} {'p^3 kept':>9}")
        rows = []
        for m in models:
            a_rate, a_p3 = rate(m, set(scored))
            c_rate, c_p3 = rate(m, clean_ids)
            rows.append(
                {"model": m, "pass_all": a_rate, "pass_kept": c_rate, "p3_all": a_p3, "p3_kept": c_p3}
            )
            print(f"{m:<34} {a_rate:>8.1f} {c_rate:>9.1f} {a_p3:>8.1f} {c_p3:>8.1f}")
        same_rate = [r["model"] for r in sorted(rows, key=lambda r: -r["pass_all"])] == [
            r["model"] for r in sorted(rows, key=lambda r: -r["pass_kept"])
        ]
        same_p3 = [r["model"] for r in sorted(rows, key=lambda r: -r["p3_all"])] == [
            r["model"] for r in sorted(rows, key=lambda r: -r["p3_kept"])
        ]
        print(f"\nranking preserved (pass): {same_rate}   (pass^3): {same_p3}")
        numbers["evaluation_slice"] = {
            "tasks": len(scored),
            "models": len(models),
            "wall": wall,
            "never_solved_total": total_never,
            "per_model": rows,
            "ranking_preserved_pass": same_rate,
            "ranking_preserved_pass3": same_p3,
        }

    if a.out is not None:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(numbers, indent=1), encoding="utf-8")
        print(f"\nnumbers -> {a.out}")


if __name__ == "__main__":
    main()
