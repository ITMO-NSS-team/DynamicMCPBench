"""RQ1 comparison harness: answer-match vs trace/effect alignment (E4.4).

The headline DynamicMCPBench scorer is trace/effect alignment — see
`evaluator.py`. RQ1 asks: if you score the same agents the *other* way
(final-answer string match against the reference's final message — the
shape prior work uses), do you get the same ranking? The answer matters
because the headline AGB-style critique is "GT tool lists are noisy" — RQ1
is the matching critique for the answer side: "final-answer scoring is
noisy under live data, so rankings move when the world moves."

This harness aggregates per-(model, task) decisions from both scorers and
reports:

  - per-model accuracy under each scorer,
  - **Kendall's τ** between the two model rankings (instability ⇒ τ < 1),
  - **false-fail rate** (trace-align passed AND answer-match failed) —
    the candidate did the right things but its wording diverged,
  - **false-pass rate** (trace-align failed AND answer-match passed) —
    the candidate parroted the right words without doing the work,
  - **over-time stability** across multiple eval runs of the same model
    (Kendall's τ between per-spec pass vectors across run instances).

Inputs are existing on-disk artifacts: a model's `EvaluationResult` JSONL
(from `dmcp eval`) for the trace-align decision, the model's candidate
`Trace` JSONL for the candidate's `final_assistant_message`, and the
reference `Trace` JSONL for the reference's `final_assistant_message`.
No new LLM calls are required.

Per `memory/feedback_agb_orthogonality.md` and the hard invariants in
CLAUDE.md, this module is comparison-only — the answer-match scorer is
NEVER imported by `evaluator.py` or `judge.py`. Its only consumer is this
harness and the `dmcp rq1-compare` CLI.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dmcp.baselines.answer_match import (
    DEFAULT_THRESHOLD,
    AnswerMatchResult,
    score_answer,
)
from dmcp.evaluator import EvaluationResult

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerSpecDecision:
    """One (model, spec) cell — both scorer verdicts side-by-side."""

    model: str
    task_id: str
    trace_pass: bool
    answer_pass: bool
    jaccard: float
    substring_hit: bool


@dataclass(frozen=True)
class ModelSummary:
    model: str
    n_tasks: int
    trace_accuracy: float
    answer_accuracy: float
    false_fail_rate: float  # trace=T, answer=F
    false_pass_rate: float  # trace=F, answer=T
    agreement_rate: float


@dataclass
class RQ1Report:
    threshold: float
    per_spec: list[PerSpecDecision] = field(default_factory=list)
    models: list[ModelSummary] = field(default_factory=list)
    kendall_tau_rankings: float | None = None
    overall_false_fail_rate: float = 0.0
    overall_false_pass_rate: float = 0.0
    overall_agreement_rate: float = 1.0
    over_time_stability: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class RQ1Error(ValueError):
    pass


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_evals(path: Path) -> list[EvaluationResult]:
    return [EvaluationResult.model_validate(d) for d in _iter_jsonl(path)]


def _final_message_from_trace_dict(d: dict[str, Any]) -> str | None:
    exploration = (d.get("seed_metadata") or {}).get("exploration") or {}
    msg = exploration.get("final_message")
    return msg if isinstance(msg, str) else None


def load_candidate_final_messages(path: Path) -> dict[str, str]:
    """Map candidate `trace_id` → final assistant message.

    Indexed by trace_id rather than task_id because one task can have many
    candidate runs (pass^k).
    """
    out: dict[str, str] = {}
    for d in _iter_jsonl(path):
        tid = d.get("trace_id")
        if not isinstance(tid, str):
            continue
        msg = _final_message_from_trace_dict(d)
        if msg is not None:
            out[tid] = msg
    return out


def load_reference_final_messages_by_trace_id(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in _iter_jsonl(path):
        tid = d.get("trace_id")
        if not isinstance(tid, str):
            continue
        msg = _final_message_from_trace_dict(d)
        if msg is not None:
            out[tid] = msg
    return out


def load_spec_to_reference_trace(specs_path: Path) -> dict[str, str]:
    """Map `task_id` → its `source_trace_id`, so the harness can join evals to
    the right reference trace."""
    out: dict[str, str] = {}
    for d in _iter_jsonl(specs_path):
        tid = d.get("task_id")
        sid = d.get("source_trace_id")
        if isinstance(tid, str) and isinstance(sid, str):
            out[tid] = sid
    return out


# ---------------------------------------------------------------------------
# Statistics (Kendall's τ — no scipy dep)
# ---------------------------------------------------------------------------


def kendall_tau(a: list[float], b: list[float]) -> float | None:
    """Kendall's τ-b between two same-length numeric vectors.

    Returns None for vectors shorter than 2 (τ is undefined). Ties are
    handled with the τ-b correction so two ranks tied in both vectors do
    not penalize the score.
    """
    n = len(a)
    if n != len(b):
        raise RQ1Error("Kendall tau: input vectors must be the same length")
    if n < 2:
        return None
    concordant = discordant = ties_a = ties_b = 0
    for i in range(n):
        for j in range(i + 1, n):
            da = a[i] - a[j]
            db = b[i] - b[j]
            if da == 0 and db == 0:
                continue
            if da == 0:
                ties_a += 1
                continue
            if db == 0:
                ties_b += 1
                continue
            if (da > 0) == (db > 0):
                concordant += 1
            else:
                discordant += 1
    total_pairs = n * (n - 1) / 2
    denom_a = total_pairs - ties_a
    denom_b = total_pairs - ties_b
    if denom_a <= 0 or denom_b <= 0:
        return None
    return (concordant - discordant) / ((denom_a * denom_b) ** 0.5)


# ---------------------------------------------------------------------------
# Core aggregation
# ---------------------------------------------------------------------------


def _score_pair(
    candidate_msg: str | None,
    reference_msg: str | None,
    threshold: float,
) -> AnswerMatchResult:
    return score_answer(candidate_msg, reference_msg, threshold=threshold)


def build_decisions(
    *,
    model: str,
    evals: list[EvaluationResult],
    candidate_final_messages: dict[str, str],
    reference_final_messages_by_trace_id: dict[str, str],
    spec_to_source_trace: dict[str, str] | None,
    threshold: float,
) -> list[PerSpecDecision]:
    """Build the per-(model, spec) decision cells for one model."""
    out: list[PerSpecDecision] = []
    for ev in evals:
        task_id = str(ev.task_id)
        cand_msg = candidate_final_messages.get(str(ev.candidate_trace_id))
        ref_trace_id = None
        if spec_to_source_trace is not None:
            ref_trace_id = spec_to_source_trace.get(task_id)
        ref_msg = reference_final_messages_by_trace_id.get(ref_trace_id) if ref_trace_id is not None else None
        res = _score_pair(cand_msg, ref_msg, threshold)
        out.append(
            PerSpecDecision(
                model=model,
                task_id=task_id,
                trace_pass=bool(ev.passed),
                answer_pass=res.passed,
                jaccard=res.jaccard,
                substring_hit=res.substring_hit,
            )
        )
    return out


def _model_summary(model: str, decisions: list[PerSpecDecision]) -> ModelSummary:
    n = len(decisions)
    if n == 0:
        return ModelSummary(model, 0, 0.0, 0.0, 0.0, 0.0, 1.0)
    trace_pass = sum(1 for d in decisions if d.trace_pass)
    answer_pass = sum(1 for d in decisions if d.answer_pass)
    false_fail = sum(1 for d in decisions if d.trace_pass and not d.answer_pass)
    false_pass = sum(1 for d in decisions if not d.trace_pass and d.answer_pass)
    agreement = sum(1 for d in decisions if d.trace_pass == d.answer_pass)
    return ModelSummary(
        model=model,
        n_tasks=n,
        trace_accuracy=trace_pass / n,
        answer_accuracy=answer_pass / n,
        false_fail_rate=false_fail / n,
        false_pass_rate=false_pass / n,
        agreement_rate=agreement / n,
    )


def aggregate_rq1(
    decisions_by_model: dict[str, list[PerSpecDecision]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    over_time_runs: dict[str, list[list[PerSpecDecision]]] | None = None,
) -> RQ1Report:
    """Build the full RQ1 report from per-model decision lists.

    `over_time_runs[model]` = list of per-spec decision lists (one per
    re-run). When present, the harness reports a per-model
    `over_time_stability` = Kendall's τ between the binary pass vectors of
    the first two runs.
    """
    per_spec: list[PerSpecDecision] = []
    models: list[ModelSummary] = []
    for model, ds in decisions_by_model.items():
        per_spec.extend(ds)
        models.append(_model_summary(model, ds))
    # Overall (all (model, spec) cells).
    n = len(per_spec)
    false_fail = sum(1 for d in per_spec if d.trace_pass and not d.answer_pass) if n else 0
    false_pass = sum(1 for d in per_spec if not d.trace_pass and d.answer_pass) if n else 0
    agreement = sum(1 for d in per_spec if d.trace_pass == d.answer_pass) if n else 0
    # Kendall's τ between the two model rankings (trace-acc vs answer-acc).
    if len(models) >= 2:
        tau = kendall_tau(
            [m.trace_accuracy for m in models],
            [m.answer_accuracy for m in models],
        )
    else:
        tau = None
    # Optional over-time stability per model.
    over_time_stability: dict[str, float] = {}
    if over_time_runs:
        for model, runs in over_time_runs.items():
            if len(runs) < 2:
                continue
            # Align by task_id; keep only specs that appear in both runs.
            by_task_a = {d.task_id: int(d.trace_pass) for d in runs[0]}
            by_task_b = {d.task_id: int(d.trace_pass) for d in runs[1]}
            common = sorted(set(by_task_a) & set(by_task_b))
            if len(common) < 2:
                continue
            vec_a = [float(by_task_a[t]) for t in common]
            vec_b = [float(by_task_b[t]) for t in common]
            t = kendall_tau(vec_a, vec_b)
            if t is not None:
                over_time_stability[model] = t

    return RQ1Report(
        threshold=threshold,
        per_spec=per_spec,
        models=sorted(models, key=lambda m: m.trace_accuracy, reverse=True),
        kendall_tau_rankings=tau,
        overall_false_fail_rate=(false_fail / n) if n else 0.0,
        overall_false_pass_rate=(false_pass / n) if n else 0.0,
        overall_agreement_rate=(agreement / n) if n else 1.0,
        over_time_stability=over_time_stability,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_pct(x: float | None, digits: int = 0) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def _fmt_tau(t: float | None) -> str:
    if t is None:
        return "—"
    return f"{t:+.3f}"


def render_markdown(report: RQ1Report, *, title: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"# {title or 'RQ1 comparison — answer-match vs trace-align (E4.4)'}")
    lines.append("")
    lines.append(
        f"_answer-match threshold_: **{report.threshold:.2f}** (token-Jaccard with substring fallback)"
    )
    lines.append("")
    if not report.models:
        lines.append("_no models supplied_")
        return "\n".join(lines) + "\n"

    # Per-model table.
    lines.append("## Per-model accuracy")
    lines.append("")
    lines.append("| model | n | trace-align acc | answer-match acc | agree | false-fail | false-pass |")
    lines.append("|---|---|---|---|---|---|---|")
    for m in report.models:
        lines.append(
            f"| `{m.model}` | {m.n_tasks} | "
            f"{_fmt_pct(m.trace_accuracy)} | {_fmt_pct(m.answer_accuracy)} | "
            f"{_fmt_pct(m.agreement_rate)} | {_fmt_pct(m.false_fail_rate)} | "
            f"{_fmt_pct(m.false_pass_rate)} |"
        )
    lines.append("")

    # Headline: ranking instability + overall disagreement.
    lines.append("## Headline")
    lines.append("")
    tau_str = _fmt_tau(report.kendall_tau_rankings)
    lines.append(f"- **Kendall's τ between rankings**: {tau_str}")
    lines.append(
        f"- **overall false-fail rate** (trace-align ✓, answer-match ✗): "
        f"{_fmt_pct(report.overall_false_fail_rate, digits=1)}"
    )
    lines.append(
        f"- **overall false-pass rate** (trace-align ✗, answer-match ✓): "
        f"{_fmt_pct(report.overall_false_pass_rate, digits=1)}"
    )
    lines.append(f"- **overall agreement rate**: {_fmt_pct(report.overall_agreement_rate, digits=1)}")
    lines.append("")

    if report.over_time_stability:
        lines.append("## Over-time stability (trace-align pass vector, run 1 vs run 2)")
        lines.append("")
        lines.append("| model | Kendall's τ |")
        lines.append("|---|---|")
        for model, tau in sorted(report.over_time_stability.items()):
            lines.append(f"| `{model}` | {_fmt_tau(tau)} |")
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines) + "\n"


def report_to_json(report: RQ1Report) -> dict[str, Any]:
    return {
        "threshold": report.threshold,
        "kendall_tau_rankings": report.kendall_tau_rankings,
        "overall_false_fail_rate": report.overall_false_fail_rate,
        "overall_false_pass_rate": report.overall_false_pass_rate,
        "overall_agreement_rate": report.overall_agreement_rate,
        "over_time_stability": dict(report.over_time_stability),
        "models": [
            {
                "model": m.model,
                "n_tasks": m.n_tasks,
                "trace_accuracy": m.trace_accuracy,
                "answer_accuracy": m.answer_accuracy,
                "false_fail_rate": m.false_fail_rate,
                "false_pass_rate": m.false_pass_rate,
                "agreement_rate": m.agreement_rate,
            }
            for m in report.models
        ],
        "notes": list(report.notes),
        "summary_stats": {
            "n_cells": len(report.per_spec),
            "mean_jaccard": (
                statistics.fmean(d.jaccard for d in report.per_spec) if report.per_spec else 0.0
            ),
        },
    }
