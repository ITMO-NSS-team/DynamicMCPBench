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
from .stats import (
    BASELINE_SENSITIVITY_RATES,
    DEFAULT_BASELINE_RATE,
    FLOOR_CEILING_WARNING_BAND,
    HARD_BUDGET_SEARCH_CAP,
    MIN_TASKS_PER_CONFIRMATORY_SLICE,
    MIN_TASKS_PER_EXPLORATORY_DIAGNOSTIC_SLICE,
    SOFT_SPLIT_WARNING_CAP,
    STRONGER_BUDGETS,
    ci_width_pp,
    diagnostic_slice_ci_width_pp,
    leaderboard_rank_resolution_pp,
    planned_mde_pp_for_unique_tasks,
    required_tasks_for_mde,
    slice_task_count,
)
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
    PlanningDiagnostic,
    PowerAnalysis,
    PowerCurvePoint,
    StatisticalIssue,
)
from .validator import BUDGET_BANDS, ValidationOutcome, validate_design

ENGINE_VERSION = "benchmark_advisor.statistical_engine.v1"
ENGINE_DECISION_SCHEMA_VERSION = "benchmark_advisor.engine_decision.v2"
_PAIRWISE_REPAIR = "Use exactly two candidate models for a pairwise comparison."
_LEADERBOARD_REPAIR = "Use at least three candidate models for leaderboard rank-stability planning."
_REGRESSION_REPAIR = "Set target_detectable_effect_pp as the predeclared non-inferiority margin."
_REGRESSION_MODEL_REPAIR = "Use exactly two models for regression: baseline and candidate."
_DIAGNOSTIC_OVERCLAIM_REPAIR = (
    "Switch to pairwise or leaderboard mode with representative coverage, "
    "or narrow the claim to the diagnostic slice."
)
_STRUCTURAL_WEAKNESS_CODES = {
    "insufficient_budget",
    "underpowered_design",
    "rank_stability_uncertain",
    "insufficient_slice_coverage",
    "too_many_secondary_slices",
    "too_few_repeats",
    "task_mix_bias",
    "insufficient_cross_server_coverage",
    "insufficient_long_chain_coverage",
    "insufficient_recovery_coverage",
    "missing_diagnostic_pressure",
}

_GUIDE_SECTIONS = {
    "G1": "G1 - Intent To Mode",
    "G2": "G2 - Estimand And Metric Selection",
    "G3": "G3 - Task Distribution",
    "G4": "G4 - Budget, Power, And Repeats",
    "G5": "G5 - Criterion Selection",
    "G6": "G6 - Claim Boundaries",
    "G7": "G7 - Rationale And UI Explanation",
}


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
            target = request.target_detectable_effect_pp or planned_mde_pp_for_unique_tasks(budget)
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
        claim_card=_claim_card(recommended.status, recommended.design),
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
            formula_versions=_formula_versions(recommended.design),
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
    issues.extend(_ba54_statistical_issues(request, design, refs))
    status = _status_from_issues(outcome.status, issues)
    assumptions = _assumptions(design, refs, request=request)
    power = _power_analysis(design, status, assumptions)
    candidate = ParameterCandidate(
        candidate_id="validation.edited",
        design=design,
        power_analysis=power,
        assumption_ledger=assumptions,
        issues=issues,
        score=_score(status, design.task_budget, issues),
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
        claim_card=_claim_card(status, design),
        issues=issues,
        citations=_citations_for_design(index, design.mode, design.criteria[0].test_family),
        computation_trace=EngineComputationTrace(
            engine_version=ENGINE_VERSION,
            guide_version=GUIDE_VERSION,
            guide_snapshot_id="STATISTICAL_GUIDE.md",
            random_seed=None,
            candidate_count=1,
            formula_versions=[*_formula_versions(design), "v2.validate.refresh"],
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
        *STRONGER_BUDGETS.get(request.mode, ()),
    }
    if request.target_detectable_effect_pp is not None:
        values.add(required_tasks_for_mde(request.target_detectable_effect_pp))
    return sorted(max(1, min(HARD_BUDGET_SEARCH_CAP, int(v))) for v in values)


def _attempts_grid(request: AdvisorV2DesignRequest) -> list[int]:
    values = {request.attempts_per_task}
    if "pass@3" in request.intent.lower() or "pass at 3" in request.intent.lower():
        values.add(3)
    return sorted(max(1, int(v)) for v in values)


def _effect_grid(request: AdvisorV2DesignRequest, budgets: Iterable[int]) -> list[float]:
    values = {round(planned_mde_pp_for_unique_tasks(b), 3) for b in budgets}
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
    issues.extend(
        _ba54_statistical_issues(
            request,
            proposal.design,
            proposal.design.criteria[0].guide_references,
        )
    )
    status = _status_from_issues(outcome.status, issues)
    assumptions = _assumptions(proposal.design, proposal.design.criteria[0].guide_references, request=request)
    power = _power_analysis(proposal.design, status, assumptions)
    rejection_reasons = [issue.message for issue in issues if issue.severity in ("warning", "critical")]
    repair_actions = [repair for issue in issues for repair in issue.repair_options]
    return ParameterCandidate(
        candidate_id=candidate_id,
        design=proposal.design,
        power_analysis=power,
        assumption_ledger=assumptions,
        issues=issues,
        score=_score(status, proposal.design.task_budget, issues),
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


def _guide_ref(rule_id: str, role: str) -> StatisticalGuideReference:
    prefix = rule_id.split(".", 1)[0]
    return StatisticalGuideReference(
        guide_version=GUIDE_VERSION,
        rule_id=rule_id,
        section=_GUIDE_SECTIONS.get(prefix, "STATISTICAL_GUIDE.md"),
        role=role,
    )


def _engine_issue(
    *,
    severity: str,
    code: str,
    message: str,
    failed_field: str | None,
    reason: str,
    repair: str,
    refs: list[StatisticalGuideReference],
    criterion_id: str = "criterion.primary",
) -> StatisticalIssue:
    return StatisticalIssue(
        severity=severity,
        code=code,
        message=message,
        failed_field=failed_field,
        failed_criterion_id=criterion_id,
        statistical_reason=reason,
        repair_options=[repair],
        guide_references=refs,
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
    if mode == "regression" and candidate_models and len(candidate_models) != 2:
        issues.append(
            _constraint_issue(
                code="unsupported_candidate_model_count",
                message="Regression planning requires baseline and candidate models.",
                reason="non-inferiority planning needs exactly one baseline and one candidate",
                repair=_REGRESSION_MODEL_REPAIR,
                failed_field="candidate_models",
                refs=refs,
            )
        )
    return issues


def _ba54_statistical_issues(
    request: AdvisorV2DesignRequest,
    design: AdvisorDesign,
    refs: list[StatisticalGuideReference],
) -> list[StatisticalIssue]:
    issues: list[StatisticalIssue] = []
    issues.extend(_leaderboard_rank_issues(design))
    issues.extend(_diagnostic_overclaim_issues(request, design))
    issues.extend(_diagnostic_slice_issues(design))
    issues.extend(_missingness_issues(request, design))
    issues.extend(_floor_ceiling_issues(request))
    return issues


def _leaderboard_rank_issues(design: AdvisorDesign) -> list[StatisticalIssue]:
    if design.mode != "leaderboard":
        return []
    _approved_floor, warning_floor = BUDGET_BANDS["leaderboard"]
    if design.task_budget < warning_floor:
        return []
    if design.task_budget >= BUDGET_BANDS["leaderboard"][0]:
        return []
    return [
        _engine_issue(
            severity="warning",
            code="rank_stability_uncertain",
            message=f"Leaderboard rank stability is exploratory at {design.task_budget} unique tasks.",
            failed_field="task_budget",
            reason=(
                "the leaderboard budget is in the warning band, so pre-run rank-resolution "
                "planning cannot support strong rank claims"
            ),
            repair="Increase task_budget to at least 150, or 300/500 for stronger rank-stability planning.",
            refs=[
                _guide_ref("G1.leaderboard.ranking", "intent_mapping"),
                _guide_ref("G2.metric.rank_stability", "metric_choice"),
                _guide_ref("G5.criterion.rank_stability", "criterion_choice"),
            ],
        )
    ]


def _diagnostic_overclaim_issues(
    request: AdvisorV2DesignRequest, design: AdvisorDesign
) -> list[StatisticalIssue]:
    if design.mode != "diagnostic":
        return []
    intent = request.intent.lower()
    broad_markers = (
        "best overall",
        "best model",
        "which model is best",
        "which model",
        "which is better",
        "tell me which is better",
        "model selection",
    )
    if not any(marker in intent for marker in broad_markers):
        return []
    return [
        _engine_issue(
            severity="critical",
            code="diagnostic_overclaim",
            message="A diagnostic-only design cannot support the requested broad model-selection claim.",
            failed_field="claim_scope",
            reason=(
                "diagnostic slices estimate a narrow failure mode and do not "
                "represent the full task distribution"
            ),
            repair=_DIAGNOSTIC_OVERCLAIM_REPAIR,
            refs=[
                _guide_ref("G1.diagnostic.slice", "intent_mapping"),
                _guide_ref("G6.claim.diagnostic_not_selection", "claim_boundary"),
                _guide_ref("G6.claim.no_universal_best", "claim_boundary"),
            ],
        )
    ]


def _diagnostic_slice_issues(design: AdvisorDesign) -> list[StatisticalIssue]:
    issues: list[StatisticalIssue] = []
    if not design.task_distribution.diagnostic_slices:
        return issues
    for slc in design.task_distribution.diagnostic_slices:
        count = slice_task_count(design.task_budget, slc.ratio)
        if slc.confirmatory and count < 20:
            issues.append(
                _engine_issue(
                    severity="critical",
                    code="insufficient_slice_coverage",
                    message=(
                        f"Confirmatory slice {slc.slice_id} has {count} planned tasks, "
                        "below the minimum diagnostic slice floor."
                    ),
                    failed_field="task_distribution.diagnostic_slices",
                    reason=(
                        "confirmatory diagnostic slices need enough unique tasks "
                        "for interpretable precision"
                    ),
                    repair="Increase task_budget or mark the slice exploratory.",
                    refs=[
                        _guide_ref("G4.slices.limit", "budget_power"),
                        _guide_ref("G5.criterion.descriptive_diagnostic", "criterion_choice"),
                    ],
                )
            )
        elif slc.confirmatory and count < MIN_TASKS_PER_CONFIRMATORY_SLICE:
            issues.append(
                _engine_issue(
                    severity="warning",
                    code="insufficient_slice_coverage",
                    message=(
                        f"Confirmatory slice {slc.slice_id} has {count} planned tasks; "
                        f"{MIN_TASKS_PER_CONFIRMATORY_SLICE} is the BA5.4 target."
                    ),
                    failed_field="task_distribution.diagnostic_slices",
                    reason="slice-level precision is weak for a confirmatory diagnostic claim",
                    repair="Increase task_budget, increase the slice ratio, or mark the slice exploratory.",
                    refs=[
                        _guide_ref("G4.slices.limit", "budget_power"),
                        _guide_ref("G5.criterion.descriptive_diagnostic", "criterion_choice"),
                    ],
                )
            )
        elif design.mode == "diagnostic" and count < MIN_TASKS_PER_EXPLORATORY_DIAGNOSTIC_SLICE:
            issues.append(
                _engine_issue(
                    severity="warning",
                    code="insufficient_slice_coverage",
                    message=(
                        f"Diagnostic slice {slc.slice_id} has {count} planned tasks; "
                        f"{MIN_TASKS_PER_EXPLORATORY_DIAGNOSTIC_SLICE} is the exploratory precision target."
                    ),
                    failed_field="task_distribution.diagnostic_slices",
                    reason="slice-level Wilson precision is weak at the planned slice count",
                    repair="Increase task_budget or increase the diagnostic slice ratio.",
                    refs=[
                        _guide_ref("G2.metric.diagnostic_slice", "metric_choice"),
                        _guide_ref("G5.criterion.wilson_planning", "criterion_choice"),
                    ],
                )
            )
    issues.extend(_diagnostic_pressure_issues(design))
    return issues


def _diagnostic_pressure_issues(design: AdvisorDesign) -> list[StatisticalIssue]:
    issues: list[StatisticalIssue] = []
    categories = set(design.task_distribution.categories)
    pressure_specs = {
        "same_name": ("same_name_fraction", design.task_distribution.distractors.same_name_fraction),
        "near_miss": ("near_miss_fraction", design.task_distribution.distractors.near_miss_fraction),
        "hard_negative": ("near_miss_fraction", design.task_distribution.distractors.near_miss_fraction),
    }
    for marker, (field, value) in pressure_specs.items():
        if marker not in categories or value >= 0.25:
            continue
        severity = "critical" if value < 0.10 else "warning"
        issues.append(
            _engine_issue(
                severity=severity,
                code="missing_diagnostic_pressure",
                message=(
                    f"{marker} is claimed but {field} is {value:.2f}; BA5.4 expects at least 0.25."
                ),
                failed_field=f"task_distribution.distractors.{field}",
                reason=(
                    "diagnostic claims need generator pressure that actually "
                    "creates the stated failure mode"
                ),
                repair=f"Set {field} >= 0.25 or remove the {marker} claim.",
                refs=[
                    _guide_ref("G3.distractor.claim_requires_pressure", "distribution_choice"),
                    _guide_ref("G5.criterion.descriptive_diagnostic", "criterion_choice"),
                ],
            )
        )
    return issues


def _missingness_issues(
    request: AdvisorV2DesignRequest, design: AdvisorDesign
) -> list[StatisticalIssue]:
    raw = request.user_overrides.get("expected_missingness_rate")
    if raw is None:
        return []
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return []
    if not 0.0 <= rate <= 1.0 or rate < 0.05:
        return []
    confirmatory = design.claim_scope in {
        "confirmatory_model_selection",
        "leaderboard_ranking",
        "regression_non_inferiority",
    }
    if rate > 0.20 and confirmatory:
        return [
            _engine_issue(
                severity="critical",
                code="expected_missingness_too_high",
                message=f"Expected missingness {rate:.0%} is too high for a confirmatory claim.",
                failed_field="expected_missingness_rate",
                reason="high missingness can invalidate the planned comparison or non-inferiority margin",
                repair=(
                    "Reduce expected missingness, add a missingness handling plan, "
                    "or downgrade to exploratory."
                ),
                refs=[
                    _guide_ref("G6.claim.confirmatory_vs_exploratory", "claim_boundary"),
                    _guide_ref("G7.doc.parameter_status_label", "ui_explanation"),
                ],
            )
        ]
    if not confirmatory and rate <= 0.20:
        return []
    return [
        _engine_issue(
            severity="warning",
            code="expected_missingness_warning",
            message=f"Expected missingness {rate:.0%} may weaken the planned claim.",
            failed_field="expected_missingness_rate",
            reason="missing outcomes reduce effective information and require explicit reporting policy",
            repair="Increase task_budget, add missingness handling, or narrow the claim.",
            refs=[
                _guide_ref("G6.claim.confirmatory_vs_exploratory", "claim_boundary"),
                _guide_ref("G7.doc.parameter_status_label", "ui_explanation"),
            ],
        )
    ]


def _floor_ceiling_issues(request: AdvisorV2DesignRequest) -> list[StatisticalIssue]:
    raw = request.user_overrides.get("baseline_rate")
    if raw is None:
        return []
    try:
        baseline = float(raw)
    except (TypeError, ValueError):
        return []
    if not 0.0 <= baseline <= 1.0:
        return []
    low, high = FLOOR_CEILING_WARNING_BAND
    if low <= baseline <= high:
        return []
    return [
        _engine_issue(
            severity="warning",
            code="floor_ceiling_risk",
            message=f"Assumed pass rate {baseline:.2f} is near a floor or ceiling.",
            failed_field="assumption_ledger.baseline_rate",
            reason="near-saturated metrics make small effect differences hard to detect and interpret",
            repair=(
                "Rebalance task difficulty, choose a more discriminative slice, "
                "or frame the run as diagnostic."
            ),
            refs=[
                _guide_ref("G2.metric.floor_ceiling_sensitivity", "metric_choice"),
                _guide_ref("G4.floor_ceiling.power_warning", "budget_power"),
                _guide_ref("G6.warning.floor_ceiling", "claim_boundary"),
            ],
        )
    ]


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


def _assumptions(
    design: AdvisorDesign,
    refs: list[StatisticalGuideReference],
    *,
    request: AdvisorV2DesignRequest | None = None,
) -> AssumptionLedger:
    mode = design.mode
    paired = mode in {"pairwise", "regression"}
    baseline = _baseline_rate_from_request(request)
    sensitivity_notes = _sensitivity_notes(design, baseline, request)
    return AssumptionLedger(
        baseline_rate=baseline,
        paired_design=paired,
        independence_assumption=(
            "unique tasks are the iid planning unit; n_eff is at most task_budget and may be smaller "
            "for shared templates, servers, tools, or trajectories"
        ),
        repeated_attempts_policy=(
            "attempts can support reliability metrics but do not multiply unique-task power"
        ),
        missingness_policy="explicit_null_with_reason before post-run reporting",
        multiplicity_policy=(
            "single primary criterion; use Holm for small confirmatory families "
            "and keep diagnostics exploratory unless predeclared and budgeted"
        ),
        sensitivity_notes=sensitivity_notes,
        guide_references=refs,
    )


def _baseline_rate_from_request(request: AdvisorV2DesignRequest | None) -> float:
    if request is None:
        return DEFAULT_BASELINE_RATE
    raw = request.user_overrides.get("baseline_rate")
    if raw is None:
        return DEFAULT_BASELINE_RATE
    try:
        baseline = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_BASELINE_RATE
    if 0.0 <= baseline <= 1.0:
        return baseline
    return DEFAULT_BASELINE_RATE


def _sensitivity_notes(
    design: AdvisorDesign,
    baseline: float,
    request: AdvisorV2DesignRequest | None,
) -> list[str]:
    branch_text = ", ".join(
        f"{rate:.1f}->{planned_mde_pp_for_unique_tasks(design.task_budget, rate):.1f}pp"
        for rate in BASELINE_SENSITIVITY_RATES
    )
    notes = [
        f"Baseline-rate sensitivity branches at task_budget={design.task_budget}: {branch_text}.",
        "Repeated attempts can support reliability metrics but do not multiply unique-task power.",
        "Treat public logs as priors only, not private-deployment evidence.",
        "No calibrated design-effect prior is applied; assume n_eff <= unique task_budget.",
    ]
    if baseline < FLOOR_CEILING_WARNING_BAND[0] or baseline > FLOOR_CEILING_WARNING_BAND[1]:
        notes.append(
            f"Baseline override {baseline:.2f} is near a floor or ceiling; "
            "rebalance task difficulty before small-effect claims."
        )
    if request is not None and "expected_missingness_rate" in request.user_overrides:
        notes.append(
            "Expected missingness override is "
            f"{request.user_overrides['expected_missingness_rate']}; "
            "keep explicit null-with-reason reporting."
        )
    if design.mode == "leaderboard":
        notes.append(
            "Leaderboard rank-resolution proxy is "
            f"{leaderboard_rank_resolution_pp(design.task_budget, baseline):.1f}pp "
            "at this budget."
        )
    if design.mode == "diagnostic" and design.task_distribution.diagnostic_slices:
        for slc in design.task_distribution.diagnostic_slices:
            count = slice_task_count(design.task_budget, slc.ratio)
            width = diagnostic_slice_ci_width_pp(design.task_budget, slc.ratio, baseline)
            notes.append(
                f"Diagnostic slice {slc.slice_id} receives {count} unique tasks; "
                f"Wilson width is {width:.1f}pp."
            )
    cap = SOFT_SPLIT_WARNING_CAP.get(design.mode)
    if cap is not None and design.task_budget > cap:
        notes.append(
            f"Task budget exceeds the {design.mode} split-warning cap {cap}; "
            "consider splitting the benchmark."
        )
    return notes


def _power_analysis(design: AdvisorDesign, status: Status, assumptions: AssumptionLedger) -> PowerAnalysis:
    budgets = sorted(
        {
            max(1, design.task_budget // 2),
            design.task_budget,
            max(design.task_budget + 1, int(round(design.task_budget * 1.5))),
            max(design.task_budget + 2, design.task_budget * 2),
            *STRONGER_BUDGETS.get(design.mode, ()),
        }
    )
    baseline = assumptions.baseline_rate or DEFAULT_BASELINE_RATE
    curve = [
        PowerCurvePoint(
            task_budget=b,
            mde_pp=round(planned_mde_pp_for_unique_tasks(b, baseline), 3),
            ci_width_pp=round(_ci_width_for_design(design, b, baseline), 3),
        )
        for b in budgets
    ]
    alternatives = [
        BudgetAlternative(
            task_budget=point.task_budget,
            detectable_effect_pp=point.mde_pp,
            claim_status=(
                status
                if point.task_budget == design.task_budget
                else _claim_status_for_budget(design, point.task_budget, point.mde_pp)
            ),
        )
        for point in curve
    ]
    return PowerAnalysis(
        alpha=design.criteria[0].alpha,
        target_power=design.criteria[0].beta_or_target_power,
        planned_mde_pp=round(planned_mde_pp_for_unique_tasks(design.task_budget, baseline), 3),
        ci_width_pp=round(_ci_width_for_design(design, design.task_budget, baseline), 3),
        method=_power_method_label(design),
        power_curve=curve,
        budget_alternatives=alternatives,
        planning_diagnostics=_planning_diagnostics(design, baseline, status),
        assumptions=assumptions,
    )


def _ci_width_for_design(design: AdvisorDesign, task_budget: int, baseline: float) -> float:
    if design.mode == "diagnostic" and design.task_distribution.diagnostic_slices:
        primary = design.task_distribution.diagnostic_slices[0]
        return diagnostic_slice_ci_width_pp(task_budget, primary.ratio, baseline)
    return ci_width_pp(task_budget, baseline)


def _claim_status_for_budget(design: AdvisorDesign, task_budget: int, planned_mde: float) -> Status:
    approved_floor, warning_floor = BUDGET_BANDS[design.mode]
    if task_budget < warning_floor:
        return "refused"
    status: Status = "approved" if task_budget >= approved_floor else "warning"
    target = design.target_detectable_effect_pp
    if target is not None:
        if target < 0.75 * planned_mde:
            return "refused"
        if target < planned_mde:
            return "warning"
    return status


def _power_method_label(design: AdvisorDesign) -> str:
    return {
        "pairwise": "paired_bootstrap_heuristic",
        "leaderboard": "rank_stability_resolution_proxy",
        "regression": "non_inferiority_margin_planning",
        "diagnostic": "diagnostic_slice_precision",
    }[design.mode]


def _formula_versions(design: AdvisorDesign) -> list[str]:
    by_mode = {
        "pairwise": [
            "planned_mde_pp.unique_tasks.v1",
            "paired_task_delta.v1",
            "ci_width_pp.v1",
            "validator.v1",
        ],
        "leaderboard": [
            "leaderboard_rank_resolution_pp.v1",
            "planned_mde_pp.unique_tasks.v1",
            "validator.v1",
        ],
        "regression": [
            "planned_mde_pp.unique_tasks.v1",
            "non_inferiority_margin_status.v1",
            "validator.v1",
        ],
        "diagnostic": [
            "wilson_slice_ci_width.v1",
            "slice_task_count.v1",
            "validator.v1",
        ],
    }
    return by_mode[design.mode]


def _planning_diagnostics(
    design: AdvisorDesign, baseline: float, status: Status
) -> list[PlanningDiagnostic]:
    diagnostics = [
        PlanningDiagnostic(
            diagnostic_id="diagnostic.n_eff.unique_tasks",
            label="Effective sample size caveat",
            value=design.task_budget,
            unit="unique_tasks",
            status=status,
            interpretation=(
                "Planning uses unique tasks as the information unit; repeated attempts do not multiply iid N."
            ),
            guide_references=[
                _guide_ref("G4.repeats.not_independent_tasks", "budget_power"),
                _guide_ref("G4.clustered_tasks.neff_caveat", "budget_power"),
            ],
        )
    ]
    for rate in BASELINE_SENSITIVITY_RATES:
        diagnostics.append(
            PlanningDiagnostic(
                diagnostic_id=f"diagnostic.baseline_sensitivity.{rate:.1f}",
                label=f"Baseline sensitivity p={rate:.1f}",
                value=round(planned_mde_pp_for_unique_tasks(design.task_budget, rate), 3),
                unit="pp_mde",
                status=None,
                interpretation="No-prior MDE branch for assumed binary pass rate.",
                guide_references=[_guide_ref("G4.mde.two_proportion_planning", "budget_power")],
            )
        )
    if design.mode == "leaderboard":
        diagnostics.append(
            PlanningDiagnostic(
                diagnostic_id="diagnostic.leaderboard.rank_resolution_pp",
                label="Leaderboard rank-resolution proxy",
                value=round(leaderboard_rank_resolution_pp(design.task_budget, baseline), 3),
                unit="pp",
                status=status,
                interpretation=(
                    "Pre-run proxy for rank separation; actual rank stability "
                    "requires post-run task bootstrap."
                ),
                guide_references=[
                    _guide_ref("G2.metric.rank_stability", "metric_choice"),
                    _guide_ref("G5.criterion.rank_stability", "criterion_choice"),
                ],
            )
        )
    if design.mode == "diagnostic":
        for slc in design.task_distribution.diagnostic_slices:
            count = slice_task_count(design.task_budget, slc.ratio)
            diagnostics.append(
                PlanningDiagnostic(
                    diagnostic_id=f"diagnostic.slice_count.{slc.slice_id}",
                    label=f"Diagnostic slice tasks: {slc.label}",
                    value=count,
                    unit="unique_tasks",
                    status=_slice_count_status(count, slc.confirmatory),
                    interpretation=(
                        "Planned unique tasks allocated to this diagnostic slice; "
                        "diagnostics are exploratory "
                        "unless predeclared and budgeted."
                    ),
                    guide_references=[
                        _guide_ref("G2.metric.diagnostic_slice", "metric_choice"),
                        _guide_ref("G5.criterion.descriptive_diagnostic", "criterion_choice"),
                    ],
                )
            )
            diagnostics.append(
                PlanningDiagnostic(
                    diagnostic_id=f"diagnostic.slice_ci_width.{slc.slice_id}",
                    label=f"Diagnostic slice Wilson width: {slc.label}",
                    value=round(diagnostic_slice_ci_width_pp(design.task_budget, slc.ratio, baseline), 3),
                    unit="pp",
                    status=None,
                    interpretation="Wilson CI-width planning proxy for the slice's binary rate.",
                    guide_references=[_guide_ref("G5.criterion.wilson_planning", "criterion_choice")],
                )
            )
    return diagnostics


def _slice_count_status(count: int, confirmatory: bool) -> Status:
    if confirmatory:
        if count < 20:
            return "refused"
        if count < MIN_TASKS_PER_CONFIRMATORY_SLICE:
            return "warning"
        return "approved"
    if count < MIN_TASKS_PER_EXPLORATORY_DIAGNOSTIC_SLICE:
        return "warning"
    return "approved"


def _score(status: Status, task_budget: int, issues: list[StatisticalIssue] | None = None) -> float:
    base = {"approved": 3000.0, "warning": 2000.0, "needs_clarification": 500.0, "refused": 0.0}[status]
    structural_penalty = 0.0
    if issues:
        structural_penalty = 500.0 * sum(issue.code in _STRUCTURAL_WEAKNESS_CODES for issue in issues)
        structural_penalty += 25.0 * sum(issue.severity == "warning" for issue in issues)
    return base - structural_penalty - float(task_budget)


def _select_candidate(candidates: list[ParameterCandidate]) -> ParameterCandidate:
    return max(candidates, key=lambda c: (c.score, -c.design.task_budget, c.candidate_id))


def _design_alternatives(
    candidates: list[ParameterCandidate], recommended: ParameterCandidate
) -> list[DesignAlternative]:
    cheapest = min(candidates, key=lambda c: c.design.task_budget)
    preferred_stronger_floor = next(
        (
            budget
            for budget in STRONGER_BUDGETS.get(recommended.design.mode, ())
            if budget > recommended.design.task_budget
        ),
        None,
    )
    stronger_candidates = [
        c
        for c in sorted(candidates, key=lambda c: c.design.task_budget)
        if c.design.task_budget > recommended.design.task_budget
        and (preferred_stronger_floor is None or c.design.task_budget >= preferred_stronger_floor)
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
    target = design.target_detectable_effect_pp or planned_mde_pp_for_unique_tasks(design.task_budget)
    return ParameterSearchSpace(
        task_budget_grid=[design.task_budget],
        attempts_grid=[design.attempts_per_task],
        effect_target_grid_pp=[round(target, 3)],
        distribution_candidates=[design.task_distribution],
        confirmatory_slice_limit=max(1, design.task_budget // 40),
        method_families=[design.criteria[0].test_family],
        server_scope_options=[request.server_scope],
    )


def _claim_card(status: Status, design: AdvisorDesign) -> ClaimCard:
    mode = design.mode
    if status == "refused":
        allowed = "No confirmatory claim until the critical issues are repaired."
        if mode == "diagnostic":
            allowed = "Only a diagnostic-only finding is possible after narrowing the claim."
        return ClaimCard(
            allowed_claims=[allowed],
            not_allowed_claims=[
                "model selection",
                "universal model ranking",
                "private-deployment guarantee",
                "post-run proof before outcomes exist",
            ],
            plain_language_summary="The current request cannot support the requested statistical claim.",
        )
    if mode == "pairwise":
        allowed = (
            "Scoped pairwise difference on the planned task distribution using paired task-level outcomes."
        )
        not_allowed = ["universal best-model claim", "unseen private-deployment guarantee"]
    elif mode == "leaderboard":
        allowed = "Scoped leaderboard display with rank-stability caveats."
        not_allowed = [
            "exact final ranking",
            "pairwise superiority without a predeclared multiplicity plan",
            "unseen private-deployment guarantee",
        ]
    elif mode == "regression":
        margin = design.target_detectable_effect_pp
        allowed = (
            f"Scoped non-inferiority claim within the predeclared {margin:.1f}pp margin."
            if margin is not None
            else "No non-inferiority claim until a margin is predeclared."
        )
        not_allowed = [
            "candidate is better than baseline",
            "post-hoc non-inferiority margin",
            "unseen private-deployment guarantee",
        ]
    else:
        allowed = "Exploratory diagnostic slice description."
        not_allowed = [
            "broad model-selection claim",
            "universal best-model claim",
            "unseen private-deployment guarantee",
        ]
    if status == "warning":
        allowed = f"{allowed} Warning caveats must remain visible in export and UI."
    return ClaimCard(
        allowed_claims=[allowed],
        not_allowed_claims=not_allowed,
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
