"""Tests for the BA5.2 offline guide citation index."""

from __future__ import annotations

import pytest

from benchmark_advisor.guide import KNOWN_RULE_IDS
from benchmark_advisor.guide_citations import (
    DEFAULT_GUIDE_PATH,
    GuideCitationIndexError,
    load_guide_citation_index,
)
from benchmark_advisor.schema import TEST_FAMILIES
from benchmark_advisor.validator import validate_design
from tests.test_benchmark_advisor_validator import design


def test_guide_citation_index_is_deterministic_and_offline():
    first = load_guide_citation_index()
    second = load_guide_citation_index()

    assert set(first.records) == KNOWN_RULE_IDS
    assert first.records == second.records
    assert first.source_references == second.source_references


def test_rule_lookup_returns_audited_v2_citation():
    index = load_guide_citation_index()

    citation = index.citation_for_rule("G5.criterion.paired_bootstrap")

    assert citation.source_id == "statistical_guide.v1:G5.criterion.paired_bootstrap"
    assert citation.source_keys
    assert set(citation.source_keys) <= set(index.source_references)
    assert citation.guide_references[0].rule_id == "G5.criterion.paired_bootstrap"
    assert citation.guide_references[0].section == citation.section
    assert citation.snippet


def test_lookup_by_method_family_and_advisor_mode():
    index = load_guide_citation_index()

    method_rules = [
        c.guide_references[0].rule_id
        for c in index.citations_for_method_family("paired_bootstrap")
    ]
    mode_rules = [c.guide_references[0].rule_id for c in index.citations_for_advisor_mode("pairwise")]

    assert method_rules == [
        "G5.criterion.paired_bootstrap",
        "G2.metric.pairwise_delta",
        "G4.repeats.not_independent_tasks",
    ]
    assert mode_rules == [
        "G1.pairwise.selection",
        "G2.metric.pairwise_delta",
        "G5.criterion.paired_bootstrap",
        "G6.claim.no_universal_best",
    ]


def test_lookup_accepts_contract_test_family_names():
    index = load_guide_citation_index()

    for test_family in TEST_FAMILIES:
        citations = index.citations_for_method_family(test_family)
        assert citations, test_family

    assert [
        c.guide_references[0].rule_id
        for c in index.citations_for_method_family("non_inferiority_margin")
    ] == [
        "G1.regression.non_inferiority",
        "G2.metric.non_inferiority",
        "G5.criterion.non_inferiority",
    ]


def test_legacy_method_family_aliases_still_work():
    index = load_guide_citation_index()

    assert index.citations_for_method_family("wilson_planning") == index.citations_for_method_family(
        "two_proportion_wilson"
    )
    assert index.citations_for_method_family("diagnostic") == index.citations_for_method_family(
        "diagnostic_descriptive"
    )


def test_every_citation_maps_to_known_rule_ids_and_source_keys():
    index = load_guide_citation_index()

    for rule_id in sorted(KNOWN_RULE_IDS):
        record = index.records[rule_id]
        citation = index.citation_for_rule(rule_id)
        assert citation.guide_references[0].rule_id in KNOWN_RULE_IDS
        assert citation.source_keys
        assert set(citation.source_keys) <= set(index.source_references)
        assert record.validator_behavior
        assert record.repair_suggestions == ""


def test_missing_source_keys_fail_index_audit(tmp_path):
    original = DEFAULT_GUIDE_PATH.read_text(encoding="utf-8")
    edited = "\n".join(
        line for line in original.splitlines() if not line.startswith("| `Dror2017` |")
    )
    guide_path = tmp_path / "STATISTICAL_GUIDE.md"
    guide_path.write_text(edited, encoding="utf-8")

    with pytest.raises(GuideCitationIndexError, match="missing source keys"):
        load_guide_citation_index(guide_path)


def test_validator_behavior_is_unchanged_by_citation_snippet_text(tmp_path):
    original = DEFAULT_GUIDE_PATH.read_text(encoding="utf-8")
    edited = original.replace(
        "pairwise model selection | Paired bootstrap over tasks",
        "pairwise model selection | Changed local explanatory snippet",
    )
    guide_path = tmp_path / "STATISTICAL_GUIDE.md"
    guide_path.write_text(edited, encoding="utf-8")

    original_citation = load_guide_citation_index().citation_for_rule("G5.criterion.paired_bootstrap")
    edited_citation = load_guide_citation_index(guide_path).citation_for_rule(
        "G5.criterion.paired_bootstrap"
    )
    assert edited_citation.snippet != original_citation.snippet

    base_design = design(task_budget=70)
    base_outcome = validate_design(base_design)
    mutated_outcome = validate_design(base_design)

    assert mutated_outcome.status == base_outcome.status
    assert [w.model_dump() for w in mutated_outcome.warnings] == [
        w.model_dump() for w in base_outcome.warnings
    ]
