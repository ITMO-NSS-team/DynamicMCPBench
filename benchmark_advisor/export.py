"""Benchmark Advisor export handoff (BA3.3 / T07).

Builds and validates the JSON ``ExportConfig`` that bridges an approved/warning
design to the *future* DynamicMCPBench generation pipeline. v1 is JSON-first and
strictly preview-only: ``dry_run_only`` is always ``True`` and nothing here runs
``goal-gen`` / ``explore`` / ``distill`` / ``eval``. ``tasks`` is a target
TaskSpec count, never an embedded task list.

Out of scope: launching generation, changing generation algorithms, the CLI.
"""

from __future__ import annotations

from .schema import AdvisorDesign, ExportConfig, ExportGenerationKnobs, WarningCard

# mode -> the generation goal strategy knob.
_GOAL_STRATEGY = {
    "pairwise": "deployment_slice",
    "leaderboard": "leaderboard_mix",
    "regression": "regression_replay",
    "diagnostic": "diagnostic_slice",
}


def is_exportable(status: str) -> bool:
    """Only approved/warning designs may produce an export preview."""
    return status in ("approved", "warning")


def build_export_config(
    design: AdvisorDesign,
    warnings: list[WarningCard],
    *,
    sandbox_required: bool | None = None,
    server_scope: list[str] | None = None,
) -> ExportConfig:
    """Compose an ``ExportConfig`` from a design. Warnings are preserved inside it."""
    stateful = design.task_distribution.stateful_write_ratio > 0
    sandbox = sandbox_required if sandbox_required is not None else stateful
    knobs = ExportGenerationKnobs(
        handoff_target="scripts/build_corpus.py",
        dry_run_only=True,
        goal_strategy=_GOAL_STRATEGY[design.mode],
        max_tool_calls_per_task=6,
        server_scope=server_scope or [],
        sandbox_required=sandbox,
        generation_notes=[
            "v1 preview only — no generation is launched from the advisor.",
            "`tasks` is a target TaskSpec count, not an embedded task list.",
        ],
    )
    return ExportConfig(
        schema_version="benchmark_advisor.v1",
        mode=design.mode,
        candidate_models=design.candidate_models,
        evaluation_question=design.evaluation_question,
        estimand=design.estimand,
        hypotheses=design.hypotheses,
        criteria=design.criteria,
        tasks=design.task_budget,
        attempts_per_task=design.attempts_per_task,
        task_distribution=design.task_distribution,
        distractors=design.task_distribution.distractors,
        analysis_plan=design.analysis_plan,
        warnings=warnings,
        claim_boundary=design.claim_boundary,
        generation_knobs=knobs,
    )


def export_violations(cfg: ExportConfig) -> list[str]:
    """Semantic checks beyond schema validation (empty list = ok)."""
    v: list[str] = []
    if cfg.distractors != cfg.task_distribution.distractors:
        v.append("distractors must equal task_distribution.distractors")
    if cfg.task_distribution.stateful_write_ratio > 0 and not cfg.generation_knobs.sandbox_required:
        v.append("sandbox_required must be true when stateful_write_ratio > 0")
    if not cfg.generation_knobs.dry_run_only:
        v.append("dry_run_only must be true in v1")
    return v
