"""Tests for the deterministic Benchmark Advisor validator (BA2.1 / T02)."""

from __future__ import annotations

import copy

from benchmark_advisor.schema import AdvisorDesign
from benchmark_advisor.validator import validate_design


def _criterion(primary_metric: str = "pairwise_delta_pp") -> dict:
    return {
        "criterion_id": "criterion.primary_power",
        "purpose": "Detect a meaningful difference in effect pass rate.",
        "estimand": "paired difference in trace-effect pass rate",
        "null_hypothesis": "no difference between A and B",
        "alternative_hypothesis": "A differs from B",
        "primary_metric": primary_metric,
        "test_family": "paired_bootstrap",
        "alpha": 0.05,
        "beta_or_target_power": 0.8,
        "minimum_detectable_effect_pp": 20.0,
        "required_data": ["per_task_effect_pass"],
        "decision_rule": "reject the null if the paired bootstrap CI excludes 0",
        "allowed_claim": "A differs from B on the planned distribution",
        "failure_modes": ["underpowered if budget too small"],
        "confirmatory": True,
        "guide_references": [
            {
                "guide_version": "statistical_guide.v1",
                "rule_id": "G5.criterion.paired_bootstrap",
                "section": "G5 - Criterion Selection",
                "role": "criterion_choice",
            }
        ],
        "selection_rationale": "the primary question is a pairwise model selection",
    }


_BASE: dict = {
    "evaluation_question": "Which of two agents is better on long finance workflows?",
    "mode": "pairwise",
    "claim_scope": "confirmatory_model_selection",
    "candidate_models": ["agent-a", "agent-b"],
    "task_budget": 120,
    "attempts_per_task": 3,
    "target_detectable_effect_pp": None,
    "estimand": "paired difference in trace-effect pass rate",
    "hypotheses": {
        "null": "no difference",
        "alternative": "A differs from B",
        "non_inferiority_margin_pp": None,
    },
    "criteria": [_criterion()],
    "task_distribution": {
        "short_chain": 0.3,
        "medium_chain": 0.4,
        "long_chain": 0.3,
        "cross_server_ratio": 0.35,
        "recovery_required_ratio": 0.15,
        "prerequisite_strict_ratio": 0.2,
        "stateful_write_ratio": 0.0,
        "categories": ["finance"],
        "distractors": {
            "same_name_fraction": 0.1,
            "near_miss_fraction": 0.1,
            "cross_domain_fraction": 0.0,
            "random_fraction": 0.0,
        },
        "diagnostic_slices": [],
    },
    "analysis_plan": {
        "ci_method": "wilson_score",
        "mde_method": "normal_approx_two_proportion",
        "rank_stability_method": "not_applicable",
        "pairwise_test": "paired_bootstrap",
        "alpha": 0.05,
        "beta": 0.2,
        "planning_assumptions": ["assumed base effect-pass rate near 0.4"],
        "heuristic_label": "planning_heuristic",
    },
    "claim_boundary": "Applies only to the planned distribution; not a universal ranking.",
    "intent_evidence": ["user asked to compare two agents on finance workflows"],
    "statistical_guide_version": "statistical_guide.v1",
}


def design(**overrides) -> AdvisorDesign:
    d = copy.deepcopy(_BASE)
    td = overrides.pop("task_distribution", None)
    if td:
        d["task_distribution"].update(td)
    d.update(overrides)
    return AdvisorDesign.model_validate(d)


def codes(outcome) -> set[str]:
    return {w.code for w in outcome.warnings}


# --- approval -----------------------------------------------------------------


def test_valid_design_is_approved():
    out = validate_design(design())
    assert out.status == "approved"
    assert out.refusal is None and out.clarification is None
    assert not [w for w in out.warnings if w.severity in ("warning", "critical")]


def test_validator_is_deterministic():
    d = design(task_budget=70)
    a, b = validate_design(d), validate_design(d)
    assert a.status == b.status
    assert [w.model_dump() for w in a.warnings] == [w.model_dump() for w in b.warnings]


# --- budget bands -------------------------------------------------------------


def test_pairwise_budget_boundaries():
    assert validate_design(design(task_budget=100)).status == "approved"
    assert validate_design(design(task_budget=99)).status == "warning"
    assert validate_design(design(task_budget=60)).status == "warning"
    refused = validate_design(design(task_budget=59))
    assert refused.status == "refused"
    assert refused.refusal.code == "insufficient_budget"


def test_underpowered_budget_warns_with_code():
    out = validate_design(design(task_budget=70))
    assert out.status == "warning"
    assert "underpowered_design" in codes(out)


def test_leaderboard_band_differs_from_pairwise():
    # 120 is approved for pairwise but a warning for leaderboard (floor 150).
    assert validate_design(design(task_budget=120)).status == "approved"
    lb = validate_design(design(mode="leaderboard", task_budget=120))
    assert lb.status == "warning" and "underpowered_design" in codes(lb)


# --- power: target vs planned MDE --------------------------------------------


def test_ambitious_target_below_planned_mde_is_refused():
    out = validate_design(design(task_budget=120, target_detectable_effect_pp=5.0))
    assert out.status == "refused"
    assert out.refusal.code == "insufficient_budget"


def test_target_in_warning_band_warns():
    # planned MDE at 120 ~ 18.1pp; 15pp is within 25% below -> warning, not refusal.
    out = validate_design(design(task_budget=120, target_detectable_effect_pp=15.0))
    assert out.status == "warning"
    assert "underpowered_design" in codes(out)


def test_target_above_planned_mde_is_approved():
    out = validate_design(design(task_budget=120, target_detectable_effect_pp=20.0))
    assert out.status == "approved"


# --- repeats ------------------------------------------------------------------


def test_too_few_repeats_warns_for_pass3():
    out = validate_design(design(criteria=[_criterion("pass_at_3")], attempts_per_task=2))
    assert out.status == "warning"
    assert "too_few_repeats" in codes(out)


def test_single_attempt_pass3_confirmatory_is_refused():
    out = validate_design(design(criteria=[_criterion("pass_at_3")], attempts_per_task=1))
    assert out.status == "refused"
    assert out.refusal.code == "cannot_support_claim"


# --- coverage -----------------------------------------------------------------


def test_low_cross_server_coverage_warns_when_claimed():
    out = validate_design(
        design(task_distribution={"categories": ["cross_server"], "cross_server_ratio": 0.15})
    )
    assert out.status == "warning"
    assert "insufficient_cross_server_coverage" in codes(out)


def test_very_low_cross_server_coverage_refused_when_claimed():
    out = validate_design(
        design(task_distribution={"categories": ["cross_server"], "cross_server_ratio": 0.05})
    )
    assert out.status == "refused"
    assert out.refusal.code == "cannot_support_claim"


def test_coverage_not_flagged_when_not_claimed():
    # Low cross-server ratio but no cross_server marker in categories -> no warning.
    out = validate_design(design(task_distribution={"categories": ["finance"], "cross_server_ratio": 0.05}))
    assert "insufficient_cross_server_coverage" not in codes(out)


def test_low_long_chain_coverage_warns_when_claimed():
    out = validate_design(
        design(
            task_distribution={
                "categories": ["long_chain"],
                "short_chain": 0.4,
                "medium_chain": 0.4,
                "long_chain": 0.2,
            }
        )
    )
    assert out.status == "warning"
    assert "insufficient_long_chain_coverage" in codes(out)


def test_low_recovery_coverage_warns_when_claimed():
    out = validate_design(
        design(task_distribution={"categories": ["recovery"], "recovery_required_ratio": 0.06})
    )
    assert out.status == "warning"
    assert "insufficient_recovery_coverage" in codes(out)


def test_low_distractor_pressure_warns_when_claimed():
    out = validate_design(
        design(
            task_distribution={
                "categories": ["same_name", "near_miss", "hard_negative"],
                "distractors": {
                    "same_name_fraction": 0.1,
                    "near_miss_fraction": 0.1,
                    "cross_domain_fraction": 0.0,
                    "random_fraction": 0.0,
                },
            }
        )
    )
    assert out.status == "warning"
    assert "task_mix_bias" in codes(out)


def test_very_low_distractor_pressure_refused_when_claimed():
    out = validate_design(
        design(
            task_distribution={
                "categories": ["hard_negative"],
                "distractors": {
                    "same_name_fraction": 0.0,
                    "near_miss_fraction": 0.05,
                    "cross_domain_fraction": 0.0,
                    "random_fraction": 0.0,
                },
            }
        )
    )
    assert out.status == "refused"
    assert out.refusal.code == "cannot_support_claim"


# --- distribution + invariants ------------------------------------------------


def test_chain_fractions_must_sum_to_one():
    out = validate_design(
        design(task_distribution={"short_chain": 0.5, "medium_chain": 0.4, "long_chain": 0.3})
    )
    assert out.status == "refused"
    assert out.refusal.code == "invalid_distribution"


def test_stateful_write_without_sandbox_is_refused():
    out = validate_design(design(task_distribution={"stateful_write_ratio": 0.2}))
    assert out.status == "refused"
    assert out.refusal.code == "invalid_distribution"


def test_stateful_write_with_sandbox_is_allowed():
    out = validate_design(design(task_distribution={"stateful_write_ratio": 0.2}), sandbox_required=True)
    assert out.refusal is None or out.refusal.code != "invalid_distribution"


# --- claim boundaries + clarification -----------------------------------------


def test_diagnostic_claiming_model_selection_is_refused():
    out = validate_design(design(mode="diagnostic", candidate_models=[]))
    assert out.status == "refused"
    assert out.refusal.code == "cannot_support_claim"


def test_missing_candidate_models_needs_clarification():
    out = validate_design(design(candidate_models=[]))
    assert out.status == "needs_clarification"
    assert out.clarification is not None
    assert "candidate_models" in out.clarification.missing_fields


def test_smoke_scope_warns_and_skips_budget_refusal():
    out = validate_design(design(claim_scope="smoke_test_only", task_budget=12))
    assert out.status == "warning"
    assert "smoke_test_only" in codes(out)


# --- guide references ---------------------------------------------------------


def test_unknown_guide_rule_id_is_refused():
    bad = _criterion()
    bad["guide_references"][0]["rule_id"] = "G9.bogus.rule"
    out = validate_design(design(criteria=[bad]))
    assert out.status == "refused"
    assert out.refusal.code == "missing_required_design_field"


# --- refusal completeness -----------------------------------------------------


def test_refusal_carries_all_required_fields():
    out = validate_design(design(task_budget=40))
    r = out.refusal
    assert r is not None
    assert r.reason and r.statistical_reason and r.failed_criterion_id
    assert r.repair_options
