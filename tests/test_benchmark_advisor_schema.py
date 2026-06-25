"""Schema tests for the Benchmark Advisor v1 contract layer (BA1.1 / T01).

These exercise structural validation only — no planner/validator/statistics logic.
Valid example payloads are built inline (golden fixtures proper land in T08).
"""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from benchmark_advisor import schema as S
from benchmark_advisor.schema import (
    GUIDE_VERSION,
    REPORT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AdvisorResponse,
    ExportConfig,
    ValidationReportStub,
    response_state_violations,
)

# --- inline valid payloads -----------------------------------------------------


def _guide_ref(rule_id: str = "G5.criterion.paired_bootstrap", role: str = "criterion_choice") -> dict:
    return {
        "guide_version": "statistical_guide.v1",
        "rule_id": rule_id,
        "section": "G5 - Criterion Selection",
        "role": role,
    }


def _criterion() -> dict:
    return {
        "criterion_id": "criterion.primary_power",
        "purpose": "Detect a meaningful difference in effect pass rate.",
        "estimand": "paired difference in effect pass rate",
        "null_hypothesis": "no difference between A and B",
        "alternative_hypothesis": "A differs from B",
        "primary_metric": "pairwise_delta_pp",
        "test_family": "paired_bootstrap",
        "alpha": 0.05,
        "beta_or_target_power": 0.8,
        "minimum_detectable_effect_pp": 5.0,
        "required_data": ["per_task_effect_pass"],
        "decision_rule": "reject null if the paired bootstrap CI excludes 0",
        "allowed_claim": "A differs from B on this planned distribution",
        "failure_modes": ["underpowered if task_budget is too small"],
        "confirmatory": True,
        "guide_references": [_guide_ref()],
        "selection_rationale": "the primary question is a pairwise model selection",
    }


def _distribution() -> dict:
    return {
        "short_chain": 0.3,
        "medium_chain": 0.4,
        "long_chain": 0.3,
        "cross_server_ratio": 0.35,
        "recovery_required_ratio": 0.1,
        "prerequisite_strict_ratio": 0.2,
        "stateful_write_ratio": 0.0,
        "categories": ["finance"],
        "distractors": {
            "same_name_fraction": 0.1,
            "near_miss_fraction": 0.1,
            "cross_domain_fraction": 0.0,
            "random_fraction": 0.0,
        },
        "diagnostic_slices": [
            {"slice_id": "slice.cross_server", "label": "cross-server", "ratio": 0.35, "confirmatory": False}
        ],
    }


def _analysis_plan() -> dict:
    return {
        "ci_method": "wilson_score",
        "mde_method": "normal_approx_two_proportion",
        "rank_stability_method": "not_applicable",
        "pairwise_test": "paired_bootstrap",
        "alpha": 0.05,
        "beta": 0.2,
        "planning_assumptions": ["assumed base effect-pass rate near 0.4"],
        "heuristic_label": "planning_heuristic",
    }


def _hypotheses() -> dict:
    return {"null": "no difference", "alternative": "A differs from B", "non_inferiority_margin_pp": None}


def _design() -> dict:
    return {
        "evaluation_question": "Which of two agents is better on long finance workflows?",
        "mode": "pairwise",
        "claim_scope": "confirmatory_model_selection",
        "candidate_models": ["qwen3.7-max", "glm-5.1"],
        "task_budget": 120,
        "attempts_per_task": 3,
        "target_detectable_effect_pp": 5.0,
        "estimand": "paired difference in effect pass rate",
        "hypotheses": _hypotheses(),
        "criteria": [_criterion()],
        "task_distribution": _distribution(),
        "analysis_plan": _analysis_plan(),
        "claim_boundary": "Applies only to the planned distribution; not a universal ranking.",
        "intent_evidence": ["user asked to compare two agents on finance workflows"],
        "statistical_guide_version": "statistical_guide.v1",
    }


def _generation_knobs() -> dict:
    return {
        "handoff_target": "scripts/build_corpus.py",
        "dry_run_only": True,
        "goal_strategy": "deployment_slice",
        "max_tool_calls_per_task": 6,
        "server_scope": ["finance-api"],
        "sandbox_required": False,
        "generation_notes": ["dry run only; no generation launched"],
    }


def _export_config() -> dict:
    dist = _distribution()
    return {
        "schema_version": "benchmark_advisor.v1",
        "mode": "pairwise",
        "candidate_models": ["qwen3.7-max", "glm-5.1"],
        "evaluation_question": "Which of two agents is better on long finance workflows?",
        "estimand": "paired difference in effect pass rate",
        "hypotheses": _hypotheses(),
        "criteria": [_criterion()],
        "tasks": 120,
        "attempts_per_task": 3,
        "task_distribution": dist,
        "distractors": dist["distractors"],
        "analysis_plan": _analysis_plan(),
        "warnings": [],
        "claim_boundary": "Applies only to the planned distribution; not a universal ranking.",
        "generation_knobs": _generation_knobs(),
    }


def _outcome_tensor() -> dict:
    return {
        "shape": "X[task, model, attempt, metric, slice]",
        "task_axis": "task id, spec schema version, complexity profile, and slice labels",
        "model_axis": "candidate model label and provider family",
        "attempt_axis": "zero-based attempt index and deterministic replay seed if used",
        "metric_axis": "allowed metric labels from primary_metric",
        "slice_axis": "all plus diagnostic slice ids",
        "missingness_policy": "explicit_null_with_reason",
        "stage_2_only": True,
    }


def _report_stub() -> dict:
    return {
        "schema_version": "benchmark_advisor.report.v1",
        "implemented": False,
        "outcome_tensor": _outcome_tensor(),
        "supported_future_questions": [
            "models_above_success_threshold",
            "pairwise_win_probability",
            "rank_stability",
            "slice_failure_diagnostics",
        ],
    }


def _evidence_entry() -> dict:
    return {
        "parameter": "task_distribution.cross_server_ratio",
        "value": 0.35,
        "intent_evidence": "the request emphasizes cross-server composition",
        "statistical_rationale": "allocate a cross-server slice per G3 coverage rules",
        "guide_references": [_guide_ref("G3.coverage.cross_server", "distribution_choice")],
        "hover_text": "Cross-server slice raised because the request emphasizes composition.",
        "judge_validation_hint": "check the rationale cites a G3 coverage rule",
        "validator_status": "approved",
        "repair_suggestion": None,
    }


def _approved_response() -> dict:
    return {
        "schema_version": "benchmark_advisor.v1",
        "status": "approved",
        "design": _design(),
        "warnings": [],
        "refusal": None,
        "clarification": None,
        "evidence_ledger": [_evidence_entry()],
        "export_config": _export_config(),
        "validation_report_stub": _report_stub(),
    }


# --- tests ---------------------------------------------------------------------


def test_version_constants_match_contract():
    assert SCHEMA_VERSION == "benchmark_advisor.v1"
    assert REPORT_SCHEMA_VERSION == "benchmark_advisor.report.v1"
    assert GUIDE_VERSION == "statistical_guide.v1"


def test_valid_response_parses_and_satisfies_state_matrix():
    resp = AdvisorResponse.model_validate(_approved_response())
    assert resp.status == "approved"
    assert resp.design is not None
    assert response_state_violations(resp) == []


def test_unknown_top_level_field_fails():
    bad = _approved_response()
    bad["surprise"] = 1
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_unknown_nested_field_fails():
    bad = _approved_response()
    bad["design"]["surprise"] = 1
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_required_field_is_enforced():
    bad = _approved_response()
    del bad["design"]["evaluation_question"]
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_nullable_required_field_must_be_present_not_absent():
    # absent != null: omitting a nullable-required field is an error...
    bad = _approved_response()
    del bad["design"]["target_detectable_effect_pp"]
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)
    # ...but an explicit null is accepted.
    ok = _approved_response()
    ok["design"]["target_detectable_effect_pp"] = None
    AdvisorResponse.model_validate(ok)


def test_enum_registry_rejects_unknown_value():
    bad = _approved_response()
    bad["design"]["mode"] = "tournament"
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_ratio_and_percent_bounds_enforced():
    bad = _approved_response()
    bad["design"]["task_distribution"]["cross_server_ratio"] = 1.5
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_count_ge_one_enforced():
    bad = _approved_response()
    bad["design"]["task_budget"] = 0
    with pytest.raises(ValidationError):
        AdvisorResponse.model_validate(bad)


def test_export_config_round_trips_through_json():
    cfg = ExportConfig.model_validate(_export_config())
    as_json = cfg.model_dump_json()
    reloaded = ExportConfig.model_validate(json.loads(as_json))
    assert reloaded == cfg


def test_guide_refs_and_hover_rationale_round_trip():
    resp = AdvisorResponse.model_validate(_approved_response())
    reloaded = AdvisorResponse.model_validate(json.loads(resp.model_dump_json()))
    entry = reloaded.evidence_ledger[0]
    assert entry.hover_text.startswith("Cross-server slice raised")
    assert entry.guide_references[0].rule_id == "G3.coverage.cross_server"
    assert entry.guide_references[0].guide_version == "statistical_guide.v1"


def test_validation_report_stub_present_but_not_implemented():
    stub = ValidationReportStub.model_validate(_report_stub())
    assert stub.implemented is False
    assert stub.outcome_tensor.stage_2_only is True
    # implemented must be the literal False — true is a contract violation.
    bad = _report_stub()
    bad["implemented"] = True
    with pytest.raises(ValidationError):
        ValidationReportStub.model_validate(bad)


def test_state_matrix_flags_missing_export_on_approved():
    resp = AdvisorResponse.model_validate(_approved_response())
    broken = resp.model_copy(update={"export_config": None})
    violations = response_state_violations(broken)
    assert any("export_config" in m for m in violations)


def test_state_matrix_flags_warning_without_warning_cards():
    data = _approved_response()
    data["status"] = "warning"  # but warnings list is empty
    resp = AdvisorResponse.model_validate(data)
    violations = response_state_violations(resp)
    assert any("warning" in m for m in violations)


def test_state_matrix_ok_for_refused_and_clarification():
    refused = {
        "schema_version": "benchmark_advisor.v1",
        "status": "refused",
        "design": None,
        "warnings": [],
        "refusal": {
            "code": "insufficient_budget",
            "reason": "too few tasks for a confirmatory model-selection claim",
            "statistical_reason": "planned MDE exceeds the requested detectable effect",
            "failed_criterion_id": "criterion.primary_power",
            "repair_options": ["increase task_budget", "frame as a smoke test"],
        },
        "clarification": None,
        "evidence_ledger": [],
        "export_config": None,
        "validation_report_stub": _report_stub(),
    }
    clar = {
        "schema_version": "benchmark_advisor.v1",
        "status": "needs_clarification",
        "design": None,
        "warnings": [],
        "refusal": None,
        "clarification": {
            "missing_fields": ["mode"],
            "questions": ["Do you want to compare two models or rank several?"],
            "why_needed": "the intent does not pin down a single primary question",
        },
        "evidence_ledger": [],
        "export_config": None,
        "validation_report_stub": _report_stub(),
    }
    assert response_state_violations(AdvisorResponse.model_validate(refused)) == []
    assert response_state_violations(AdvisorResponse.model_validate(clar)) == []


def test_refused_response_cannot_carry_export_config():
    data = {
        "schema_version": "benchmark_advisor.v1",
        "status": "refused",
        "design": None,
        "warnings": [],
        "refusal": {
            "code": "unsupported_final_answer_claim",
            "reason": "final-answer grading is not an allowed metric",
            "statistical_reason": "the benchmark scores effects, not answers",
            "failed_criterion_id": "criterion.primary_power",
            "repair_options": ["choose an effect-based metric"],
        },
        "clarification": None,
        "evidence_ledger": [],
        "export_config": _export_config(),  # contract violation for refused
        "validation_report_stub": _report_stub(),
    }
    resp = AdvisorResponse.model_validate(data)
    assert any("export_config" in m for m in response_state_violations(resp))


def test_request_defaults_apply():
    req = S.AdvisorRequest.model_validate(
        {
            "schema_version": "benchmark_advisor.v1",
            "intent": "Compare two local agents on long finance workflows.",
            "mode": "pairwise",
            "task_budget": 120,
            "attempts_per_task": 3,
        }
    )
    assert req.alpha == 0.05
    assert req.beta == 0.2
    assert req.candidate_models == []
    assert req.deployment_context is None


def test_validation_request_wraps_design():
    vreq = S.AdvisorValidationRequest.model_validate(
        {"schema_version": "benchmark_advisor.v1", "design": _design(), "edited_fields": ["task_budget"]}
    )
    assert vreq.design.task_budget == 120
    assert vreq.edited_fields == ["task_budget"]


def test_deep_copy_payloads_are_independent():
    # guards the test helpers themselves: mutating one payload must not leak.
    a = _approved_response()
    b = copy.deepcopy(a)
    a["design"]["task_budget"] = 999
    assert b["design"]["task_budget"] == 120
