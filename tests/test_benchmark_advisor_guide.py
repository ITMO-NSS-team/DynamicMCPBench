"""The runtime guide registry must stay identical to STATISTICAL_GUIDE.md (D3)."""

from __future__ import annotations

from benchmark_advisor.guide import GUIDE_VERSION, KNOWN_RULE_IDS, is_known_rule
from tests import advisor_fixtures as fx


def test_runtime_registry_matches_the_frozen_document():
    documented = fx.guide_rule_ids()
    assert documented, "no rule ids parsed from STATISTICAL_GUIDE.md"
    assert documented == KNOWN_RULE_IDS, (
        f"guide.py out of sync with the doc; "
        f"only-in-doc={documented - KNOWN_RULE_IDS}, only-in-code={KNOWN_RULE_IDS - documented}"
    )


def test_guide_version_constant():
    assert GUIDE_VERSION == "statistical_guide.v1"


def test_is_known_rule():
    assert is_known_rule("G5.criterion.paired_bootstrap")
    assert not is_known_rule("G9.bogus.rule")


def test_ba1_4_required_g3_rules_are_registered():
    required = {
        "G3.coverage.short_workflows",
        "G3.coverage.medium_workflows",
        "G3.coverage.long_workflows",
        "G3.domain.finance",
        "G3.domain.user_named",
        "G3.coverage.same_name",
        "G3.distractor.hard_negative",
        "G3.distractor.near_miss",
        "G3.distractor.claim_requires_pressure",
    }
    assert required <= KNOWN_RULE_IDS
