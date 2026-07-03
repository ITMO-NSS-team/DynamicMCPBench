"""Tests for BA5.3 guide-first v2 planner/engine composition."""

from __future__ import annotations

from benchmark_advisor.v2_engine import run_statistical_engine
from benchmark_advisor.v2_schema import AdvisorV2DesignRequest
from benchmark_advisor.v2_service import advisor_v2_design


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
