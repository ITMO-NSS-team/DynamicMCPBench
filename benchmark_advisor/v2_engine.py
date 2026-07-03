"""Deterministic Statistical Engine MVP for Benchmark Advisor v2 (BA5.3/T13).

The engine owns candidate parameter search before the v2 response is composed.
It deliberately reuses the v1 deterministic planner as a structured design
factory, then scores every candidate with the deterministic validator. No LLM,
network retrieval, generation, or post-run inference happens here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .guide import GUIDE_VERSION
from .guide_citations import GuideCitationIndex, load_guide_citation_index
from .planner import PlannerResult, plan
from .schema import (
    AdvisorDesign,
    AdvisorRequest,
    Refusal,
    StatisticalGuideReference,
    Status,
    WarningCard,
)
from .stats import ci_width_pp, planned_mde_pp, required_tasks_for_mde
from .v2_schema import (
    AdvisorV2DesignRequest,
    AssumptionLedger,
    BudgetAlternative,
    ClaimCard,
    DesignAlternative,
    EngineComputationTrace,
    EngineDecision,
    LocalStatisticalCitation,
    ParameterCandidate,
    ParameterSearchSpace,
    PowerAnalysis,
    PowerCurvePoint,
    StatisticalIssue,
)
from .validator import BUDGET_BANDS, ValidationOutcome, validate_design

ENGINE_VERSION = "benchmark_advisor.statistical_engine.v0"
ENGINE_DECISION_SCHEMA_VERSION = "benchmark_advisor.engine_decision.v2"
_PAIRWISE_REPAIR = "Use exactly two candidate models for a pairwise comparison."
_LEADERBOARD_REPAIR = "Use at least three candidate models for leaderboard rank-stability planning."
_REGRESSION_REPAIR = "Set target_detectable_effect_pp as the predeclared non-inferiority margin."


@dataclass(frozen=True)
class EngineValidationRefresh:
    """One bounded Statistical Engine refresh for an edited v2 design."""

    decision: EngineDecision
    validation_outcome: ValidationOutcome


def run_statistical_engine(
    request: AdvisorV2DesignRequest,
    *,
    guide_index: GuideCitationIndex | None = None,
) -> EngineDecision:
    """Search and score deterministic v2 planning candidates."""

    index = guide_index or load_guide_citation_index()
    candidates: list[ParameterCandidate] = []
    budgets = _budget_grid(request)
    attempts_grid = _attempts_grid(request)
    target_grid = _effect_grid(request, budgets)

    for budget in budgets:
        for attempts in attempts_grid:
            target = request.target_detectable_effect_pp or planned_mde_pp(budget)
            candidate_req = _to_v1_request(
                request,
                task_budget=budget,
                attempts_per_task=attempts,
                target=target,
            )
            proposal = plan(candidate_req)
            candidate = _candidate_from_proposal(
                request=request,
                proposal=proposal,
                candidate_id=f"candidate.b{budget}.a{attempts}",
                guide_index=index,
            )
            candidates.append(candidate)

    recommended = _select_candidate(candidates)
    search_space = ParameterSearchSpace(
        task_budget_grid=budgets,
        attempts_grid=attempts_grid,
        effect_target_grid_pp=target_grid,
        distribution_candidates=[recommended.design.task_distribution],
        confirmatory_slice_limit=max(1, recommended.design.task_budget // 40),
        method_families=sorted({c.design.criteria[0].test_family for c in candidates}),
        server_scope_options=[request.server_scope],
    )
    alternatives = _design_alternatives(candidates, recommended)
    return EngineDecision(
        schema_version=ENGINE_DECISION_SCHEMA_VERSION,
        recommended_candidate_id=recommended.candidate_id,
        recommended_design=recommended.design,
        parameter_search_space=search_space,
        parameter_candidates=candidates,
        design_alternatives=alternatives,
        power_analysis=recommended.power_analysis,
        assumption_ledger=recommended.assumption_ledger,
        claim_card=_claim_card(recommended.status, recommended.design.mode),
        issues=recommended.issues,
        citations=_citations_for_design(
            index,
            recommended.design.mode,
            recommended.design.criteria[0].test_family,
        ),
        computation_trace=EngineComputationTrace(
            engine_version=ENGINE_VERSION,
            guide_version=GUIDE_VERSION,
            guide_snapshot_id="STATISTICAL_GUIDE.md",
            random_seed=None,
            candidate_count=len(candidates),
            formula_versions=["planned_mde_pp", "ci_width_pp", "validator.v1"],
            empirical_prior_sources=[],
            validator_rule_ids=_validator_rule_ids(recommended),
            selected_reason=_selected_reason(recommended),
        ),
    )


def refresh_engine_decision_for_design(
    request: AdvisorV2DesignRequest,
    design: AdvisorDesign,
    *,
    sandbox_required: bool | None = None,
    guide_index: GuideCitationIndex | None = None,
    refresh_depth: int = 0,
    max_refresh_depth: int = 1,
) -> EngineValidationRefresh:
    """Refresh engine-derived fields for one edited design without recursive routing."""

    if refresh_depth >= max_refresh_depth:
        raise ValueError("v2 validation refresh depth exceeded")

    index = guide_index or load_guide_citation_index()
    outcome = validate_design(design, sandbox_required=sandbox_required)
    issues = _issues_from_validation(outcome)
    refs = design.criteria[0].guide_references
    issues.extend(_method_constraint_issues_for_design(design, refs))
    status = _status_from_issues(outcome.status, issues)
    assumptions = _assumptions(design.mode, refs)
    power = _power_analysis(design, status, assumptions)
    candidate = ParameterCandidate(
        candidate_id="validation.edited",
        design=design,
        power_analysis=power,
        assumption_ledger=assumptions,
        issues=issues,
        score=_score(status, design.task_budget),
        status=status,
        rejection_reasons=[issue.message for issue in issues if issue.severity in ("warning", "critical")],
        repair_actions=[repair for issue in issues for repair in issue.repair_options],
    )
    decision = EngineDecision(
        schema_version=ENGINE_DECISION_SCHEMA_VERSION,
        recommended_candidate_id=candidate.candidate_id,
        recommended_design=design,
        parameter_search_space=_search_space_for_edited_design(request, design),
        parameter_candidates=[candidate],
        design_alternatives=_design_alternatives([candidate], candidate),
        power_analysis=power,
        assumption_ledger=assumptions,
        claim_card=_claim_card(status, design.mode),
        issues=issues,
        citations=_citations_for_design(index, design.mode, design.criteria[0].test_family),
        computation_trace=EngineComputationTrace(
            engine_version=ENGINE_VERSION,
            guide_version=GUIDE_VERSION,
            guide_snapshot_id="STATISTICAL_GUIDE.md",
            random_seed=None,
            candidate_count=1,
            formula_versions=["planned_mde_pp", "ci_width_pp", "validator.v1", "v2.validate.refresh"],
            empirical_prior_sources=[],
            validator_rule_ids=_validator_rule_ids(candidate),
            selected_reason="Edited design refreshed once by v2 validate; no recursive route call.",
        ),
    )
    return EngineValidationRefresh(decision=decision, validation_outcome=outcome)


def _to_v1_request(
    request: AdvisorV2DesignRequest,
    *,
    task_budget: int | None = None,
    attempts_per_task: int | None = None,
    target: float | None = None,
) -> AdvisorRequest:
    return AdvisorRequest(
        schema_version="benchmark_advisor.v1",
        intent=request.intent,
        mode=request.mode,
        task_budget=task_budget or request.task_budget,
        attempts_per_task=attempts_per_task or request.attempts_per_task,
        candidate_models=request.candidate_models,
        target_detectable_effect_pp=target if target is not None else request.target_detectable_effect_pp,
        alpha=request.alpha,
        beta=request.beta,
        deployment_context=request.deployment_context,
        user_overrides=request.user_overrides,
    )


def _budget_grid(request: AdvisorV2DesignRequest) -> list[int]:
    approved_floor, warning_floor = BUDGET_BANDS[request.mode]
    values = {
        request.task_budget,
        warning_floor,
        approved_floor,
        max(approved_floor, request.task_budget * 2),
        max(approved_floor + 20, int(round(approved_floor * 1.5))),
    }
    if request.target_detectable_effect_pp is not None:
        values.add(required_tasks_for_mde(request.target_detectable_effect_pp))
    return sorted(max(1, min(5000, int(v))) for v in values)


def _attempts_grid(request: AdvisorV2DesignRequest) -> list[int]:
    values = {request.attempts_per_task}
    if "pass@3" in request.intent.lower() or "pass at 3" in request.intent.lower():
        values.add(3)
    return sorted(max(1, int(v)) for v in values)


def _effect_grid(request: AdvisorV2DesignRequest, budgets: Iterable[int]) -> list[float]:
    values = {round(planned_mde_pp(b), 3) for b in budgets}
    if request.target_detectable_effect_pp is not None:
        values.add(round(request.target_detectable_effect_pp, 3))
    return sorted(v for v in values if 0.0 < v <= 100.0)


def _candidate_from_proposal(
    *,
    request: AdvisorV2DesignRequest,
    proposal: PlannerResult,
    candidate_id: str,
    guide_index: GuideCitationIndex,
) -> ParameterCandidate:
    if proposal.design is None:
        issue = _intent_issue(proposal)
        raise ValueError(f"engine candidate could not produce design: {issue.code}")

    outcome = validate_design(proposal.design, sandbox_required=proposal.sandbox_required)
    issues = _issues_from_validation(outcome)
    issues.extend(_method_constraint_issues(request, proposal.design.criteria[0].guide_references))
    status = _status_from_issues(outcome.status, issues)
    assumptions = _assumptions(proposal.design.mode, proposal.design.criteria[0].guide_references)
    power = _power_analysis(proposal.design, status, assumptions)
    rejection_reasons = [issue.message for issue in issues if issue.severity in ("warning", "critical")]
    repair_actions = [repair for issue in issues for repair in issue.repair_options]
    return ParameterCandidate(
        candidate_id=candidate_id,
        design=proposal.design,
        power_analysis=power,
        assumption_ledger=assumptions,
        issues=issues,
        score=_score(status, proposal.design.task_budget),
        status=status,
        rejection_reasons=rejection_reasons,
        repair_actions=repair_actions,
    )


def _intent_issue(proposal: PlannerResult) -> StatisticalIssue:
    if proposal.refusal is not None:
        return _issue_from_refusal(proposal.refusal)
    if proposal.clarification is not None:
        return StatisticalIssue(
            severity="critical",
            code="needs_clarification",
            message=proposal.clarification.why_needed,
            failed_field="candidate_models",
            failed_criterion_id=None,
            statistical_reason=proposal.clarification.why_needed,
            repair_options=proposal.clarification.questions,
            guide_references=[],
        )
    raise ValueError("planner returned neither design nor issue")


def _issues_from_validation(outcome: ValidationOutcome) -> list[StatisticalIssue]:
    issues = [_issue_from_warning(w) for w in outcome.warnings]
    if outcome.refusal is not None:
        issues.append(_issue_from_refusal(outcome.refusal))
    if outcome.clarification is not None:
        issues.append(
            StatisticalIssue(
                severity="critical",
                code="needs_clarification",
                message=outcome.clarification.why_needed,
                failed_field=",".join(outcome.clarification.missing_fields),
                failed_criterion_id=None,
                statistical_reason=outcome.clarification.why_needed,
                repair_options=outcome.clarification.questions,
                guide_references=[],
            )
        )
    return issues


def _issue_from_warning(warning: WarningCard) -> StatisticalIssue:
    return StatisticalIssue(
        severity=warning.severity,
        code=warning.code,
        message=warning.message,
        failed_field=None,
        failed_criterion_id=warning.failed_criterion_id,
        statistical_reason=warning.statistical_reason or warning.message,
        repair_options=[warning.repair_suggestion],
        guide_references=[],
    )


def _issue_from_refusal(refusal: Refusal) -> StatisticalIssue:
    return StatisticalIssue(
        severity="critical",
        code=refusal.code,
        message=refusal.reason,
        failed_field=None,
        failed_criterion_id=refusal.failed_criterion_id,
        statistical_reason=refusal.statistical_reason,
        repair_options=refusal.repair_options,
        guide_references=[],
    )


def _method_constraint_issues(
    request: AdvisorV2DesignRequest, refs: list[StatisticalGuideReference]
) -> list[StatisticalIssue]:
    return _method_constraint_issues_for_fields(
        mode=request.mode,
        candidate_models=request.candidate_models,
        target_detectable_effect_pp=request.target_detectable_effect_pp,
        refs=refs,
    )


def _method_constraint_issues_for_design(
    design: AdvisorDesign, refs: list[StatisticalGuideReference]
) -> list[StatisticalIssue]:
    return _method_constraint_issues_for_fields(
        mode=design.mode,
        candidate_models=design.candidate_models,
        target_detectable_effect_pp=design.target_detectable_effect_pp,
        refs=refs,
    )


def _method_constraint_issues_for_fields(
    *,
    mode: str,
    candidate_models: list[str],
    target_detectable_effect_pp: float | None,
    refs: list[StatisticalGuideReference],
) -> list[StatisticalIssue]:
    issues: list[StatisticalIssue] = []
    if mode == "pairwise" and len(candidate_models) != 2:
        issues.append(
            _constraint_issue(
                code="unsupported_candidate_model_count",
                message="Pairwise planning requires exactly two candidate models.",
                reason="paired task-level comparisons need one A/B candidate pair",
                repair=_PAIRWISE_REPAIR,
                failed_field="candidate_models",
                refs=refs,
            )
        )
    if mode == "leaderboard" and len(candidate_models) < 3:
        issues.append(
            _constraint_issue(
                code="unsupported_candidate_model_count",
                message="Leaderboard planning requires at least three candidate models.",
                reason="rank-stability planning needs a leaderboard candidate set",
                repair=_LEADERBOARD_REPAIR,
                failed_field="candidate_models",
                refs=refs,
            )
        )
    if mode == "regression" and target_detectable_effect_pp is None:
        issues.append(
            _constraint_issue(
                code="missing_non_inferiority_margin",
                message="Regression planning needs a predeclared non-inferiority margin.",
                reason="post-hoc non-inferiority margins are not statistically defensible",
                repair=_REGRESSION_REPAIR,
                failed_field="target_detectable_effect_pp",
                refs=refs,
            )
        )
    return issues


def _constraint_issue(
    *,
    code: str,
    message: str,
    reason: str,
    repair: str,
    failed_field: str,
    refs: list[StatisticalGuideReference],
) -> StatisticalIssue:
    return StatisticalIssue(
        severity="critical",
        code=code,
        message=message,
        failed_field=failed_field,
        failed_criterion_id="criterion.primary",
        statistical_reason=reason,
        repair_options=[repair],
        guide_references=refs,
    )


def _status_from_issues(base_status: Status, issues: list[StatisticalIssue]) -> Status:
    if any(issue.severity == "critical" for issue in issues):
        return "refused"
    if any(issue.severity == "warning" for issue in issues):
        return "warning"
    return base_status


def _assumptions(mode: str, refs: list[StatisticalGuideReference]) -> AssumptionLedger:
    paired = mode == "pairwise"
    return AssumptionLedger(
        baseline_rate=0.5,
        paired_design=paired,
        independence_assumption="unique tasks are the iid planning unit; same-task model outputs are paired",
        repeated_attempts_policy=(
            "attempts can support reliability metrics but do not multiply unique-task power"
        ),
        missingness_policy="explicit_null_with_reason before post-run reporting",
        multiplicity_policy=(
            "single primary criterion; diagnostic slices remain exploratory unless predeclared"
        ),
        sensitivity_notes=[
            "Inspect low/medium/high baseline-rate sensitivity before launch.",
            "Treat public logs as priors only, not private-deployment evidence.",
        ],
        guide_references=refs,
    )


def _power_analysis(design, status: Status, assumptions: AssumptionLedger) -> PowerAnalysis:
    budgets = sorted(
        {
            max(1, design.task_budget // 2),
            design.task_budget,
            max(design.task_budget + 1, int(round(design.task_budget * 1.5))),
            max(design.task_budget + 2, design.task_budget * 2),
        }
    )
    curve = [
        PowerCurvePoint(
            task_budget=b,
            mde_pp=round(planned_mde_pp(b), 3),
            ci_width_pp=round(ci_width_pp(b), 3),
        )
        for b in budgets
    ]
    alternatives = [
        BudgetAlternative(
            task_budget=point.task_budget,
            detectable_effect_pp=point.mde_pp,
            claim_status=status if point.task_budget == design.task_budget else "warning",
        )
        for point in curve
    ]
    return PowerAnalysis(
        alpha=design.criteria[0].alpha,
        target_power=design.criteria[0].beta_or_target_power,
        planned_mde_pp=round(planned_mde_pp(design.task_budget), 3),
        ci_width_pp=round(ci_width_pp(design.task_budget), 3),
        method=design.analysis_plan.mde_method,
        power_curve=curve,
        budget_alternatives=alternatives,
        assumptions=assumptions,
    )


def _score(status: Status, task_budget: int) -> float:
    base = {"approved": 3000.0, "warning": 2000.0, "needs_clarification": 500.0, "refused": 0.0}[status]
    return base - float(task_budget)


def _select_candidate(candidates: list[ParameterCandidate]) -> ParameterCandidate:
    return max(candidates, key=lambda c: (c.score, -c.design.task_budget, c.candidate_id))


def _design_alternatives(
    candidates: list[ParameterCandidate], recommended: ParameterCandidate
) -> list[DesignAlternative]:
    cheapest = min(candidates, key=lambda c: c.design.task_budget)
    stronger_candidates = [
        c
        for c in sorted(candidates, key=lambda c: c.design.task_budget)
        if c.design.task_budget > recommended.design.task_budget
    ]
    stronger = stronger_candidates[0] if stronger_candidates else recommended
    narrowed = next((c for c in candidates if c.status != "refused"), recommended)
    selected = [
        (
            "budget_minimum",
            "Budget minimum",
            cheapest,
            "Cheapest searched candidate; may narrow or weaken claims.",
        ),
        ("recommended", "Recommended", recommended, _selected_reason(recommended)),
        ("stronger", "Stronger", stronger, "Higher budget alternative with lower planned MDE."),
        (
            "narrowed_claim",
            "Narrowed claim",
            narrowed,
            "Closest defensible scoped claim found by the engine.",
        ),
    ]
    return [
        DesignAlternative(
            alternative_id=f"alt.{alt_id}",
            label=label,
            task_budget=candidate.design.task_budget,
            attempts_per_task=candidate.design.attempts_per_task,
            target_detectable_effect_pp=candidate.design.target_detectable_effect_pp,
            status=candidate.status,
            tradeoff=tradeoff,
            repair_actions=candidate.repair_actions,
        )
        for alt_id, label, candidate, tradeoff in selected
    ]


def _search_space_for_edited_design(
    request: AdvisorV2DesignRequest, design: AdvisorDesign
) -> ParameterSearchSpace:
    target = design.target_detectable_effect_pp or planned_mde_pp(design.task_budget)
    return ParameterSearchSpace(
        task_budget_grid=[design.task_budget],
        attempts_grid=[design.attempts_per_task],
        effect_target_grid_pp=[round(target, 3)],
        distribution_candidates=[design.task_distribution],
        confirmatory_slice_limit=max(1, design.task_budget // 40),
        method_families=[design.criteria[0].test_family],
        server_scope_options=[request.server_scope],
    )


def _claim_card(status: Status, mode: str) -> ClaimCard:
    if status == "refused":
        return ClaimCard(
            allowed_claims=["No confirmatory claim until the critical issues are repaired."],
            not_allowed_claims=["model selection", "universal model ranking", "private-deployment guarantee"],
            plain_language_summary="The current request cannot support the requested statistical claim.",
        )
    allowed_by_mode = {
        "pairwise": "Scoped pairwise difference on the planned task distribution.",
        "leaderboard": "Scoped leaderboard display with rank-stability caveats.",
        "regression": "Scoped non-inferiority claim within the predeclared margin.",
        "diagnostic": "Exploratory diagnostic slice description.",
    }
    return ClaimCard(
        allowed_claims=[allowed_by_mode[mode]],
        not_allowed_claims=["universal best-model claim", "unseen private-deployment guarantee"],
        plain_language_summary=f"This {mode} plan is {status} for the scoped claim shown here.",
    )


def _citations_for_design(
    index: GuideCitationIndex, mode: str, method_family: str
) -> list[LocalStatisticalCitation]:
    citations = [
        *index.citations_for_advisor_mode(mode),
        *index.citations_for_method_family(method_family),
        index.citation_for_rule("G4.budget.mode_thresholds"),
        index.citation_for_rule("G7.rationale.hover"),
    ]
    seen: set[str] = set()
    deduped: list[LocalStatisticalCitation] = []
    for citation in citations:
        if citation.source_id in seen:
            continue
        seen.add(citation.source_id)
        deduped.append(citation)
    return deduped


def _validator_rule_ids(candidate: ParameterCandidate) -> list[str]:
    ids: set[str] = set()
    for issue in candidate.issues:
        ids.update(ref.rule_id for ref in issue.guide_references)
    for ref in candidate.design.criteria[0].guide_references:
        ids.add(ref.rule_id)
    return sorted(ids)


def _selected_reason(candidate: ParameterCandidate) -> str:
    if candidate.status == "approved":
        return "Cheapest approved candidate under deterministic engine scoring."
    if candidate.status == "warning":
        return "Best warning-level candidate; repairs remain visible before launch."
    return "No non-refused candidate was found; returning the strongest refused candidate with repairs."
