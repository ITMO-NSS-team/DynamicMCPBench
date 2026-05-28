"""Per-property leaderboard generator (v0 reporting primitive).

Joins one-or-more evaluation JSONL files (each tagged with a `candidate_model`)
against a specs JSONL file and emits a markdown report with:

  - per-agent overall pass rate
  - per-task pass/fail matrix
  - per-property breakdowns (dynamism, depth bucket, cross_server,
    state_coupling)

This is the v0 substrate for Phase 5's Table 2 in the rev. 3 plan (per-agent
capability profile incl. dynamism handling).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID

from dmcp.evaluator import EvaluationResult
from dmcp.spec import TaskSpec

UNKNOWN_MODEL = "<unknown>"


def _load_specs(path: Path) -> dict[UUID, TaskSpec]:
    specs: dict[UUID, TaskSpec] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            s = TaskSpec.model_validate_json(line)
            specs[s.task_id] = s
    return specs


def _load_evals(paths: list[Path]) -> list[EvaluationResult]:
    out: list[EvaluationResult] = []
    for p in paths:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(EvaluationResult.model_validate_json(line))
    return out


def _depth_bucket(d: int) -> str:
    if d <= 2:
        return "1-2"
    if d <= 4:
        return "3-4"
    return "5+"


def _fmt_pass(num: int, denom: int) -> str:
    if denom == 0:
        return "—"
    pct = (num / denom) * 100
    return f"{num}/{denom} ({pct:.0f}%)"


def _agent_key(ev) -> str:
    """The aggregation key for one candidate run: model name + eval mode."""
    model = ev.candidate_model or UNKNOWN_MODEL
    mode = ev.evaluation_mode
    if mode is None:
        return model
    return f"{model} [{mode}]"


def _short(label: str) -> str:
    """Short display form: last path segment + mode tag preserved."""
    if " [" in label:
        head, _, tail = label.partition(" [")
        return f"{head.split('/')[-1]} [{tail}"
    return label.split("/")[-1]


def aggregate_markdown(specs_path: Path, eval_paths: list[Path]) -> str:
    specs = _load_specs(specs_path)
    evals = _load_evals(eval_paths)
    if not specs:
        return "# DynamicMCPBench Report\n\n(no specs)\n"
    if not evals:
        return "# DynamicMCPBench Report\n\n(no evaluation results)\n"

    models = sorted({_agent_key(ev) for ev in evals})
    by_model_task: dict[str, dict[UUID, bool]] = defaultdict(dict)
    for ev in evals:
        by_model_task[_agent_key(ev)][ev.task_id] = ev.passed

    lines: list[str] = []
    lines.append("# DynamicMCPBench Report")
    lines.append("")
    lines.append(
        f"Generated from {len(specs)} TaskSpec(s) and {len(evals)} EvaluationResult(s) "
        f"across {len(models)} model(s)."
    )
    lines.append("")

    # ---- overall ----
    lines.append("## Overall pass rate")
    lines.append("")
    lines.append("| Model | Pass rate |")
    lines.append("|---|---|")
    for m in models:
        passed = sum(1 for v in by_model_task[m].values() if v)
        total = len(by_model_task[m])
        lines.append(f"| `{m}` | {_fmt_pass(passed, total)} |")
    lines.append("")

    # ---- per-task matrix ----
    lines.append("## Per-task results")
    lines.append("")
    header = ["task", "dynamism", "depth", "cs", "sc"] + [_short(m) for m in models]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for task_id, spec in specs.items():
        c = spec.complexity
        task_label = spec.prompt[:40] + ("…" if len(spec.prompt) > 40 else "")
        row = [
            task_label,
            spec.dynamism.value,
            str(c.trace_depth),
            "y" if c.cross_server else "n",
            "y" if c.state_coupling else "n",
        ]
        for m in models:
            v = by_model_task[m].get(task_id)
            row.append("✓" if v is True else "✗" if v is False else "·")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- by dynamism ----
    lines.append("## Pass rate by dynamism")
    lines.append("")
    dynamism_order = ["static", "live_read", "stateful_write"]
    lines.append("| Dynamism | " + " | ".join(f"`{m.split('/')[-1]}`" for m in models) + " |")
    lines.append("|" + "|".join(["---"] * (len(models) + 1)) + "|")
    for d in dynamism_order:
        ids_in_d = [tid for tid, s in specs.items() if s.dynamism.value == d]
        row = [d]
        for m in models:
            passed = sum(1 for tid in ids_in_d if by_model_task[m].get(tid) is True)
            row.append(_fmt_pass(passed, len(ids_in_d)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- by depth bucket ----
    lines.append("## Pass rate by trace depth")
    lines.append("")
    bucket_order = ["1-2", "3-4", "5+"]
    lines.append("| Depth | " + " | ".join(f"`{m.split('/')[-1]}`" for m in models) + " |")
    lines.append("|" + "|".join(["---"] * (len(models) + 1)) + "|")
    for b in bucket_order:
        ids_in_b = [tid for tid, s in specs.items() if _depth_bucket(s.complexity.trace_depth) == b]
        row = [b]
        for m in models:
            passed = sum(1 for tid in ids_in_b if by_model_task[m].get(tid) is True)
            row.append(_fmt_pass(passed, len(ids_in_b)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- by cross_server / state_coupling ----
    lines.append("## Pass rate by complexity flag")
    lines.append("")
    lines.append("| Subset | " + " | ".join(f"`{m.split('/')[-1]}`" for m in models) + " |")
    lines.append("|" + "|".join(["---"] * (len(models) + 1)) + "|")
    for label, flag_fn in [
        ("cross_server=True", lambda s: s.complexity.cross_server),
        ("cross_server=False", lambda s: not s.complexity.cross_server),
        ("state_coupling=True", lambda s: s.complexity.state_coupling),
        ("state_coupling=False", lambda s: not s.complexity.state_coupling),
    ]:
        ids = [tid for tid, s in specs.items() if flag_fn(s)]
        row = [label]
        for m in models:
            passed = sum(1 for tid in ids if by_model_task[m].get(tid) is True)
            row.append(_fmt_pass(passed, len(ids)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    return "\n".join(lines)
