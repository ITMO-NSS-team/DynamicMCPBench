"""Frozen registry of the v1 statistical guide rule ids (supports BA2.1).

The curated knowledge lives in ``benchmark_advisor/data/STATISTICAL_GUIDE.md``
(``statistical_guide.v1``, research-refreshed per BA1.2). This module is the *runtime*
mirror of that document's rule-id registry, so the validator can check guide
references without reading a docs file at runtime (which would break packaged
installs). ``tests/test_benchmark_advisor_guide.py`` asserts this set stays
identical to the document.

Scope: rule-id membership only. No statistical logic, no thresholds.
"""

from __future__ import annotations

GUIDE_VERSION = "statistical_guide.v1"

KNOWN_RULE_IDS: frozenset[str] = frozenset(
    {
        # G1 - Intent To Mode
        "G1.pairwise.selection",
        "G1.leaderboard.ranking",
        "G1.regression.non_inferiority",
        "G1.diagnostic.slice",
        "G1.smoke.budget",
        "G1.intent.primary_question_required",
        "G1.intent.claim_scope_first",
        # G2 - Estimand And Metric Selection
        "G2.metric.effect_pass",
        "G2.metric.execution_primary",
        "G2.metric.pass3",
        "G2.metric.reliability_requires_k",
        "G2.metric.pairwise_delta",
        "G2.metric.non_inferiority",
        "G2.metric.rank_stability",
        "G2.metric.diagnostic_slice",
        "G2.metric.floor_ceiling_sensitivity",
        # G3 - Task Distribution
        "G3.distribution.target_mix_explicit",
        "G3.distribution.stratified_generation",
        "G3.audit.coverage_distance",
        "G3.coverage.long_workflows",
        "G3.coverage.short_workflows",
        "G3.coverage.medium_workflows",
        "G3.coverage.cross_server",
        "G3.coverage.recovery",
        "G3.coverage.same_name",
        "G3.distractor.hard_negative",
        "G3.distractor.near_miss",
        "G3.distractor.claim_requires_pressure",
        "G3.domain.finance",
        "G3.domain.user_named",
        "G3.coverage.stateful",
        "G3.distribution.min_per_primary_stratum",
        # G4 - Budget, Power, And Repeats
        "G4.budget.mode_thresholds",
        "G4.repeats.pass3",
        "G4.repeats.not_independent_tasks",
        "G4.mde.heuristic",
        "G4.mde.underpowered",
        "G4.mde.two_proportion_planning",
        "G4.power.empirical_curves",
        "G4.slices.limit",
        "G4.floor_ceiling.power_warning",
        "G4.clustered_tasks.neff_caveat",
        # G5 - Criterion Selection
        "G5.criterion.paired_bootstrap",
        "G5.criterion.wilson_planning",
        "G5.criterion.non_inferiority",
        "G5.criterion.rank_stability",
        "G5.criterion.descriptive_diagnostic",
        "G5.criterion.bootstrap_score_ci",
        "G5.criterion.stratified_bootstrap",
        "G5.criterion.randomization_fallback",
        "G5.criterion.mcnemar_narrow",
        "G5.criterion.paired_default",
        "G5.multiple.holm_confirmatory",
        "G5.multiple.bh_diagnostic",
        "G5.multiple.primary_vs_exploratory",
        # G6 - Claim Boundaries
        "G6.claim.no_universal_best",
        "G6.claim.no_external_validity",
        "G6.claim.public_logs_prior",
        "G6.claim.no_final_answer",
        "G6.claim.diagnostic_not_selection",
        "G6.warning.floor_ceiling",
        "G6.warning.contamination_artifacts",
        "G6.warning.label_noise",
        "G6.claim.private_transfer_limit",
        "G6.claim.confirmatory_vs_exploratory",
        # G7 - Rationale And UI Explanation
        "G7.rationale.parameter",
        "G7.rationale.criterion",
        "G7.rationale.default",
        "G7.rationale.hover",
        "G7.rationale.future_judge",
        "G7.doc.parameter_status_label",
        "G7.doc.benchmark_card",
        "G7.rationale.repair_actionable",
    }
)


def is_known_rule(rule_id: str) -> bool:
    return rule_id in KNOWN_RULE_IDS
