"""Tests for BA5.3 guide-first v2 planner/engine composition."""

from __future__ import annotations

import pytest

from benchmark_advisor.stats import planned_mde_pp, planned_mde_pp_for_unique_tasks
from benchmark_advisor.v2_engine import run_statistical_engine
from benchmark_advisor.v2_schema import AdvisorV2DesignRequest, AdvisorV2ValidationRequest
from benchmark_advisor.v2_service import advisor_v2_design, advisor_v2_validate


def _request(**overrides) -> AdvisorV2DesignRequest:
    payload = {
        "schema_version": "benchmark_advisor.v2",
        "intent": "Compare two local agents on short step finance workflows.",
        "mode": "pairwise",
        "task_budget": 70,
        "attempts_per_task": 1,
        "candidate_models": ["agent-a", "agent-b"],
        "server_scope": ["finance-tools"],
    }
    payload.update(overrides)
    return AdvisorV2DesignRequest.model_validate(payload)


def _diagnostics_by_id(plan) -> dict[str, object]:
    return {d.diagnostic_id: d for d in plan.power_analysis.planning_diagnostics}


def test_engine_output_is_deterministic_and_contains_required_alternatives():
    request = _request()

    first = run_statistical_engine(request)
    second = run_statistical_engine(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert {a.alternative_id for a in first.design_alternatives} == {
        "alt.budget_minimum",
        "alt.recommended",
        "alt.stronger",
        "alt.narrowed_claim",
    }
    assert first.computation_trace.candidate_count == len(first.parameter_candidates)
    assert first.computation_trace.engine_version.startswith("benchmark_advisor.statistical_engine")


def test_v2_design_uses_engine_scored_parameters_and_local_citations():
    response = advisor_v2_design(_request())

    assert response.status == "approved"
    assert response.statistical_plan is not None
    plan = response.statistical_plan
    assert plan.engine_decision is not None
    assert plan.design.task_budget == 100
    assert plan.design.task_budget != 70
    assert plan.design.target_detectable_effect_pp is not None
    candidate_ids = {c.candidate_id for c in plan.engine_decision.parameter_candidates}
    assert plan.engine_decision.recommended_candidate_id in candidate_ids
    assert plan.citations
    assert all(c.source_keys for c in plan.citations)
    assert response.export_config is not None
    assert response.export_config.tasks == plan.design.task_budget
    assert response.export_config.generation_knobs.server_scope == ["finance-tools"]


def test_ba54_pairwise_attempts_do_not_multiply_iid_mde():
    one_attempt = advisor_v2_design(_request(task_budget=100, attempts_per_task=1))
    three_attempts = advisor_v2_design(_request(task_budget=100, attempts_per_task=3))
    assert one_attempt.statistical_plan is not None
    assert three_attempts.statistical_plan is not None
    one_plan = one_attempt.statistical_plan
    three_plan = three_attempts.statistical_plan

    assert one_plan.design.task_budget == three_plan.design.task_budget == 100
    assert three_plan.design.attempts_per_task == 3
    assert three_plan.power_analysis.planned_mde_pp == one_plan.power_analysis.planned_mde_pp
    assert three_plan.power_analysis.planned_mde_pp == pytest.approx(
        round(planned_mde_pp_for_unique_tasks(100), 3)
    )
    diagnostics = _diagnostics_by_id(three_plan)
    assert diagnostics["diagnostic.n_eff.unique_tasks"].value == 100
    assert "diagnostic.baseline_sensitivity.0.2" in diagnostics
    assert "diagnostic.baseline_sensitivity.0.5" in diagnostics
    assert "diagnostic.baseline_sensitivity.0.8" in diagnostics
    assert any(
        "Repeated attempts can support reliability metrics but do not multiply unique-task power"
        in note
        for note in three_plan.assumption_ledger.sensitivity_notes
    )
    trace = three_plan.engine_decision.computation_trace
    assert "planned_mde_pp.unique_tasks.v1" in trace.formula_versions


def test_ba54_leaderboard_warning_includes_rank_stability_diagnostic():
    original_request = _request(
        intent="Rank three local agents on short finance workflows.",
        mode="leaderboard",
        task_budget=150,
        candidate_models=["agent-a", "agent-b", "agent-c"],
    )
    response = advisor_v2_design(original_request)
    assert response.statistical_plan is not None
    edited_plan = response.statistical_plan.model_copy(deep=True)
    edited_plan.design.task_budget = 100

    validation = advisor_v2_validate(
        AdvisorV2ValidationRequest(
            schema_version="benchmark_advisor.v2",
            statistical_plan=edited_plan,
            original_request=original_request,
            edited_fields=["design.task_budget"],
        )
    )

    assert validation.status == "warning"
    assert any(issue.code == "rank_stability_uncertain" for issue in validation.issues)
    plan = validation.statistical_plan
    assert plan.power_analysis.method == "rank_stability_resolution_proxy"
    assert "diagnostic.leaderboard.rank_resolution_pp" in _diagnostics_by_id(plan)
    assert "exact final ranking" in plan.claim_card.not_allowed_claims
    assert plan.engine_decision is not None
    assert "leaderboard_rank_resolution_pp.v1" in plan.engine_decision.computation_trace.formula_versions


def test_ba54_regression_margin_uses_non_inferiority_planning():
    response = advisor_v2_design(
        _request(
            intent="Check that the new agent did not regress on short finance workflows.",
            mode="regression",
            task_budget=120,
            candidate_models=["baseline-agent", "candidate-agent"],
            target_detectable_effect_pp=20.0,
        )
    )

    assert response.status == "approved"
    assert response.statistical_plan is not None
    plan = response.statistical_plan
    assert plan.design.task_budget == 120
    assert plan.power_analysis.method == "non_inferiority_margin_planning"
    assert plan.power_analysis.planned_mde_pp <= 20.0
    assert "candidate is better than baseline" in plan.claim_card.not_allowed_claims
    assert plan.engine_decision is not None
    assert "non_inferiority_margin_status.v1" in plan.engine_decision.computation_trace.formula_versions


def test_ba54_diagnostic_overclaim_refuses_broad_model_selection():
    response = advisor_v2_design(
        _request(
            intent="Tell me which model is best overall using same-name diagnostic failures in finance.",
            mode="diagnostic",
            task_budget=80,
            candidate_models=["agent-a", "agent-b"],
        )
    )

    assert response.status == "refused"
    assert response.statistical_plan is not None
    assert any(issue.code == "diagnostic_overclaim" for issue in response.issues)
    assert response.export_config is None
    assert response.launchable is False
    assert "model selection" in response.statistical_plan.claim_card.not_allowed_claims


def test_ba54_missingness_and_floor_ceiling_are_explicit_warnings():
    response = advisor_v2_design(
        _request(
            task_budget=100,
            user_overrides={"baseline_rate": 0.95, "expected_missingness_rate": 0.10},
        )
    )

    assert response.status == "warning"
    assert response.statistical_plan is not None
    plan = response.statistical_plan
    assert plan.design.task_budget == 100
    assert plan.assumption_ledger.baseline_rate == 0.95
    assert {issue.code for issue in response.issues} >= {
        "expected_missingness_warning",
        "floor_ceiling_risk",
    }


def test_ba54_high_expected_missingness_refuses_confirmatory_claim():
    response = advisor_v2_design(
        _request(task_budget=100, user_overrides={"expected_missingness_rate": 0.25})
    )

    assert response.status == "refused"
    assert any(issue.code == "expected_missingness_too_high" for issue in response.issues)
    assert response.export_config is None


def test_regression_v2_design_refuses_missing_non_inferiority_margin():
    response = advisor_v2_design(
        _request(
            intent="Check that the new agent did not regress on finance workflows.",
            mode="regression",
            task_budget=80,
            candidate_models=["old-agent", "new-agent"],
            target_detectable_effect_pp=None,
        )
    )

    assert response.status == "refused"
    assert response.statistical_plan is not None
    assert any(issue.code == "missing_non_inferiority_margin" for issue in response.issues)
    assert response.export_config is None
    assert response.launchable is False


def test_pairwise_v2_design_refuses_wrong_candidate_count():
    response = advisor_v2_design(_request(candidate_models=["a", "b", "c"]))

    assert response.status == "refused"
    assert any(issue.code == "unsupported_candidate_model_count" for issue in response.issues)
    assert response.export_config is None


def test_v2_validate_refuses_edited_pairwise_candidate_count():
    original_request = _request()
    response = advisor_v2_design(original_request)
    assert response.statistical_plan is not None
    edited_plan = response.statistical_plan.model_copy(deep=True)
    edited_plan.design.candidate_models.append("agent-c")

    validation = advisor_v2_validate(
        AdvisorV2ValidationRequest(
            schema_version="benchmark_advisor.v2",
            statistical_plan=edited_plan,
            original_request=original_request,
            edited_fields=["design.candidate_models"],
        )
    )

    assert validation.status == "refused"
    assert any(issue.code == "unsupported_candidate_model_count" for issue in validation.issues)
    assert validation.export_config is None
    assert validation.launchable is False
    assert validation.statistical_plan.engine_decision is not None
    assert validation.statistical_plan.engine_decision.recommended_design.candidate_models == [
        "agent-a",
        "agent-b",
        "agent-c",
    ]


def test_v2_validate_refreshes_power_analysis_for_edited_budget():
    original_request = _request()
    response = advisor_v2_design(original_request)
    assert response.statistical_plan is not None
    edited_plan = response.statistical_plan.model_copy(deep=True)
    edited_plan.design.task_budget = 70

    validation = advisor_v2_validate(
        AdvisorV2ValidationRequest(
            schema_version="benchmark_advisor.v2",
            statistical_plan=edited_plan,
            original_request=original_request,
            edited_fields=["design.task_budget"],
        )
    )

    assert validation.status == "warning"
    assert validation.export_config is not None
    assert validation.export_config.tasks == 70
    assert validation.statistical_plan.design.task_budget == 70
    assert validation.statistical_plan.power_analysis.planned_mde_pp == pytest.approx(
        round(planned_mde_pp(70), 3)
    )
    decision = validation.statistical_plan.engine_decision
    assert decision is not None
    assert decision.recommended_design.task_budget == 70
    assert decision.power_analysis.planned_mde_pp == validation.statistical_plan.power_analysis.planned_mde_pp
    assert decision.computation_trace.candidate_count == 1


def test_v2_validate_refresh_depth_is_bounded():
    original_request = _request()
    response = advisor_v2_design(original_request)
    assert response.statistical_plan is not None
    validation_request = AdvisorV2ValidationRequest(
        schema_version="benchmark_advisor.v2",
        statistical_plan=response.statistical_plan,
        original_request=original_request,
    )

    with pytest.raises(ValueError, match="refresh depth"):
        advisor_v2_validate(validation_request, refresh_depth=1)
