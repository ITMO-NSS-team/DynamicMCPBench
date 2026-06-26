"""Adversarial hardening for the Benchmark Advisor (BA4.2 / T10, trimmed per D4).

Pins the invariants that protect the advisor's scientific honesty: overclaiming
and unsupported-claim refusals, unknown guide references, distribution/state-matrix
integrity, no final-answer grading, no Stage-2 creep, and the no-export rule for
refused/clarification designs.
"""

from __future__ import annotations

from benchmark_advisor.planner import plan
from benchmark_advisor.schema import (
    PRIMARY_METRICS,
    AdvisorRequest,
    response_state_violations,
)
from benchmark_advisor.service import advisor_design
from benchmark_advisor.validator import validate_design
from tests import advisor_fixtures as fx
from tests.test_benchmark_advisor_validator import _criterion, design

ALL = fx.load_all()

# Phrases an honest pre-run advisor must never put in user-facing design text.
_BANNED = (
    "universally better",
    "universally best",
    "best model overall",
    "final answer",
    "public logs prove",
    "proves private",
    "represents your private",
    "guarantees external validity",
)


def _req(fixture_id: str) -> AdvisorRequest:
    return AdvisorRequest.model_validate(fx.load(fixture_id)["request"])


# --- refusals -----------------------------------------------------------------


def test_invalid_distribution_is_refused():
    out = validate_design(
        design(task_distribution={"short_chain": 0.6, "medium_chain": 0.6, "long_chain": 0.1})
    )
    assert out.status == "refused" and out.refusal.code == "invalid_distribution"


def test_overbroad_diagnostic_claim_is_refused():
    out = validate_design(design(mode="diagnostic", candidate_models=[]))
    assert out.status == "refused" and out.refusal.code == "cannot_support_claim"


def test_unknown_guide_reference_is_refused():
    bad = _criterion()
    bad["guide_references"][0]["rule_id"] = "G9.not.real"
    out = validate_design(design(criteria=[bad]))
    assert out.status == "refused" and out.refusal.code == "missing_required_design_field"


def test_final_answer_grading_is_refused_and_metric_enum_excludes_it():
    resp = advisor_design(_req("final-answer-grading-refusal"))
    assert resp.status == "refused" and resp.refusal.code == "unsupported_final_answer_claim"
    assert resp.export_config is None
    # the schema itself cannot express a final-answer metric
    assert not any("final" in m or "answer" in m for m in PRIMARY_METRICS)


def test_stateful_write_without_sandbox_is_refused():
    out = validate_design(design(task_distribution={"stateful_write_ratio": 0.3}))
    assert out.status == "refused" and out.refusal.code == "invalid_distribution"


# --- thresholds at the boundary -----------------------------------------------


def test_pairwise_budget_boundaries_are_exact():
    assert validate_design(design(task_budget=100)).status == "approved"
    assert validate_design(design(task_budget=99)).status == "warning"
    assert validate_design(design(task_budget=60)).status == "warning"
    assert validate_design(design(task_budget=59)).status == "refused"


# --- no overclaiming anywhere user-visible ------------------------------------


def test_no_design_emits_banned_overclaiming_language():
    for f in ALL:
        pr = plan(AdvisorRequest.model_validate(f["request"]))
        if pr.design is None:
            continue
        blob = " ".join(
            [
                pr.design.claim_boundary,
                pr.design.estimand,
                *[c.allowed_claim for c in pr.design.criteria],
                *[c.selection_rationale for c in pr.design.criteria],
                *[e.hover_text for e in pr.evidence_ledger],
                *[e.statistical_rationale for e in pr.evidence_ledger],
            ]
        ).lower()
        for phrase in _BANNED:
            assert phrase not in blob, f"{f['id']}: banned phrase '{phrase}'"


# --- state matrix + no-export invariants --------------------------------------


def test_every_fixture_response_is_state_matrix_clean():
    for f in ALL:
        resp = advisor_design(AdvisorRequest.model_validate(f["request"]))
        assert response_state_violations(resp) == [], f"{f['id']}: {response_state_violations(resp)}"


def test_refused_and_clarification_never_export():
    for f in ALL:
        resp = advisor_design(AdvisorRequest.model_validate(f["request"]))
        if resp.status in ("refused", "needs_clarification"):
            assert resp.export_config is None, f"{f['id']}: must not export"


# --- Stage-2 must stay interface-only -----------------------------------------


def test_stage2_is_declared_not_implemented_on_every_response():
    for f in ALL:
        resp = advisor_design(AdvisorRequest.model_validate(f["request"]))
        stub = resp.validation_report_stub
        assert stub.implemented is False
        assert stub.outcome_tensor.stage_2_only is True
