"""Benchmark Advisor v2 service composition (BA5.3/T13).

V2 design is guide-first and engine-scored: raw intent is first checked by the
deterministic planner for intent-level refusals/clarifications, then the
Statistical Engine searches candidate parameters, validates each proposal, and
the service wraps the selected engine decision into a ``StatisticalPlan``.
"""

from __future__ import annotations

from .export import build_export_config, is_exportable
from .planner import plan
from .schema import AdvisorRequest
from .v2_engine import (
    _intent_issue,
    refresh_engine_decision_for_design,
    run_statistical_engine,
)
from .v2_report import build_statistical_report
from .v2_schema import (
    AdvisorV2DesignRequest,
    AdvisorV2DesignResponse,
    AdvisorV2ReportRequest,
    AdvisorV2ReportResponse,
    AdvisorV2ValidationRequest,
    AdvisorV2ValidationResponse,
    StatisticalPlan,
)

_MAX_VALIDATE_REFRESH_DEPTH = 1


def advisor_v2_design(request: AdvisorV2DesignRequest) -> AdvisorV2DesignResponse:
    """Return an engine-scored v2 statistical design response."""

    preflight = plan(_to_v1_request(request))
    if preflight.design is None:
        issue = _intent_issue(preflight)
        status = "needs_clarification" if issue.code == "needs_clarification" else "refused"
        return AdvisorV2DesignResponse(
            schema_version="benchmark_advisor.v2",
            status=status,
            statistical_plan=None,
            issues=[issue],
            export_config=None,
            launchable=False,
        )

    decision = run_statistical_engine(request)
    plan_obj = StatisticalPlan(
        schema_version="benchmark_advisor.statistical_plan.v2",
        design=decision.recommended_design,
        engine_decision=decision,
        power_analysis=decision.power_analysis,
        design_alternatives=decision.design_alternatives,
        assumption_ledger=decision.assumption_ledger,
        issues=decision.issues,
        citations=decision.citations,
        claim_card=decision.claim_card,
    )
    status = _decision_status(decision)
    export = None
    if is_exportable(status):
        export = build_export_config(
            decision.recommended_design,
            [],
            sandbox_required=_sandbox_required(request, decision.recommended_design),
            server_scope=request.server_scope,
        )
    return AdvisorV2DesignResponse(
        schema_version="benchmark_advisor.v2",
        status=status,
        statistical_plan=plan_obj,
        issues=decision.issues,
        export_config=export,
        launchable=export is not None,
    )


def advisor_v2_validate(
    request: AdvisorV2ValidationRequest,
    *,
    refresh_depth: int = 0,
) -> AdvisorV2ValidationResponse:
    """Validate an edited v2 plan without rerunning generation or evaluation."""

    sandbox_required = None
    if request.original_request is not None:
        sandbox_required = _sandbox_required(request.original_request, request.statistical_plan.design)

    original_request = request.original_request or _request_from_plan(request.statistical_plan)
    refresh = refresh_engine_decision_for_design(
        original_request,
        request.statistical_plan.design,
        sandbox_required=sandbox_required,
        refresh_depth=refresh_depth,
        max_refresh_depth=_MAX_VALIDATE_REFRESH_DEPTH,
    )
    decision = refresh.decision
    outcome = refresh.validation_outcome
    issues = decision.issues
    status = _decision_status(decision)
    plan_obj = request.statistical_plan.model_copy(
        update={
            "design": decision.recommended_design,
            "engine_decision": decision,
            "power_analysis": decision.power_analysis,
            "design_alternatives": decision.design_alternatives,
            "assumption_ledger": decision.assumption_ledger,
            "issues": issues,
            "citations": decision.citations,
            "claim_card": decision.claim_card,
        },
        deep=True,
    )
    export = None
    if is_exportable(status):
        export = build_export_config(
            decision.recommended_design,
            outcome.warnings,
            sandbox_required=sandbox_required,
            server_scope=original_request.server_scope,
        )
    return AdvisorV2ValidationResponse(
        schema_version="benchmark_advisor.v2",
        status=status,
        statistical_plan=plan_obj,
        issues=issues,
        export_config=export,
        launchable=export is not None,
    )


def advisor_v2_report(request: AdvisorV2ReportRequest) -> AdvisorV2ReportResponse:
    """Compute a scoped v2 post-run statistical report."""

    return AdvisorV2ReportResponse(
        schema_version="benchmark_advisor.v2",
        report=build_statistical_report(request),
    )


def _to_v1_request(request: AdvisorV2DesignRequest) -> AdvisorRequest:
    return AdvisorRequest(
        schema_version="benchmark_advisor.v1",
        intent=request.intent,
        mode=request.mode,
        task_budget=request.task_budget,
        attempts_per_task=request.attempts_per_task,
        candidate_models=request.candidate_models,
        target_detectable_effect_pp=request.target_detectable_effect_pp,
        alpha=request.alpha,
        beta=request.beta,
        deployment_context=request.deployment_context,
        user_overrides=request.user_overrides,
    )


def _request_from_plan(plan: StatisticalPlan) -> AdvisorV2DesignRequest:
    design = plan.design
    return AdvisorV2DesignRequest(
        schema_version="benchmark_advisor.v2",
        intent=design.evaluation_question,
        mode=design.mode,
        task_budget=design.task_budget,
        attempts_per_task=design.attempts_per_task,
        candidate_models=design.candidate_models,
        target_detectable_effect_pp=design.target_detectable_effect_pp,
        alpha=design.analysis_plan.alpha,
        beta=design.analysis_plan.beta,
        deployment_context=None,
        server_scope=[],
        user_overrides={},
    )


def _decision_status(decision) -> str:
    candidate = next(
        c for c in decision.parameter_candidates if c.candidate_id == decision.recommended_candidate_id
    )
    return candidate.status


def _sandbox_required(request: AdvisorV2DesignRequest, design) -> bool | None:
    if "sandbox_required" in request.user_overrides:
        return bool(request.user_overrides["sandbox_required"])
    if design.task_distribution.stateful_write_ratio > 0:
        return True
    return None
