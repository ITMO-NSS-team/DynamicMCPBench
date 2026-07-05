"""Tests for BA5.5 post-run v2 StatisticalReport generation."""

from __future__ import annotations

import pytest

from benchmark_advisor.v2_schema import AdvisorV2DesignRequest, AdvisorV2ReportRequest, OutcomeTensor
from benchmark_advisor.v2_service import advisor_v2_design, advisor_v2_report


def _plan(mode: str, models: list[str], *, target_detectable_effect_pp: float | None = None):
    response = advisor_v2_design(
        AdvisorV2DesignRequest(
            schema_version="benchmark_advisor.v2",
            intent=f"{mode} report fixture",
            mode=mode,
            task_budget=120 if mode != "leaderboard" else 180,
            attempts_per_task=1,
            candidate_models=models,
            target_detectable_effect_pp=target_detectable_effect_pp,
        )
    )
    assert response.statistical_plan is not None
    return response.statistical_plan


def _tensor(
    *,
    tasks: list[str],
    models: list[str],
    rows: list[tuple[str, str, str, bool | float | None, str | None]],
    metric_id: str = "trace_effect_pass_rate",
    metric_metadata: dict | None = None,
    slices: list[tuple[str, str, dict]] | None = None,
) -> OutcomeTensor:
    slices = slices or [("all", "all tasks", {})]
    return OutcomeTensor.model_validate(
        {
            "schema_version": "benchmark_advisor.outcome_tensor.v2",
            "shape": "X[task, model, attempt, metric, slice]",
            "tasks": [{"axis_id": task, "label": task, "metadata": {}} for task in tasks],
            "models": [{"axis_id": model, "label": model, "metadata": {}} for model in models],
            "attempts": [{"axis_id": "attempt.0", "label": "attempt 0", "metadata": {}}],
            "metrics": [
                {
                    "axis_id": metric_id,
                    "label": metric_id,
                    "metadata": metric_metadata or {},
                }
            ],
            "slices": [
                {"axis_id": slice_id, "label": label, "metadata": metadata}
                for slice_id, label, metadata in slices
            ],
            "values": [
                {
                    "task_id": task,
                    "model_id": model,
                    "attempt_id": "attempt.0",
                    "metric_id": metric_id,
                    "slice_id": slice_id,
                    "value": value,
                    "missing_reason": missing_reason,
                }
                for task, model, slice_id, value, missing_reason in rows
            ],
        }
    )


def _full_rows(
    outcomes: dict[str, dict[str, list[bool | float | None]]],
    *,
    tasks: list[str],
    slice_id: str = "all",
    missing: dict[tuple[str, str], str] | None = None,
) -> list[tuple[str, str, str, bool | float | None, str | None]]:
    missing = missing or {}
    rows: list[tuple[str, str, str, bool | float | None, str | None]] = []
    for model, by_task in outcomes.items():
        for task, value in zip(tasks, by_task, strict=True):
            rows.append((task, model, slice_id, value, missing.get((task, model))))
    return rows


def test_pairwise_report_computes_scoped_delta_and_ci():
    tasks = ["t1", "t2", "t3", "t4"]
    tensor = _tensor(
        tasks=tasks,
        models=["model-a", "model-b"],
        rows=_full_rows(
            {
                "model-a": [True, True, False, False],
                "model-b": [True, True, True, False],
            },
            tasks=tasks,
        ),
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(
            schema_version="benchmark_advisor.v2",
            outcome_tensor=tensor,
            statistical_plan=_plan("pairwise", ["model-a", "model-b"]),
        )
    ).report

    assert report.status == "approved"
    assert report.effect_sizes[0].label == "model-b - model-a"
    assert report.effect_sizes[0].estimate_pp == pytest.approx(25.0)
    assert report.confidence_intervals[0].method == "paired_bootstrap_tasks"
    assert report.rank_stability is None
    assert "universal best-model claim" in report.not_allowed_claims


def test_leaderboard_report_computes_rank_stability():
    tasks = ["t1", "t2", "t3", "t4", "t5"]
    tensor = _tensor(
        tasks=tasks,
        models=["model-a", "model-b", "model-c"],
        rows=_full_rows(
            {
                "model-a": [True, True, True, False, False],
                "model-b": [True, True, True, True, False],
                "model-c": [True, False, False, False, False],
            },
            tasks=tasks,
        ),
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(
            schema_version="benchmark_advisor.v2",
            outcome_tensor=tensor,
            statistical_plan=_plan("leaderboard", ["model-a", "model-b", "model-c"]),
        )
    ).report

    assert report.mode == "leaderboard"
    assert report.status == "approved"
    assert report.rank_stability is not None
    assert report.rank_stability.method == "bootstrap_tasks_within_strata"
    assert report.rank_stability.stable_top_k >= 1
    assert "top-1 retention" in report.rank_stability.summary
    assert report.effect_sizes[0].label == "model-b pass rate"


def test_regression_report_respects_non_inferiority_margin():
    tasks = ["t1", "t2", "t3", "t4", "t5"]
    tensor = _tensor(
        tasks=tasks,
        models=["baseline", "candidate"],
        rows=_full_rows(
            {
                "baseline": [True, True, True, False, False],
                "candidate": [True, True, True, False, False],
            },
            tasks=tasks,
        ),
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(
            schema_version="benchmark_advisor.v2",
            outcome_tensor=tensor,
            statistical_plan=_plan(
                "regression",
                ["baseline", "candidate"],
                target_detectable_effect_pp=10.0,
            ),
        )
    ).report

    assert report.mode == "regression"
    assert report.status == "approved"
    assert report.effect_sizes[0].estimate_pp == pytest.approx(0.0)
    assert report.confidence_intervals[0].low_pp == pytest.approx(0.0)
    assert "non-inferior" in report.allowed_claims[0]
    assert "post-hoc non-inferiority margin" in report.not_allowed_claims


def test_diagnostic_report_remains_descriptive():
    tasks = ["t1", "t2", "t3"]
    rows = []
    for slice_id, values in {
        "slice.same_name": [True, False, False],
        "slice.cross_server": [True, True, False],
    }.items():
        rows.extend(_full_rows({"model-a": values}, tasks=tasks, slice_id=slice_id))
    tensor = _tensor(
        tasks=tasks,
        models=["model-a"],
        rows=rows,
        metric_metadata={"advisor_mode": "diagnostic"},
        slices=[
            ("slice.same_name", "same-name failures", {}),
            ("slice.cross_server", "cross-server failures", {}),
        ],
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(schema_version="benchmark_advisor.v2", outcome_tensor=tensor)
    ).report

    assert report.mode == "diagnostic"
    assert report.status == "approved"
    assert report.effect_sizes == []
    assert report.confidence_intervals == []
    assert len(report.slice_diagnostics) == 2
    assert "broad model-selection claim" in report.not_allowed_claims


def test_missing_outcomes_are_explicit_and_affect_status():
    tasks = ["t1", "t2", "t3", "t4"]
    tensor = _tensor(
        tasks=tasks,
        models=["model-a", "model-b"],
        rows=_full_rows(
            {
                "model-a": [True, True, False, False],
                "model-b": [True, True, True, None],
            },
            tasks=tasks,
            missing={("t4", "model-b"): "tool timeout"},
        ),
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(
            schema_version="benchmark_advisor.v2",
            outcome_tensor=tensor,
            statistical_plan=_plan("pairwise", ["model-a", "model-b"]),
        )
    ).report

    assert report.status == "warning"
    assert report.missingness.missing_count == 1
    assert report.missingness.reasons == {"tool timeout": 1}
    assert any(issue.code == "missing_outcomes_present" for issue in report.issues)


def test_multiplicity_notes_are_present_for_multiple_confirmatory_slices():
    tasks = ["t1", "t2"]
    rows = []
    for slice_id in ("slice.primary_a", "slice.primary_b"):
        rows.extend(
            _full_rows(
                {
                    "model-a": [True, False],
                    "model-b": [True, True],
                },
                tasks=tasks,
                slice_id=slice_id,
            )
        )
    tensor = _tensor(
        tasks=tasks,
        models=["model-a", "model-b"],
        rows=rows,
        slices=[
            ("slice.primary_a", "primary A", {"confirmatory": True}),
            ("slice.primary_b", "primary B", {"confirmatory": True}),
        ],
    )

    report = advisor_v2_report(
        AdvisorV2ReportRequest(schema_version="benchmark_advisor.v2", outcome_tensor=tensor)
    ).report

    assert report.status == "approved"
    assert report.multiplicity.confirmatory_tests == 2
    assert "Holm" in report.multiplicity.policy
    assert "2 confirmatory tests" in report.multiplicity.note
