"""Post-run statistical reports for Benchmark Advisor v2 (BA5.5/T15).

This module consumes the v2 ``OutcomeTensor`` contract and produces a scoped
``StatisticalReport``. It does not launch generation/evaluation and does not
change evaluator scoring. Repeated attempts are collapsed within each task so
the task axis remains the inference unit.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from dmcp.curves import proportion_ci

from .schema import Mode, Status
from .v2_schema import (
    AdvisorV2ReportRequest,
    AdvisorV2ReportResponse,
    AxisMetadata,
    ConfidenceIntervalRecord,
    EffectSizeRecord,
    MissingnessSummary,
    MultiplicitySummary,
    OutcomeTensor,
    OutcomeValue,
    RankStabilityResult,
    SliceDiagnosticResult,
    StatisticalIssue,
    StatisticalPlan,
    StatisticalReport,
)

REPORT_SCHEMA_VERSION = "benchmark_advisor.report.v2"
REPORT_RESPONSE_SCHEMA_VERSION = "benchmark_advisor.v2"
_BOOTSTRAP_REPLICATES = 1000
_BOOTSTRAP_SEED = 20260704
_PRIMARY_SLICE_HINTS = ("all", "overall", "primary")


@dataclass(frozen=True)
class _ReportContext:
    tensor: OutcomeTensor
    plan: StatisticalPlan | None
    mode: Mode
    metric_id: str
    primary_slice_id: str
    model_ids: list[str]


def advisor_v2_report(request: AdvisorV2ReportRequest) -> AdvisorV2ReportResponse:
    """Build a v2 post-run statistical report from an outcome tensor."""

    report = build_statistical_report(request)
    return AdvisorV2ReportResponse(schema_version=REPORT_RESPONSE_SCHEMA_VERSION, report=report)


def build_statistical_report(request: AdvisorV2ReportRequest) -> StatisticalReport:
    """Convert completed outcomes into a scoped statistical report."""

    context = _context(request)
    missingness = _missingness_summary(context.tensor)
    issues = _missingness_issues(missingness)
    multiplicity = _multiplicity_summary(context)

    if context.mode == "pairwise":
        report = _pairwise_report(context, missingness, multiplicity, issues)
    elif context.mode == "leaderboard":
        report = _leaderboard_report(context, missingness, multiplicity, issues)
    elif context.mode == "regression":
        report = _regression_report(context, missingness, multiplicity, issues)
    else:
        report = _diagnostic_report(context, missingness, multiplicity, issues)

    return report


def _context(request: AdvisorV2ReportRequest) -> _ReportContext:
    tensor = request.outcome_tensor
    mode = _report_mode(request)
    metric_id = _primary_metric_id(tensor, request.statistical_plan)
    primary_slice_id = _primary_slice_id(tensor)
    model_ids = _ordered_model_ids(tensor, request.statistical_plan)
    return _ReportContext(
        tensor=tensor,
        plan=request.statistical_plan,
        mode=mode,
        metric_id=metric_id,
        primary_slice_id=primary_slice_id,
        model_ids=model_ids,
    )


def _report_mode(request: AdvisorV2ReportRequest) -> Mode:
    if request.statistical_plan is not None:
        return request.statistical_plan.design.mode
    for metric in request.outcome_tensor.metrics:
        raw = metric.metadata.get("advisor_mode") or metric.metadata.get("mode")
        if raw in {"pairwise", "leaderboard", "regression", "diagnostic"}:
            return raw
    model_count = len(request.outcome_tensor.models)
    if model_count >= 3:
        return "leaderboard"
    if model_count == 2:
        return "pairwise"
    return "diagnostic"


def _primary_metric_id(tensor: OutcomeTensor, plan: StatisticalPlan | None) -> str:
    metric_ids = {m.axis_id for m in tensor.metrics}
    if plan is not None:
        planned = plan.design.criteria[0].primary_metric
        if planned in metric_ids:
            return planned
    for metric in tensor.metrics:
        if metric.metadata.get("primary") is True:
            return metric.axis_id
    return tensor.metrics[0].axis_id


def _primary_slice_id(tensor: OutcomeTensor) -> str:
    for hint in _PRIMARY_SLICE_HINTS:
        for slc in tensor.slices:
            if slc.axis_id == hint:
                return slc.axis_id
    for slc in tensor.slices:
        if slc.metadata.get("primary") is True:
            return slc.axis_id
    return tensor.slices[0].axis_id


def _ordered_model_ids(tensor: OutcomeTensor, plan: StatisticalPlan | None) -> list[str]:
    tensor_ids = [model.axis_id for model in tensor.models]
    if plan is None:
        return tensor_ids
    planned = [model for model in plan.design.candidate_models if model in tensor_ids]
    return [*planned, *[model for model in tensor_ids if model not in planned]]


def _missingness_summary(tensor: OutcomeTensor) -> MissingnessSummary:
    expected = (
        len(tensor.tasks)
        * len(tensor.models)
        * len(tensor.attempts)
        * len(tensor.metrics)
        * len(tensor.slices)
    )
    reasons: Counter[str] = Counter()
    explicit_missing = 0
    seen_cells: set[tuple[str, str, str, str, str]] = set()
    duplicate_cells = 0
    for value in tensor.values:
        key = (
            value.task_id,
            value.model_id,
            value.attempt_id,
            value.metric_id,
            value.slice_id,
        )
        if key in seen_cells:
            duplicate_cells += 1
        seen_cells.add(key)
        if value.value is None:
            explicit_missing += 1
            reasons[value.missing_reason or "missing"] += 1

    absent = max(0, expected - len(seen_cells))
    if absent:
        reasons["absent_tensor_cell"] += absent
    if duplicate_cells:
        reasons["duplicate_tensor_cell"] += duplicate_cells
    return MissingnessSummary(
        missing_count=explicit_missing + absent,
        total_count=max(expected, len(tensor.values)),
        policy="explicit_null_with_reason; absent tensor cells are treated as missing",
        reasons=dict(reasons),
    )


def _missingness_issues(missingness: MissingnessSummary) -> list[StatisticalIssue]:
    if missingness.missing_count == 0:
        return []
    if missingness.missing_count >= missingness.total_count:
        return [
            _issue(
                severity="critical",
                code="all_outcomes_missing",
                message="All outcome tensor cells are missing.",
                failed_field="outcome_tensor.values",
                reason="no post-run statistical claim is possible without observed outcomes",
                repair="Populate observed outcomes or rerun the benchmark before requesting a report.",
            )
        ]
    return [
        _issue(
            severity="warning",
            code="missing_outcomes_present",
            message=f"{missingness.missing_count}/{missingness.total_count} outcome cells are missing.",
            failed_field="outcome_tensor.values",
            reason="missing outcomes reduce effective information and weaken scoped claims",
            repair=(
                "Record every missing outcome as null with a reason, rerun failed cells, or narrow the claim."
            ),
        )
    ]


def _multiplicity_summary(context: _ReportContext) -> MultiplicitySummary:
    confirmatory = _confirmatory_slice_ids(context)
    if confirmatory:
        confirmatory_tests = len(confirmatory)
        exploratory_tests = max(0, len(context.tensor.slices) - confirmatory_tests)
    elif context.mode in {"pairwise", "leaderboard", "regression"}:
        confirmatory_tests = 1
        exploratory_tests = max(0, len(context.tensor.slices) - 1)
    else:
        confirmatory_tests = 0
        exploratory_tests = len(context.tensor.slices)

    if confirmatory_tests > 1:
        policy = (
            "Holm correction for multiple confirmatory slices; diagnostics remain exploratory "
            "unless predeclared."
        )
        note = f"{confirmatory_tests} confirmatory tests require multiplicity control before strong claims."
    elif confirmatory_tests == 1:
        policy = _plan_multiplicity_policy(context.plan) or "single primary criterion"
        note = "One primary confirmatory test; no multiplicity correction is needed for the primary claim."
    else:
        policy = "descriptive diagnostics only"
        note = "No confirmatory tests are declared; diagnostic slices are descriptive."
    return MultiplicitySummary(
        policy=policy,
        confirmatory_tests=confirmatory_tests,
        exploratory_tests=exploratory_tests,
        note=note,
    )


def _confirmatory_slice_ids(context: _ReportContext) -> set[str]:
    out = {slc.axis_id for slc in context.tensor.slices if slc.metadata.get("confirmatory") is True}
    if context.plan is not None:
        out.update(
            slc.slice_id
            for slc in context.plan.design.task_distribution.diagnostic_slices
            if slc.confirmatory
        )
    return out


def _plan_multiplicity_policy(plan: StatisticalPlan | None) -> str | None:
    if plan is None:
        return None
    return plan.assumption_ledger.multiplicity_policy


def _pairwise_report(
    context: _ReportContext,
    missingness: MissingnessSummary,
    multiplicity: MultiplicitySummary,
    inherited_issues: list[StatisticalIssue],
) -> StatisticalReport:
    issues = [*inherited_issues]
    if len(context.model_ids) != 2:
        issues.append(
            _issue(
                severity="critical",
                code="unsupported_candidate_model_count",
                message="Pairwise post-run reports require exactly two models.",
                failed_field="outcome_tensor.models",
                reason="a paired delta needs one baseline/candidate pair",
                repair="Provide an outcome tensor with exactly two model ids or use leaderboard mode.",
            )
        )
        return _empty_report(context, missingness, multiplicity, issues)

    a, b = context.model_ids
    pairs = _paired_task_scores(context, a, b)
    if not pairs:
        issues.append(_no_paired_data_issue())
        return _empty_report(context, missingness, multiplicity, issues)

    deltas = [right - left for left, right in pairs]
    estimate = _mean(deltas) * 100.0
    low, high = _bootstrap_ci_pp(deltas)
    label = f"{b} - {a}"
    return StatisticalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="pairwise",
        status=_status_from_issues(issues),
        effect_sizes=[
            EffectSizeRecord(
                label=label,
                estimate_pp=round(estimate, 3),
                method="paired_task_delta",
            )
        ],
        confidence_intervals=[
            ConfidenceIntervalRecord(
                label=label,
                low_pp=round(low, 3),
                high_pp=round(high, 3),
                method="paired_bootstrap_tasks",
            )
        ],
        rank_stability=None,
        slice_diagnostics=_primary_slice_diagnostics(context),
        missingness=missingness,
        multiplicity=multiplicity,
        allowed_claims=[f"Scoped pairwise difference for {label} on the evaluated task distribution."],
        not_allowed_claims=[
            "universal best-model claim",
            "unseen private-deployment guarantee",
            "claim outside the recorded outcome tensor",
        ],
        issues=issues,
    )


def _leaderboard_report(
    context: _ReportContext,
    missingness: MissingnessSummary,
    multiplicity: MultiplicitySummary,
    inherited_issues: list[StatisticalIssue],
) -> StatisticalReport:
    issues = [*inherited_issues]
    if len(context.model_ids) < 2:
        issues.append(
            _issue(
                severity="critical",
                code="unsupported_candidate_model_count",
                message="Leaderboard post-run reports require at least two models.",
                failed_field="outcome_tensor.models",
                reason="rank stability needs a candidate set",
                repair="Provide outcomes for at least two models.",
            )
        )
        return _empty_report(context, missingness, multiplicity, issues)

    by_model = _model_scores(context)
    if not any(by_model.values()):
        issues.append(_no_numeric_data_issue())
        return _empty_report(context, missingness, multiplicity, issues)

    rates = {model: _mean(values) for model, values in by_model.items() if values}
    ranked = sorted(rates, key=lambda model: (-rates[model], model))
    rank_stability = _rank_stability(context, rates)
    effect_sizes = [
        EffectSizeRecord(
            label=f"{model} pass rate",
            estimate_pp=round(rate * 100.0, 3),
            method="task_mean",
        )
        for model, rate in sorted(rates.items(), key=lambda item: (-item[1], item[0]))
    ]
    intervals = [
        _wilson_ci_record(label=f"{model} pass rate", values=by_model[model])
        for model in sorted(rates, key=lambda model: (-rates[model], model))
    ]
    return StatisticalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="leaderboard",
        status=_status_from_issues(issues),
        effect_sizes=effect_sizes,
        confidence_intervals=intervals,
        rank_stability=rank_stability,
        slice_diagnostics=_primary_slice_diagnostics(context),
        missingness=missingness,
        multiplicity=multiplicity,
        allowed_claims=[
            "Scoped leaderboard over the evaluated task distribution with rank-stability caveats.",
            f"Observed top model on this tensor: {ranked[0]}.",
        ],
        not_allowed_claims=[
            "exact final ranking without uncertainty",
            "pairwise superiority without a predeclared multiplicity plan",
            "unseen private-deployment guarantee",
        ],
        issues=issues,
    )


def _regression_report(
    context: _ReportContext,
    missingness: MissingnessSummary,
    multiplicity: MultiplicitySummary,
    inherited_issues: list[StatisticalIssue],
) -> StatisticalReport:
    issues = [*inherited_issues]
    margin = _non_inferiority_margin(context)
    if margin is None:
        issues.append(
            _issue(
                severity="critical",
                code="missing_non_inferiority_margin",
                message="Regression post-run report requires a predeclared non-inferiority margin.",
                failed_field="statistical_plan.design.target_detectable_effect_pp",
                reason="post-hoc non-inferiority margins are not statistically defensible",
                repair=(
                    "Attach the original StatisticalPlan or metric metadata with non_inferiority_margin_pp."
                ),
            )
        )
        return _empty_report(context, missingness, multiplicity, issues)
    if len(context.model_ids) != 2:
        issues.append(
            _issue(
                severity="critical",
                code="unsupported_candidate_model_count",
                message="Regression post-run reports require baseline and candidate models.",
                failed_field="outcome_tensor.models",
                reason="non-inferiority needs exactly one baseline and one candidate",
                repair="Provide exactly two model ids in baseline, candidate order.",
            )
        )
        return _empty_report(context, missingness, multiplicity, issues)

    baseline, candidate = context.model_ids
    pairs = _paired_task_scores(context, baseline, candidate)
    if not pairs:
        issues.append(_no_paired_data_issue())
        return _empty_report(context, missingness, multiplicity, issues)

    deltas = [right - left for left, right in pairs]
    estimate = _mean(deltas) * 100.0
    low, high = _bootstrap_ci_pp(deltas)
    if low < -margin:
        severity = "warning" if estimate >= -margin else "critical"
        issues.append(
            _issue(
                severity=severity,
                code="non_inferiority_margin_not_cleared",
                message=(
                    f"The {candidate} - {baseline} CI lower bound does not clear the -{margin:.1f}pp margin."
                ),
                failed_field="confidence_intervals",
                reason="the post-run uncertainty interval crosses the predeclared non-inferiority boundary",
                repair=(
                    "Increase completed paired tasks, rerun missing cells, or report this as inconclusive."
                ),
            )
        )

    label = f"{candidate} - {baseline}"
    status = _status_from_issues(issues)
    if status == "approved":
        allowed = f"{candidate} is non-inferior to {baseline} within the predeclared {margin:.1f}pp margin."
    elif status == "warning":
        allowed = "Observed regression estimate is scoped, but the non-inferiority claim needs caveats."
    else:
        allowed = "No non-inferiority claim is supported until critical issues are repaired."
    return StatisticalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="regression",
        status=status,
        effect_sizes=[
            EffectSizeRecord(
                label=label,
                estimate_pp=round(estimate, 3),
                method="paired_task_delta",
            )
        ],
        confidence_intervals=[
            ConfidenceIntervalRecord(
                label=label,
                low_pp=round(low, 3),
                high_pp=round(high, 3),
                method="paired_bootstrap_tasks",
            )
        ],
        rank_stability=None,
        slice_diagnostics=_primary_slice_diagnostics(context),
        missingness=missingness,
        multiplicity=multiplicity,
        allowed_claims=[allowed],
        not_allowed_claims=[
            "candidate is better than baseline",
            "post-hoc non-inferiority margin",
            "unseen private-deployment guarantee",
        ],
        issues=issues,
    )


def _diagnostic_report(
    context: _ReportContext,
    missingness: MissingnessSummary,
    multiplicity: MultiplicitySummary,
    inherited_issues: list[StatisticalIssue],
) -> StatisticalReport:
    issues = [*inherited_issues]
    diagnostics = _all_slice_diagnostics(context)
    if not diagnostics:
        issues.append(_no_numeric_data_issue())
    return StatisticalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="diagnostic",
        status=_status_from_issues(issues),
        effect_sizes=[],
        confidence_intervals=[],
        rank_stability=None,
        slice_diagnostics=diagnostics,
        missingness=missingness,
        multiplicity=multiplicity,
        allowed_claims=["Descriptive diagnostic slice findings on the recorded outcome tensor."],
        not_allowed_claims=[
            "broad model-selection claim",
            "universal best-model claim",
            "confirmatory claim unless slices were predeclared and corrected for multiplicity",
        ],
        issues=issues,
    )


def _empty_report(
    context: _ReportContext,
    missingness: MissingnessSummary,
    multiplicity: MultiplicitySummary,
    issues: list[StatisticalIssue],
) -> StatisticalReport:
    return StatisticalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode=context.mode,
        status=_status_from_issues(issues),
        effect_sizes=[],
        confidence_intervals=[],
        rank_stability=None,
        slice_diagnostics=[],
        missingness=missingness,
        multiplicity=multiplicity,
        allowed_claims=["No confirmatory statistical claim is supported by this outcome tensor."],
        not_allowed_claims=[
            "model selection",
            "universal model ranking",
            "private-deployment guarantee",
        ],
        issues=issues,
    )


def _paired_task_scores(
    context: _ReportContext, left_model: str, right_model: str
) -> list[tuple[float, float]]:
    by_task_model = _task_model_scores(context, context.primary_slice_id)
    out: list[tuple[float, float]] = []
    for task in context.tensor.tasks:
        left = by_task_model.get((task.axis_id, left_model))
        right = by_task_model.get((task.axis_id, right_model))
        if left is not None and right is not None:
            out.append((left, right))
    return out


def _model_scores(context: _ReportContext) -> dict[str, list[float]]:
    by_task_model = _task_model_scores(context, context.primary_slice_id)
    out: dict[str, list[float]] = {model: [] for model in context.model_ids}
    for task in context.tensor.tasks:
        for model in context.model_ids:
            value = by_task_model.get((task.axis_id, model))
            if value is not None:
                out[model].append(value)
    return out


def _task_model_scores(context: _ReportContext, slice_id: str) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for value in context.tensor.values:
        if value.metric_id != context.metric_id or value.slice_id != slice_id:
            continue
        numeric = _numeric_value(value)
        if numeric is None:
            continue
        grouped[(value.task_id, value.model_id)].append(numeric)
    return {key: _mean(values) for key, values in grouped.items() if values}


def _numeric_value(value: OutcomeValue) -> float | None:
    raw = value.value
    if raw is None:
        return None
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, int | float):
        number = float(raw)
        if math.isfinite(number):
            return _rate_value(number)
        return None
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "passed", "pass"}:
            return 1.0
        if lowered in {"false", "failed", "fail"}:
            return 0.0
        try:
            number = float(lowered)
        except ValueError:
            return None
        return _rate_value(number) if math.isfinite(number) else None
    return None


def _rate_value(number: float) -> float | None:
    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    return None


def _primary_slice_diagnostics(context: _ReportContext) -> list[SliceDiagnosticResult]:
    label = _slice_label(context.tensor.slices, context.primary_slice_id)
    return _slice_diagnostics_for(context, context.primary_slice_id, label)


def _all_slice_diagnostics(context: _ReportContext) -> list[SliceDiagnosticResult]:
    diagnostics: list[SliceDiagnosticResult] = []
    for slc in context.tensor.slices:
        diagnostics.extend(_slice_diagnostics_for(context, slc.axis_id, slc.label))
    return diagnostics


def _slice_diagnostics_for(
    context: _ReportContext, slice_id: str, slice_label: str
) -> list[SliceDiagnosticResult]:
    by_task_model = _task_model_scores(context, slice_id)
    diagnostics: list[SliceDiagnosticResult] = []
    for model in context.model_ids:
        values = [
            by_task_model[(task.axis_id, model)]
            for task in context.tensor.tasks
            if (task.axis_id, model) in by_task_model
        ]
        if not values:
            continue
        model_label = _model_label(context.tensor.models, model)
        diagnostics.append(
            SliceDiagnosticResult(
                slice_id=slice_id,
                label=f"{slice_label}: {model_label}",
                metric=context.metric_id,
                estimate=round(_mean(values), 6),
                interpretation="descriptive task-level mean over observed outcomes",
            )
        )
    return diagnostics


def _slice_label(slices: list[AxisMetadata], slice_id: str) -> str:
    return next((slc.label for slc in slices if slc.axis_id == slice_id), slice_id)


def _model_label(models: list[AxisMetadata], model_id: str) -> str:
    return next((model.label for model in models if model.axis_id == model_id), model_id)


def _rank_stability(context: _ReportContext, rates: dict[str, float]) -> RankStabilityResult:
    task_model = _task_model_scores(context, context.primary_slice_id)
    tasks = [
        task.axis_id
        for task in context.tensor.tasks
        if any((task.axis_id, model) in task_model for model in context.model_ids)
    ]
    ranked = sorted(rates, key=lambda model: (-rates[model], model))
    max_k = max(1, min(3, len(ranked)))
    if not tasks:
        return RankStabilityResult(
            method="bootstrap_tasks_within_strata",
            stable_top_k=1,
            bootstrap_replicates=1,
            summary="No observed task-level outcomes; rank stability is undefined.",
        )

    rng = random.Random(_BOOTSTRAP_SEED)
    retention: dict[int, int] = {k: 0 for k in range(1, max_k + 1)}
    for _ in range(_BOOTSTRAP_REPLICATES):
        sampled = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        sample_rates: dict[str, float] = {}
        for model in context.model_ids:
            values = [task_model[(task, model)] for task in sampled if (task, model) in task_model]
            sample_rates[model] = _mean(values) if values else -1.0
        sample_ranked = sorted(sample_rates, key=lambda model: (-sample_rates[model], model))
        for k in retention:
            if set(sample_ranked[:k]) == set(ranked[:k]):
                retention[k] += 1

    fractions = {k: retention[k] / _BOOTSTRAP_REPLICATES for k in retention}
    stable = max((k for k, frac in fractions.items() if frac >= 0.80), default=1)
    detail = ", ".join(f"top-{k} retention {fractions[k] * 100:.1f}%" for k in sorted(fractions))
    return RankStabilityResult(
        method="bootstrap_tasks_within_strata",
        stable_top_k=stable,
        bootstrap_replicates=_BOOTSTRAP_REPLICATES,
        summary=detail,
    )


def _wilson_ci_record(label: str, values: list[float]) -> ConfidenceIntervalRecord:
    n = len(values)
    successes = int(round(sum(values)))
    low, high = proportion_ci(successes, n)
    return ConfidenceIntervalRecord(
        label=label,
        low_pp=round(low * 100.0, 3),
        high_pp=round(high * 100.0, 3),
        method="wilson_score",
    )


def _bootstrap_ci_pp(deltas: list[float]) -> tuple[float, float]:
    if not deltas:
        return (0.0, 0.0)
    if len(deltas) == 1:
        point = deltas[0] * 100.0
        return (point, point)
    rng = random.Random(_BOOTSTRAP_SEED)
    means: list[float] = []
    for _ in range(_BOOTSTRAP_REPLICATES):
        sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        means.append(_mean(sample) * 100.0)
    means.sort()
    return (_quantile(means, 0.025), _quantile(means, 0.975))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    pos = q * (len(values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    weight = pos - lo
    return values[lo] * (1 - weight) + values[hi] * weight


def _non_inferiority_margin(context: _ReportContext) -> float | None:
    if context.plan is not None:
        margin = context.plan.design.target_detectable_effect_pp
        if margin is not None:
            return float(margin)
    for metric in context.tensor.metrics:
        raw = metric.metadata.get("non_inferiority_margin_pp")
        if raw is None:
            continue
        try:
            margin = float(raw)
        except (TypeError, ValueError):
            continue
        if margin > 0:
            return margin
    return None


def _status_from_issues(issues: list[StatisticalIssue]) -> Status:
    if any(issue.severity == "critical" for issue in issues):
        return "refused"
    if any(issue.severity == "warning" for issue in issues):
        return "warning"
    return "approved"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _no_paired_data_issue() -> StatisticalIssue:
    return _issue(
        severity="critical",
        code="no_paired_task_outcomes",
        message="No paired task-level outcomes are available for the requested comparison.",
        failed_field="outcome_tensor.values",
        reason="paired post-run claims require both models to have observed values on the same tasks",
        repair="Rerun missing model-task cells or narrow the report to descriptive diagnostics.",
    )


def _no_numeric_data_issue() -> StatisticalIssue:
    return _issue(
        severity="critical",
        code="no_numeric_outcomes",
        message="No numeric or boolean outcomes are available for the selected metric and slice.",
        failed_field="outcome_tensor.values",
        reason="post-run statistical summaries require numeric or boolean outcome values",
        repair="Use a numeric metric such as trace_effect_pass_rate or encode pass/fail as booleans.",
    )


def _issue(
    *,
    severity: str,
    code: str,
    message: str,
    failed_field: str | None,
    reason: str,
    repair: str,
) -> StatisticalIssue:
    return StatisticalIssue(
        severity=severity,
        code=code,
        message=message,
        failed_field=failed_field,
        failed_criterion_id=None,
        statistical_reason=reason,
        repair_options=[repair],
        guide_references=[],
    )
