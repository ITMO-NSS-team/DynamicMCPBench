"""Schema tests for the additive Benchmark Advisor v2 contract layer (BA5.1 / T11)."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from benchmark_advisor import v2_schema as V2
from tests.test_benchmark_advisor_schema import (
    _design,
    _export_config,
    _guide_ref,
)


def _citation() -> dict:
    return {
        "source_id": "statistical_guide.v1",
        "title": "Benchmark Advisor statistical guide",
        "section": "G4 - Budget, Power, And Repeats",
        "evidence_status": "curated",
        "source_keys": ["Colas2018", "Bragg2021", "ProjectInterfaces2026"],
        "snippet": "Budget and power gates are planning constraints.",
        "guide_references": [_guide_ref("G4.budget.mode_thresholds", "budget_power")],
    }


def _issue() -> dict:
    return {
        "severity": "warning",
        "code": "underpowered_design",
        "message": "The requested target effect is below the planned MDE.",
        "failed_field": "target_detectable_effect_pp",
        "failed_criterion_id": "criterion.primary_power",
        "statistical_reason": "target detectable effect is smaller than the planned MDE",
        "repair_options": ["increase task_budget", "raise target_detectable_effect_pp"],
        "guide_references": [_guide_ref("G4.mde.underpowered", "budget_power")],
    }


def _assumptions() -> dict:
    return {
        "baseline_rate": 0.5,
        "paired_design": True,
        "independence_assumption": "tasks are treated as independent planning units",
        "repeated_attempts_policy": "attempts are repeated observations, not independent tasks",
        "missingness_policy": "explicit null with reason",
        "multiplicity_policy": "single primary criterion; secondary slices exploratory",
        "sensitivity_notes": ["baseline-rate sensitivity should be inspected before launch"],
        "guide_references": [_guide_ref("G4.repeats.not_independent_tasks", "budget_power")],
    }


def _power_analysis() -> dict:
    return {
        "alpha": 0.05,
        "target_power": 0.8,
        "planned_mde_pp": 18.0,
        "ci_width_pp": 16.0,
        "method": "paired_bootstrap_heuristic",
        "power_curve": [
            {"task_budget": 60, "mde_pp": 25.0, "ci_width_pp": 24.0},
            {"task_budget": 120, "mde_pp": 18.0, "ci_width_pp": 16.0},
        ],
        "budget_alternatives": [
            {"task_budget": 80, "detectable_effect_pp": 22.0, "claim_status": "warning"},
            {"task_budget": 160, "detectable_effect_pp": 15.0, "claim_status": "approved"},
        ],
        "planning_diagnostics": [
            {
                "diagnostic_id": "diagnostic.n_eff.unique_tasks",
                "label": "Effective sample size caveat",
                "value": 120,
                "unit": "unique_tasks",
                "status": "approved",
                "interpretation": "Planning uses unique tasks as the information unit.",
                "guide_references": [_guide_ref("G4.repeats.not_independent_tasks", "budget_power")],
            }
        ],
        "assumptions": _assumptions(),
    }


def _plan() -> dict:
    return {
        "schema_version": "benchmark_advisor.statistical_plan.v2",
        "design": _design(),
        "power_analysis": _power_analysis(),
        "design_alternatives": [
            {
                "alternative_id": "alt.increase_budget",
                "label": "Increase task budget",
                "task_budget": 180,
                "attempts_per_task": 3,
                "target_detectable_effect_pp": 12.0,
                "status": "approved",
                "tradeoff": "More tasks shrink the detectable effect.",
                "repair_actions": ["raise task_budget to 180"],
            }
        ],
        "assumption_ledger": _assumptions(),
        "issues": [_issue()],
        "citations": [_citation()],
        "claim_card": {
            "allowed_claims": ["difference on the planned distribution"],
            "not_allowed_claims": ["universal model ranking"],
            "plain_language_summary": "This plan supports a scoped pairwise claim.",
        },
    }


def _tensor() -> dict:
    return {
        "schema_version": "benchmark_advisor.outcome_tensor.v2",
        "shape": "X[task, model, attempt, metric, slice]",
        "tasks": [{"axis_id": "task.1", "label": "task 1", "metadata": {"complexity": "simple"}}],
        "models": [{"axis_id": "model.a", "label": "model a", "metadata": {}}],
        "attempts": [{"axis_id": "attempt.0", "label": "attempt 0", "metadata": {}}],
        "metrics": [{"axis_id": "effect_pass", "label": "effect pass", "metadata": {}}],
        "slices": [{"axis_id": "all", "label": "all tasks", "metadata": {}}],
        "values": [
            {
                "task_id": "task.1",
                "model_id": "model.a",
                "attempt_id": "attempt.0",
                "metric_id": "effect_pass",
                "slice_id": "all",
                "value": True,
                "missing_reason": None,
            }
        ],
    }


def _report() -> dict:
    return {
        "schema_version": "benchmark_advisor.report.v2",
        "mode": "pairwise",
        "status": "warning",
        "effect_sizes": [{"label": "paired delta", "estimate_pp": 12.5, "method": "paired_bootstrap"}],
        "confidence_intervals": [
            {"label": "paired delta", "low_pp": -1.0, "high_pp": 24.0, "method": "paired_bootstrap"}
        ],
        "rank_stability": None,
        "slice_diagnostics": [
            {
                "slice_id": "all",
                "label": "all tasks",
                "metric": "effect_pass",
                "estimate": 0.62,
                "interpretation": "descriptive effect-pass rate",
            }
        ],
        "missingness": {"missing_count": 0, "total_count": 1, "policy": "explicit null", "reasons": {}},
        "multiplicity": {
            "policy": "single primary criterion",
            "confirmatory_tests": 1,
            "exploratory_tests": 0,
            "note": "no multiplicity correction needed for one primary test",
        },
        "allowed_claims": ["scoped pairwise comparison"],
        "not_allowed_claims": ["universal model ranking"],
        "issues": [_issue()],
    }


def _launch_job() -> dict:
    return {
        "schema_version": "benchmark_advisor.launch_job.v2",
        "job_id": "advisor-job-1",
        "status": "queued",
        "command_preview": ["python", "scripts/build_corpus.py", "--out", "data/advisor-job-1"],
        "logs": [],
        "artifacts": {"goals": None, "specs": None, "traces": None, "coverage": None},
    }


def test_v2_version_constants():
    assert V2.V2_SCHEMA_VERSION == "benchmark_advisor.v2"
    assert V2.STATISTICAL_PLAN_SCHEMA_VERSION == "benchmark_advisor.statistical_plan.v2"
    assert V2.OUTCOME_TENSOR_SCHEMA_VERSION == "benchmark_advisor.outcome_tensor.v2"
    assert V2.STATISTICAL_REPORT_SCHEMA_VERSION == "benchmark_advisor.report.v2"
    assert V2.LAUNCH_SCHEMA_VERSION == "benchmark_advisor.launch.v2"
    assert V2.LAUNCH_JOB_SCHEMA_VERSION == "benchmark_advisor.launch_job.v2"


def test_statistical_plan_parses_and_forbids_unknown_fields():
    plan = V2.StatisticalPlan.model_validate(_plan())
    assert plan.schema_version == V2.STATISTICAL_PLAN_SCHEMA_VERSION
    assert plan.power_analysis.assumptions.paired_design is True
    assert plan.power_analysis.planning_diagnostics[0].diagnostic_id == "diagnostic.n_eff.unique_tasks"
    assert plan.citations[0].source_keys == ["Colas2018", "Bragg2021", "ProjectInterfaces2026"]
    assert plan.issues[0].repair_options

    bad = _plan()
    bad["surprise"] = True
    with pytest.raises(ValidationError):
        V2.StatisticalPlan.model_validate(bad)


def test_v2_design_route_shapes_parse_and_forbid_unknown_fields():
    req = V2.AdvisorV2DesignRequest.model_validate(
        {
            "schema_version": "benchmark_advisor.v2",
            "intent": "Compare two agents on finance workflows.",
            "mode": "pairwise",
            "task_budget": 120,
            "attempts_per_task": 3,
            "candidate_models": ["a", "b"],
            "server_scope": ["yfinance"],
        }
    )
    assert req.retrieval_mode == "local_only"
    assert req.server_scope == ["yfinance"]

    resp = V2.AdvisorV2DesignResponse.model_validate(
        {
            "schema_version": "benchmark_advisor.v2",
            "status": "warning",
            "statistical_plan": _plan(),
            "issues": [_issue()],
            "export_config": _export_config(),
            "launchable": True,
        }
    )
    assert resp.statistical_plan is not None
    assert resp.issues[0].code == "underpowered_design"

    bad = {
        "schema_version": "benchmark_advisor.v2",
        "intent": "Compare",
        "mode": "pairwise",
        "task_budget": 120,
        "attempts_per_task": 3,
        "retrieval_mode": "web",
    }
    with pytest.raises(ValidationError):
        V2.AdvisorV2DesignRequest.model_validate(bad)


def test_v2_validation_route_shape_wraps_statistical_plan():
    vreq = V2.AdvisorV2ValidationRequest.model_validate(
        {
            "schema_version": "benchmark_advisor.v2",
            "statistical_plan": _plan(),
            "edited_fields": ["task_budget", "task_distribution.short_chain"],
        }
    )
    assert vreq.edited_fields == ["task_budget", "task_distribution.short_chain"]

    vresp = V2.AdvisorV2ValidationResponse.model_validate(
        {
            "schema_version": "benchmark_advisor.v2",
            "status": "refused",
            "statistical_plan": _plan(),
            "issues": [_issue()],
            "export_config": None,
            "launchable": False,
        }
    )
    assert vresp.launchable is False


def test_nested_unknown_fields_are_rejected():
    bad = _plan()
    bad["power_analysis"]["assumptions"]["surprise"] = True
    with pytest.raises(ValidationError):
        V2.StatisticalPlan.model_validate(bad)


def test_outcome_tensor_requires_missing_reason_for_null_values():
    tensor = V2.OutcomeTensor.model_validate(_tensor())
    assert tensor.values[0].value is True

    bad = _tensor()
    bad["values"][0]["value"] = None
    with pytest.raises(ValidationError):
        V2.OutcomeTensor.model_validate(bad)

    ok = _tensor()
    ok["values"][0]["value"] = None
    ok["values"][0]["missing_reason"] = "tool timeout"
    assert V2.OutcomeTensor.model_validate(ok).values[0].missing_reason == "tool timeout"


def test_statistical_report_parses_scoped_claims():
    report = V2.StatisticalReport.model_validate(_report())
    assert report.schema_version == V2.STATISTICAL_REPORT_SCHEMA_VERSION
    assert report.allowed_claims == ["scoped pairwise comparison"]
    assert report.not_allowed_claims == ["universal model ranking"]


def test_v2_report_route_shapes_parse():
    req = V2.AdvisorV2ReportRequest.model_validate(
        {
            "schema_version": "benchmark_advisor.v2",
            "outcome_tensor": _tensor(),
            "statistical_plan": _plan(),
        }
    )
    assert req.outcome_tensor.shape == "X[task, model, attempt, metric, slice]"

    resp = V2.AdvisorV2ReportResponse.model_validate(
        {"schema_version": "benchmark_advisor.v2", "report": _report()}
    )
    assert resp.report.schema_version == V2.STATISTICAL_REPORT_SCHEMA_VERSION


def test_launch_request_requires_explicit_confirmation_literal_true():
    req = V2.LaunchRequest.model_validate(
        {
            "schema_version": "benchmark_advisor.launch.v2",
            "export_config": _export_config(),
            "confirmation": True,
            "dry_run": True,
            "requested_by_ui": True,
        }
    )
    assert req.confirmation is True

    bad = {
        "schema_version": "benchmark_advisor.launch.v2",
        "export_config": _export_config(),
        "confirmation": False,
        "dry_run": True,
        "requested_by_ui": True,
    }
    with pytest.raises(ValidationError):
        V2.LaunchRequest.model_validate(bad)


def test_launch_job_contract_parses_and_requires_command_preview():
    job = V2.LaunchJob.model_validate(_launch_job())
    assert job.status == "queued"
    assert job.artifacts.specs is None

    bad = _launch_job()
    bad["command_preview"] = []
    with pytest.raises(ValidationError):
        V2.LaunchJob.model_validate(bad)


def test_v1_payloads_still_parse_alongside_v2_contracts():
    from benchmark_advisor.schema import AdvisorDesign, ExportConfig

    AdvisorDesign.model_validate(_design())
    ExportConfig.model_validate(_export_config())


def test_fixture_helpers_are_independent():
    a = _plan()
    b = copy.deepcopy(a)
    a["power_analysis"]["planned_mde_pp"] = 99.0
    assert b["power_analysis"]["planned_mde_pp"] == 18.0
