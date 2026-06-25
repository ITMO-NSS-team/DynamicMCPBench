"""Structural tests for the Benchmark Advisor golden fixtures (BA1.3 / T08).

These check the fixtures are well-formed against the BA1.1 schema and the frozen
fixture format, that they are internally consistent with the response state
matrix, and that every cited guide rule id exists. They do NOT assert
planner/validator behavior — that is T02/T03/T05, which consume these oracles.
"""

from __future__ import annotations

import pytest

from benchmark_advisor.schema import (
    REFUSAL_CODES,
    STATUSES,
    WARNING_CODES,
    AdvisorRequest,
)
from tests import advisor_fixtures as fx

ALL = fx.load_all()
IDS = [f["id"] for f in ALL]

# Scenarios T08 requires the fixture set to cover.
REQUIRED_IDS = {
    "pairwise-finance-valid",
    "leaderboard-small-budget-warning",
    "regression-non-inferiority",
    "diagnostic-same-name",
    "underpowered-refusal",
    "too-few-repeats-warning",
    "low-cross-server-coverage-warning",
    "smoke-test-only",
    "ambiguous-intent-clarification",
    "edited-budget-drops-to-warning",
    "final-answer-grading-refusal",
    "stateful-write-requires-sandbox-refusal",
}

REQUIRED_FIELDS = {
    "id",
    "description",
    "request",
    "expected_status",
    "expected_warning_codes",
    "expected_refusal_code",
    "expected_clarification_missing_fields",
}


def test_at_least_ten_fixtures():
    assert len(ALL) >= 10


def test_ids_are_unique_stable_and_match_filename():
    assert len(IDS) == len(set(IDS)), "duplicate fixture ids"
    for f in ALL:
        fid = f["id"]
        assert fid == fid.lower(), f"{fid} must be lowercase"
        assert " " not in fid and "_" not in fid, f"{fid} must be hyphen-separated"
        assert (fx.FIXTURES_DIR / f"{fid}.json").exists()


def test_required_scenarios_present():
    missing = REQUIRED_IDS - set(IDS)
    assert not missing, f"missing required fixtures: {sorted(missing)}"


@pytest.mark.parametrize("f", ALL, ids=IDS)
def test_fixture_has_required_format_fields(f):
    assert set(f) >= REQUIRED_FIELDS, f"{f.get('id')} missing {REQUIRED_FIELDS - set(f)}"


@pytest.mark.parametrize("f", ALL, ids=IDS)
def test_request_parses_against_schema(f):
    AdvisorRequest.model_validate(f["request"])


@pytest.mark.parametrize("f", ALL, ids=IDS)
def test_expected_enums_are_known(f):
    assert f["expected_status"] in STATUSES
    for code in f["expected_warning_codes"]:
        assert code in WARNING_CODES, f"{f['id']}: unknown warning_code {code}"
    rc = f["expected_refusal_code"]
    assert rc is None or rc in REFUSAL_CODES, f"{f['id']}: unknown refusal_code {rc}"


@pytest.mark.parametrize("f", ALL, ids=IDS)
def test_state_matrix_consistency(f):
    status = f["expected_status"]
    has_export = "expected_export_subset" in f
    if status in ("approved", "warning"):
        assert has_export, f"{f['id']}: {status} must carry an export subset"
        assert f["expected_refusal_code"] is None
        assert not f["expected_clarification_missing_fields"]
    elif status == "refused":
        assert not has_export, f"{f['id']}: refused must not carry an export subset"
        assert f["expected_refusal_code"] is not None
    elif status == "needs_clarification":
        assert not has_export, f"{f['id']}: clarification must not carry an export subset"
        assert f["expected_clarification_missing_fields"], f"{f['id']}: clarification needs missing_fields"
        assert f["expected_refusal_code"] is None


@pytest.mark.parametrize("f", ALL, ids=IDS)
def test_warning_status_lists_at_least_one_code(f):
    if f["expected_status"] == "warning":
        assert f["expected_warning_codes"], f"{f['id']}: warning must name >=1 warning_code"


def test_all_cited_guide_rule_ids_exist():
    known = fx.guide_rule_ids()
    assert known, "no guide rule ids parsed from STATISTICAL_GUIDE.md"
    for f in ALL:
        for rule_id in fx.iter_guide_refs(f):
            assert rule_id in known, f"{f['id']} cites unknown guide rule id {rule_id}"


def test_non_refused_examples_carry_guide_backed_rationale():
    # At least one approved/warning fixture exposes a guide-backed criterion in its
    # export subset (T08: guide-backed rationale entries for non-refused examples).
    cited = [f for f in ALL if fx.iter_guide_refs(f)]
    assert cited, "expected at least one fixture with guide-backed rationale"
    assert any(f["expected_status"] in ("approved", "warning") for f in cited)
