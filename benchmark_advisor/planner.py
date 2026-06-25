"""Deterministic Benchmark Advisor planner (BA2.2 / T03).

Maps an ``AdvisorRequest`` to a structured ``AdvisorDesign`` plus a guide-backed
evidence ledger. Per decision **D1** the default planner is rule-based and
deterministic (booth-safe REPLAY); an LLM planner is the opt-in LIVE path and
would slot in behind the same ``plan()`` signature. Same input -> same output.

Division of authority (T03): the planner *proposes*; the validator (T02) *decides*.
Two refusals are intent-level (the validator never sees raw ``intent``) so they
live here: final-answer grading and a request to launch generation. Everything
else — budget, power, coverage, distribution — is left to the validator.

Out of scope: validation gates, the Studio API/UI, planning-statistics math
(imported), and any generation/evaluation launch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import (
    AdvisorDesign,
    ClarificationRequest,
    Criterion,
    EvidenceLedgerEntry,
    Refusal,
    StatisticalGuideReference,
)
from .stats import planned_mde_pp

# --- intent keyword tables (tight, to avoid false positives) -------------------

_FINAL_ANSWER = ("final answer", "answer string", "reference answer", "matches my reference", "answer match")
_GEN_LAUNCH = (
    "launch generation",
    "start generating",
    "kick off generation",
    "run the benchmark now",
    "generate now",
)
_SMOKE = ("smoke", "quick check", "nothing rigorous", "sanity check", "just testing")
_RELIABILITY = ("reliab", "repeated attempt", "across repeats", "pass@3", "pass at 3")
_CROSS_SERVER = ("cross-server", "cross server", "orchestrat", "across our", "across the")
_LONG_CHAIN = ("long,", "long ", "multi-step", "end to end", "end-to-end")
_RECOVERY = ("recover", "retry", "retries", "failed tool", "failure handling", "robust")
_SAME_NAME = ("same-name", "same name", "same-named", "wrong server", "homonym")

_SECTIONS = {
    "G1": "G1 - Intent To Mode",
    "G2": "G2 - Estimand And Metric Selection",
    "G3": "G3 - Task Distribution",
    "G4": "G4 - Budget, Power, And Repeats",
    "G5": "G5 - Criterion Selection",
    "G6": "G6 - Claim Boundaries",
    "G7": "G7 - Rationale And UI Explanation",
}

# Per-mode planning profile (estimand, metric, test family, analysis plan, refs).
_MODE_PROFILE: dict[str, dict[str, Any]] = {
    "pairwise": {
        "scope": "confirmatory_model_selection",
        "metric": "pairwise_delta_pp",
        "test": "paired_bootstrap",
        "ci": "paired_bootstrap",
        "mde": "paired_bootstrap_heuristic",
        "rank": "not_applicable",
        "pairwise_test": "paired_bootstrap",
        "crit_rule": "G5.criterion.paired_bootstrap",
        "metric_rule": "G2.metric.pairwise_delta",
        "intent_rule": "G1.pairwise.selection",
        "estimand": "paired difference in trace-effect pass rate",
    },
    "leaderboard": {
        "scope": "leaderboard_ranking",
        "metric": "rank_stability",
        "test": "rank_stability_bootstrap",
        "ci": "stratified_bootstrap",
        "mde": "normal_approx_two_proportion",
        "rank": "bootstrap_tasks_within_strata",
        "pairwise_test": None,
        "crit_rule": "G5.criterion.rank_stability",
        "metric_rule": "G2.metric.rank_stability",
        "intent_rule": "G1.leaderboard.ranking",
        "estimand": "per-model trace-effect pass rate and rank",
    },
    "regression": {
        "scope": "regression_non_inferiority",
        "metric": "non_inferiority_margin_pp",
        "test": "non_inferiority_margin",
        "ci": "wilson_score",
        "mde": "normal_approx_two_proportion",
        "rank": "not_applicable",
        "pairwise_test": None,
        "crit_rule": "G5.criterion.non_inferiority",
        "metric_rule": "G2.metric.non_inferiority",
        "intent_rule": "G1.regression.non_inferiority",
        "estimand": "non-inferiority margin in trace-effect pass rate",
    },
    "diagnostic": {
        "scope": "diagnostic_slice",
        "metric": "slice_failure_rate",
        "test": "diagnostic_descriptive",
        "ci": "wilson_score",
        "mde": "normal_approx_two_proportion",
        "rank": "not_applicable",
        "pairwise_test": None,
        "crit_rule": "G5.criterion.descriptive_diagnostic",
        "metric_rule": "G2.metric.diagnostic_slice",
        "intent_rule": "G1.diagnostic.slice",
        "estimand": "descriptive slice failure rate",
    },
}

_CLAIM_BOUNDARY = {
    "pairwise": (
        "Limited to the planned task distribution; not a universal ranking and "
        "not evidence about unseen private deployments."
    ),
    "leaderboard": (
        "A leaderboard over the planned distribution only; rank order is not a universal model ranking."
    ),
    "regression": (
        "Supports a non-inferiority conclusion within the stated margin on the planned distribution only."
    ),
    "diagnostic": (
        "Describes failure on the named diagnostic slice; does not by itself justify a model-selection claim."
    ),
}

_COMPARISON_MODES = ("pairwise", "leaderboard", "regression")
_DISTRIBUTION_OVERRIDE_KEYS = {
    "short_chain",
    "medium_chain",
    "long_chain",
    "cross_server_ratio",
    "recovery_required_ratio",
    "prerequisite_strict_ratio",
    "stateful_write_ratio",
}


@dataclass
class PlannerResult:
    """A planner proposal. The API composes this with the validator's verdict."""

    design: AdvisorDesign | None
    evidence_ledger: list[EvidenceLedgerEntry] = field(default_factory=list)
    refusal: Refusal | None = None
    clarification: ClarificationRequest | None = None
    sandbox_required: bool = True


def _has(intent: str, words: tuple[str, ...]) -> bool:
    return any(w in intent for w in words)


def _ref(rule_id: str, role: str) -> StatisticalGuideReference:
    return StatisticalGuideReference(
        guide_version="statistical_guide.v1",
        rule_id=rule_id,
        section=_SECTIONS[rule_id.split(".", 1)[0]],
        role=role,
    )


def _ev(parameter, value, intent_evidence, rationale, hover, refs, hint=None) -> EvidenceLedgerEntry:
    return EvidenceLedgerEntry(
        parameter=parameter,
        value=value,
        intent_evidence=intent_evidence,
        statistical_rationale=rationale,
        guide_references=refs,
        hover_text=hover,
        judge_validation_hint=hint,
        validator_status="approved",
        repair_suggestion=None,
    )


def plan(request) -> PlannerResult:
    """Deterministically propose a design (or an intent-level refusal/clarification)."""
    intent = request.intent.lower()

    # --- intent-level refusals (validator can't see raw intent) ---------------
    if _has(intent, _FINAL_ANSWER):
        return PlannerResult(
            design=None,
            refusal=Refusal(
                code="unsupported_final_answer_claim",
                reason="Final-answer grading is not an allowed benchmark metric.",
                statistical_reason="DynamicMCPBench scores trace effects, never final-answer matches.",
                failed_criterion_id="criterion.primary",
                repair_options=["Choose an effect-based metric such as trace-effect pass rate."],
            ),
        )
    if _has(intent, _GEN_LAUNCH):
        return PlannerResult(
            design=None,
            refusal=Refusal(
                code="generation_launch_forbidden",
                reason="The advisor plans designs; it never launches generation or evaluation.",
                statistical_reason="Launching a paid run is out of scope for a pre-run planning gate.",
                failed_criterion_id="criterion.primary",
                repair_options=["Export the JSON config and launch generation through the normal pipeline."],
            ),
        )

    # --- clarification: a comparison mode with no candidate models -------------
    if request.mode in _COMPARISON_MODES and not request.candidate_models:
        return PlannerResult(
            design=None,
            clarification=ClarificationRequest(
                missing_fields=["candidate_models"],
                questions=["Which models or agents should be compared?"],
                why_needed="A comparison mode needs at least the candidate models to evaluate.",
            ),
        )

    # --- detect capability markers from intent --------------------------------
    is_smoke = _has(intent, _SMOKE)
    wants_reliability = _has(intent, _RELIABILITY)
    claims_cross = _has(intent, _CROSS_SERVER)
    claims_long = _has(intent, _LONG_CHAIN)
    claims_recovery = _has(intent, _RECOVERY)
    claims_same_name = _has(intent, _SAME_NAME)

    profile = dict(_MODE_PROFILE[request.mode])
    scope = "smoke_test_only" if is_smoke else profile["scope"]
    confirmatory = scope in (
        "confirmatory_model_selection",
        "leaderboard_ranking",
        "regression_non_inferiority",
    )

    metric = profile["metric"]
    crit_refs = [
        _ref(profile["crit_rule"], "criterion_choice"),
        _ref(profile["metric_rule"], "metric_choice"),
    ]
    if wants_reliability and request.mode in ("pairwise", "leaderboard"):
        metric = "pass_at_3"
        crit_refs = [_ref(profile["crit_rule"], "criterion_choice"), _ref("G2.metric.pass3", "metric_choice")]

    # --- task distribution -----------------------------------------------------
    if claims_long:
        short, medium, long = 0.2, 0.3, 0.5
    else:
        short, medium, long = 0.3, 0.4, 0.3
    categories: list[str] = []
    if claims_cross:
        categories.append("cross_server")
    if claims_long:
        categories.append("long_chain")
    if claims_recovery:
        categories.append("recovery")
    if claims_same_name:
        categories.append("same_name")
    if not categories:
        categories.append("general")

    diagnostic_slices = []
    if request.mode == "diagnostic" and claims_same_name:
        diagnostic_slices.append(
            {
                "slice_id": "slice.same_name",
                "label": "same-name / wrong-server confusion",
                "ratio": 0.4,
                "confirmatory": False,
            }
        )

    td: dict[str, Any] = {
        "short_chain": short,
        "medium_chain": medium,
        "long_chain": long,
        "cross_server_ratio": 0.35 if claims_cross else 0.1,
        "recovery_required_ratio": 0.15 if claims_recovery else 0.05,
        "prerequisite_strict_ratio": 0.2,
        "stateful_write_ratio": 0.0,
        "categories": categories,
        "distractors": {
            "same_name_fraction": 0.4 if claims_same_name else 0.1,
            "near_miss_fraction": 0.1,
            "cross_domain_fraction": 0.0,
            "random_fraction": 0.0,
        },
        "diagnostic_slices": diagnostic_slices,
    }

    # apply user overrides for known distribution fields
    overrides = request.user_overrides or {}
    for key in _DISTRIBUTION_OVERRIDE_KEYS:
        if key in overrides:
            td[key] = overrides[key]

    # sandbox: default safe-true when stateful; an explicit override wins.
    sandbox_required = bool(overrides.get("sandbox_required", td["stateful_write_ratio"] > 0))

    # --- criterion + hypotheses + analysis plan -------------------------------
    mde = (
        request.target_detectable_effect_pp
        if request.target_detectable_effect_pp is not None
        else planned_mde_pp(request.task_budget)
    )
    margin = request.target_detectable_effect_pp if request.mode == "regression" else None
    if request.mode == "regression" and margin is None:
        margin = 5.0

    criterion = Criterion(
        criterion_id="criterion.primary",
        purpose=f"Primary {request.mode} comparison on the planned distribution.",
        estimand=profile["estimand"],
        null_hypothesis="the candidates do not differ on the planned distribution",
        alternative_hypothesis="the candidates differ on the planned distribution",
        primary_metric=metric,
        test_family=profile["test"],
        alpha=request.alpha,
        beta_or_target_power=round(1.0 - request.beta, 6),
        minimum_detectable_effect_pp=mde,
        required_data=["per_task_effect_pass"],
        decision_rule="apply the planned test family at the stated alpha to per-task effect-pass outcomes",
        allowed_claim="a difference on the planned task distribution; not a universal ranking",
        failure_modes=["underpowered if the task budget is too small", "biased if the task mix is skewed"],
        confirmatory=confirmatory,
        guide_references=crit_refs,
        selection_rationale=(
            f"the {request.mode} question maps to {metric} under {profile['intent_rule']}, so the planned "
            "comparison family follows directly from the guide"
        ),
    )

    design = AdvisorDesign(
        evaluation_question=request.intent,
        mode=request.mode,
        claim_scope=scope,
        candidate_models=request.candidate_models,
        task_budget=request.task_budget,
        attempts_per_task=request.attempts_per_task,
        target_detectable_effect_pp=request.target_detectable_effect_pp,
        estimand=profile["estimand"],
        hypotheses={
            "null": "the candidates do not differ on the planned distribution",
            "alternative": "the candidates differ on the planned distribution",
            "non_inferiority_margin_pp": margin,
        },
        criteria=[criterion],
        task_distribution=td,
        analysis_plan={
            "ci_method": profile["ci"],
            "mde_method": profile["mde"],
            "rank_stability_method": profile["rank"],
            "pairwise_test": profile["pairwise_test"],
            "alpha": request.alpha,
            "beta": request.beta,
            "planning_assumptions": ["baseline effect-pass rate assumed near 0.5 for planning"],
            "heuristic_label": "planning_heuristic",
        },
        claim_boundary=_CLAIM_BOUNDARY[request.mode],
        intent_evidence=[request.intent],
        statistical_guide_version="statistical_guide.v1",
    )

    ledger = _build_ledger(
        request, metric, profile, categories, td, wants_reliability, intent_raw=request.intent
    )
    return PlannerResult(design=design, evidence_ledger=ledger, sandbox_required=sandbox_required)


def _build_ledger(
    request, metric, profile, categories, td, wants_reliability, *, intent_raw
) -> list[EvidenceLedgerEntry]:
    ledger: list[EvidenceLedgerEntry] = []

    metric_rule = "G2.metric.pass3" if metric == "pass_at_3" else profile["metric_rule"]
    ledger.append(
        _ev(
            "primary_metric",
            metric,
            intent_raw if wants_reliability else None,
            "the primary metric follows from the requested comparison and the guide's metric rules",
            f"Primary metric is {metric}, the planned estimand for a {request.mode} question.",
            [_ref(metric_rule, "metric_choice")],
            hint="does the metric match the user's primary question?",
        )
    )
    ledger.append(
        _ev(
            "task_budget",
            request.task_budget,
            None,
            "the task budget sets the mode's power band per the validator thresholds",
            f"{request.task_budget} tasks set the {request.mode} power band; larger budgets shrink the MDE.",
            [_ref("G4.budget.mode_thresholds", "budget_power")],
            hint="is the budget adequate for the claimed effect size?",
        )
    )
    attempts_rule = "G4.repeats.pass3" if metric == "pass_at_3" else "G4.budget.mode_thresholds"
    ledger.append(
        _ev(
            "attempts_per_task",
            request.attempts_per_task,
            intent_raw if wants_reliability else None,
            "repeats support reliability/pass@k claims",
            f"{request.attempts_per_task} attempts per task; a pass@3 claim needs at least 3.",
            [_ref(attempts_rule, "budget_power")],
        )
    )

    coverage_rule = {
        "cross_server": "G3.coverage.cross_server",
        "long_chain": "G3.coverage.long_workflows",
        "recovery": "G3.coverage.recovery",
        "same_name": "G3.coverage.same_name",
    }
    coverage_attr = {
        "cross_server": "cross_server_ratio",
        "long_chain": "long_chain",
        "recovery": "recovery_required_ratio",
    }
    claimed = [c for c in categories if c in coverage_rule]
    if claimed:
        for cap in claimed:
            ledger.append(
                _ev(
                    f"task_distribution.{coverage_attr.get(cap, cap)}",
                    td.get(coverage_attr.get(cap, cap)),
                    intent_raw,
                    f"the request emphasizes {cap}, so the distribution allocates that coverage",
                    f"{cap} coverage raised because the request emphasizes it.",
                    [_ref(coverage_rule[cap], "distribution_choice")],
                )
            )
    else:
        ledger.append(
            _ev(
                "task_distribution",
                {
                    "short_chain": td["short_chain"],
                    "medium_chain": td["medium_chain"],
                    "long_chain": td["long_chain"],
                },
                None,
                "no specific capability was emphasized, so a balanced chain mix is the default",
                "Balanced chain mix (default; no capability emphasized).",
                [_ref("G7.rationale.default", "distribution_choice")],
            )
        )

    ledger.append(
        _ev(
            "criteria.primary",
            "criterion.primary",
            intent_raw,
            "the primary criterion is selected from the guide's criterion family for this mode",
            f"Primary criterion uses {profile['test']} per {profile['crit_rule']}.",
            [_ref(profile["crit_rule"], "criterion_choice")],
            hint="does the criterion's allowed_claim stay within the claim boundary?",
        )
    )
    return ledger
