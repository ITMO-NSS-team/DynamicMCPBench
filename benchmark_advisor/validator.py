"""Deterministic Benchmark Advisor validator (BA2.1 / T02).

Validates a structured ``AdvisorDesign`` against the normative thresholds, claim
boundaries, and response state matrix in
``docs_benchmark_advisor/planning/INTERFACES.md``. It emits deterministic
``WarningCard`` / ``Refusal`` / ``ClarificationRequest`` objects and a final
status.

Hard rules (T02):
- never calls an LLM; same input -> same output;
- inspects only structured design fields (never raw ``intent``);
- refused / needs_clarification never imply an export;
- guide references are validator-visible: unknown rule ids are a refusal.

Coverage "claims" are read from ``task_distribution.categories`` using the
capability markers below — a deterministic structural signal, not NL parsing.

Out of scope: the planner adapter (T03, intent -> design) and the export handoff
(T07). This module decides; it does not propose or launch anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .guide import is_known_rule
from .schema import (
    AdvisorDesign,
    ClarificationRequest,
    Refusal,
    Status,
    WarningCard,
)
from .stats import coverage_status, planned_mde_pp

# (approved_floor, warning_floor) per mode — INTERFACES.md "Validator Thresholds".
BUDGET_BANDS: dict[str, tuple[int, int]] = {
    "pairwise": (100, 60),
    "leaderboard": (150, 80),
    "regression": (60, 30),
    "diagnostic": (40, 20),
}

# Capability marker (in task_distribution.categories) -> distribution attribute +
# the warning_code emitted when its coverage is short.
COVERAGE_CLAIMS: dict[str, tuple[str, str]] = {
    "cross_server": ("cross_server_ratio", "insufficient_cross_server_coverage"),
    "long_chain": ("long_chain", "insufficient_long_chain_coverage"),
    "recovery": ("recovery_required_ratio", "insufficient_recovery_coverage"),
}

DISTRACTOR_CLAIMS: dict[str, tuple[str, float, float]] = {
    # marker -> (DistractorPolicy attribute, approved_floor, warning_floor)
    "same_name": ("same_name_fraction", 0.25, 0.10),
    "near_miss": ("near_miss_fraction", 0.25, 0.10),
    "hard_negative": ("near_miss_fraction", 0.25, 0.10),
}

CONFIRMATORY_SCOPES = frozenset({"confirmatory_model_selection", "leaderboard_ranking"})
_TOL = 0.001


@dataclass
class ValidationOutcome:
    """Validator verdict — composed into an ``AdvisorResponse`` by the API (T05)."""

    status: Status
    warnings: list[WarningCard] = field(default_factory=list)
    refusal: Refusal | None = None
    clarification: ClarificationRequest | None = None


def _warn(
    code: str,
    message: str,
    repair: str,
    *,
    criterion: str | None = None,
    stat: str | None = None,
    severity: str = "warning",
) -> WarningCard:
    return WarningCard(
        severity=severity,
        code=code,
        message=message,
        failed_criterion_id=criterion,
        statistical_reason=stat,
        repair_suggestion=repair,
    )


def _refuse(code: str, reason: str, stat: str, criterion: str, repairs: list[str]) -> Refusal:
    return Refusal(
        code=code,
        reason=reason,
        statistical_reason=stat,
        failed_criterion_id=criterion,
        repair_options=repairs,
    )


def validate_design(design: AdvisorDesign, *, sandbox_required: bool | None = None) -> ValidationOutcome:
    """Validate a structured design. ``sandbox_required`` is the user-approved export
    override (used only for the stateful-write/sandbox invariant)."""

    warnings: list[WarningCard] = []
    refusals: list[Refusal] = []
    clarification: ClarificationRequest | None = None

    crit_id = design.criteria[0].criterion_id
    td = design.task_distribution
    scope = design.claim_scope
    is_confirmatory = scope in CONFIRMATORY_SCOPES
    is_smoke = scope == "smoke_test_only"

    # 1. Distribution validity (structural refusals).
    chain_sum = td.short_chain + td.medium_chain + td.long_chain
    if abs(chain_sum - 1.0) > _TOL:
        refusals.append(
            _refuse(
                "invalid_distribution",
                "Chain-length fractions must sum to 1.0.",
                f"short+medium+long = {chain_sum:.3f}, not 1.0",
                crit_id,
                ["Rebalance short/medium/long chain fractions so they sum to 1.0."],
            )
        )
    dp = td.distractors
    if (
        dp.same_name_fraction + dp.near_miss_fraction + dp.cross_domain_fraction + dp.random_fraction
        > 1.0 + _TOL
    ):
        refusals.append(
            _refuse(
                "invalid_distribution",
                "Distractor fractions must sum to at most 1.0.",
                "the four distractor fractions exceed 1.0",
                crit_id,
                ["Lower the distractor fractions so they sum to <= 1.0."],
            )
        )
    if td.stateful_write_ratio > 0 and sandbox_required is not True:
        refusals.append(
            _refuse(
                "invalid_distribution",
                "Stateful-write tasks require a sandboxed export.",
                "stateful_write_ratio > 0 without sandbox_required=true",
                crit_id,
                ["Set sandbox_required=true for the export, or remove stateful-write tasks."],
            )
        )

    # 2. Guide references must be known (unknown id => missing required design field).
    for c in design.criteria:
        for ref in c.guide_references:
            if not is_known_rule(ref.rule_id):
                refusals.append(
                    _refuse(
                        "missing_required_design_field",
                        f"Criterion {c.criterion_id} cites an unknown statistical-guide rule.",
                        f"unknown guide rule id: {ref.rule_id}",
                        c.criterion_id,
                        ["Cite a valid statistical_guide.v1 rule id for this criterion."],
                    )
                )

    # 3. Overbroad claim: a diagnostic design cannot make a model-selection claim.
    if design.mode == "diagnostic" and scope in CONFIRMATORY_SCOPES:
        refusals.append(
            _refuse(
                "cannot_support_claim",
                "A diagnostic design cannot support a confirmatory model-selection claim.",
                "diagnostic slices are descriptive, not a model-selection comparison",
                crit_id,
                ["Reframe as a diagnostic slice, or switch to a comparison mode with adequate budget."],
            )
        )

    # 4. Comparison modes need candidate models (else clarify).
    if design.mode in ("pairwise", "leaderboard", "regression") and not design.candidate_models:
        clarification = ClarificationRequest(
            missing_fields=["candidate_models"],
            questions=["Which models or agents should be compared?"],
            why_needed="A comparison mode needs at least the candidate models to evaluate.",
        )

    # 5. Budget band (skipped for an explicit smoke test, which downgrades the claim).
    if is_smoke:
        warnings.append(
            _warn(
                "smoke_test_only",
                "This design is framed as a smoke test; its claim scope is downgraded.",
                "Increase the task budget and reframe to make a confirmatory claim.",
                criterion=crit_id,
                stat="budget is below any confirmatory threshold",
            )
        )
    else:
        approved_floor, warning_floor = BUDGET_BANDS[design.mode]
        if design.task_budget < warning_floor:
            refusals.append(
                _refuse(
                    "insufficient_budget",
                    f"Task budget {design.task_budget} is below the {design.mode} floor of {warning_floor}.",
                    f"{design.task_budget} < refusal threshold {warning_floor} for {design.mode}",
                    crit_id,
                    [
                        f"Increase task_budget to at least {approved_floor}.",
                        "Frame this as a smoke test instead of a confirmatory claim.",
                    ],
                )
            )
        elif design.task_budget < approved_floor:
            warnings.append(
                _warn(
                    "underpowered_design",
                    f"Task budget {design.task_budget} is in the warning band for {design.mode}.",
                    f"Increase task_budget to >= {approved_floor} for an approved {design.mode} design.",
                    criterion=crit_id,
                    stat=f"{warning_floor} <= {design.task_budget} < {approved_floor}",
                )
            )

    # 6. Power: requested detectable effect vs planned MDE.
    if not is_smoke and design.target_detectable_effect_pp is not None:
        planned = planned_mde_pp(design.task_budget)
        target = design.target_detectable_effect_pp
        if target < planned * 0.75:
            refusals.append(
                _refuse(
                    "insufficient_budget",
                    "The requested detectable effect is well below the planned MDE.",
                    f"target {target:.1f}pp < 75% of planned MDE {planned:.1f}pp",
                    crit_id,
                    ["Increase task_budget, or raise the target detectable effect."],
                )
            )
        elif target < planned:
            warnings.append(
                _warn(
                    "underpowered_design",
                    "The requested detectable effect is below the planned MDE.",
                    "Increase task_budget to shrink the planned MDE below the target effect.",
                    criterion=crit_id,
                    stat=f"target {target:.1f}pp < planned MDE {planned:.1f}pp",
                )
            )

    # 7. Repeats for pass@3 reliability claims.
    if any(c.primary_metric == "pass_at_3" for c in design.criteria):
        if design.attempts_per_task == 2:
            warnings.append(
                _warn(
                    "too_few_repeats",
                    "A pass@3 reliability claim plans only 2 attempts per task.",
                    "Plan at least 3 attempts per task for a pass@3 claim.",
                    criterion=crit_id,
                    stat="pass_at_3 requires >= 3 attempts",
                )
            )
        elif design.attempts_per_task < 2:
            if is_confirmatory:
                refusals.append(
                    _refuse(
                        "cannot_support_claim",
                        "A confirmatory pass@3 claim needs at least 3 attempts per task.",
                        "1 attempt cannot support a pass@3 reliability claim",
                        crit_id,
                        ["Plan at least 3 attempts per task."],
                    )
                )
            else:
                warnings.append(
                    _warn(
                        "too_few_repeats",
                        "A pass@3 metric is planned with fewer than 2 attempts per task.",
                        "Plan at least 3 attempts per task for a pass@3 metric.",
                        criterion=crit_id,
                        stat="pass_at_3 requires >= 3 attempts",
                    )
                )

    # 8. Coverage for claimed capabilities (marker in categories).
    for marker, (attr, code) in COVERAGE_CLAIMS.items():
        if marker in td.categories:
            planned = getattr(td, attr)
            status = coverage_status(planned, marker)
            if status == "warning":
                warnings.append(
                    _warn(
                        code,
                        f"Planned {marker} coverage {planned:.2f} is in the warning band.",
                        f"Raise the {marker} coverage above the approved floor.",
                        criterion=crit_id,
                        stat=f"{marker} coverage {planned:.2f} below approved floor",
                    )
                )
            elif status == "refused":
                refusals.append(
                    _refuse(
                        "cannot_support_claim",
                        f"Planned {marker} coverage {planned:.2f} is too low to support that claim.",
                        f"{marker} coverage {planned:.2f} below the minimum",
                        crit_id,
                        [f"Raise the {marker} coverage above the approved floor, or drop the claim."],
                    )
                )

    for marker, (attr, approved_floor, warning_floor) in DISTRACTOR_CLAIMS.items():
        if marker in td.categories:
            planned = getattr(td.distractors, attr)
            if planned < warning_floor:
                refusals.append(
                    _refuse(
                        "cannot_support_claim",
                        f"Planned {marker} distractor pressure {planned:.2f} is too low.",
                        f"{attr} {planned:.2f} below minimum {warning_floor:.2f}",
                        crit_id,
                        [f"Raise {attr} to at least {approved_floor:.2f}, or drop the {marker} claim."],
                    )
                )
            elif planned < approved_floor:
                warnings.append(
                    _warn(
                        "task_mix_bias",
                        f"Planned {marker} distractor pressure {planned:.2f} is in the warning band.",
                        f"Raise {attr} to >= {approved_floor:.2f} for an approved "
                        "distractor-pressure design.",
                        criterion=crit_id,
                        stat=f"{warning_floor:.2f} <= {planned:.2f} < {approved_floor:.2f}",
                    )
                )
    # 9. Secondary slice limits.
    max_conf = max(1, design.task_budget // 40)
    max_diag = max(1, design.task_budget // 25)
    conf_slices = [s for s in td.diagnostic_slices if s.confirmatory]
    if is_confirmatory and len(conf_slices) > 2 * max_conf:
        refusals.append(
            _refuse(
                "cannot_support_claim",
                "Too many confirmatory slices for the task budget.",
                f"{len(conf_slices)} confirmatory slices > 2 x limit {max_conf}",
                crit_id,
                ["Reduce the number of confirmatory slices or increase task_budget."],
            )
        )
    elif len(conf_slices) > max_conf:
        warnings.append(
            _warn(
                "too_many_secondary_slices",
                "More confirmatory slices than the task budget supports.",
                "Mark extra slices as exploratory or increase task_budget.",
                criterion=crit_id,
                stat=f"{len(conf_slices)} confirmatory slices > limit {max_conf}",
            )
        )
    if len(td.diagnostic_slices) > max_diag:
        warnings.append(
            _warn(
                "too_many_secondary_slices",
                "More diagnostic slices than the task budget supports.",
                "Reduce diagnostic slices or increase task_budget.",
                criterion=crit_id,
                stat=f"{len(td.diagnostic_slices)} slices > limit {max_diag}",
            )
        )

    return _resolve(warnings, refusals, clarification)


def _resolve(
    warnings: list[WarningCard],
    refusals: list[Refusal],
    clarification: ClarificationRequest | None,
) -> ValidationOutcome:
    """Apply status precedence: refused > needs_clarification > warning > approved."""
    if refusals:
        return ValidationOutcome(status="refused", warnings=warnings, refusal=refusals[0])
    if clarification is not None:
        return ValidationOutcome(status="needs_clarification", warnings=warnings, clarification=clarification)
    blocking = [w for w in warnings if w.severity in ("warning", "critical")]
    if blocking:
        return ValidationOutcome(status="warning", warnings=warnings)
    return ValidationOutcome(status="approved", warnings=warnings)
