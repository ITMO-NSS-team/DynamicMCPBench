"""Frozen registry of the v1 statistical guide rule ids (supports BA2.1).

The curated knowledge lives in ``docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md``
(``statistical_guide.v1``, frozen per decision D3). This module is the *runtime*
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
        # G2 - Estimand And Metric Selection
        "G2.metric.effect_pass",
        "G2.metric.pass3",
        "G2.metric.pairwise_delta",
        "G2.metric.non_inferiority",
        "G2.metric.rank_stability",
        "G2.metric.diagnostic_slice",
        # G3 - Task Distribution
        "G3.coverage.long_workflows",
        "G3.coverage.cross_server",
        "G3.coverage.recovery",
        "G3.coverage.same_name",
        "G3.coverage.stateful",
        # G4 - Budget, Power, And Repeats
        "G4.budget.mode_thresholds",
        "G4.repeats.pass3",
        "G4.mde.heuristic",
        "G4.mde.underpowered",
        "G4.slices.limit",
        # G5 - Criterion Selection
        "G5.criterion.paired_bootstrap",
        "G5.criterion.wilson_planning",
        "G5.criterion.non_inferiority",
        "G5.criterion.rank_stability",
        "G5.criterion.descriptive_diagnostic",
        # G6 - Claim Boundaries
        "G6.claim.no_universal_best",
        "G6.claim.no_external_validity",
        "G6.claim.public_logs_prior",
        "G6.claim.no_final_answer",
        "G6.claim.diagnostic_not_selection",
        # G7 - Rationale And UI Explanation
        "G7.rationale.parameter",
        "G7.rationale.criterion",
        "G7.rationale.default",
        "G7.rationale.hover",
        "G7.rationale.future_judge",
    }
)


def is_known_rule(rule_id: str) -> bool:
    return rule_id in KNOWN_RULE_IDS
