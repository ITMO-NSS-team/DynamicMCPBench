"""Tests for the Benchmark Advisor composition service (BA3.1 / T05)."""

from __future__ import annotations

from benchmark_advisor.planner import plan
from benchmark_advisor.schema import (
    AdvisorRequest,
    AdvisorValidationRequest,
    response_state_violations,
)
from benchmark_advisor.service import advisor_design, advisor_validate
from tests import advisor_fixtures as fx

ALL = fx.load_all()


def _req(fixture_id: str) -> AdvisorRequest:
    return AdvisorRequest.model_validate(fx.load(fixture_id)["request"])


def test_every_fixture_response_satisfies_state_matrix_and_oracle():
    failures = []
    for f in ALL:
        resp = advisor_design(AdvisorRequest.model_validate(f["request"]))
        # schema-level: response is internally consistent
        violations = response_state_violations(resp)
        if violations:
            failures.append(f"{f['id']}: state-matrix {violations}")
        if resp.status != f["expected_status"]:
            failures.append(f"{f['id']}: status {resp.status} != {f['expected_status']}")
        missing = set(f["expected_warning_codes"]) - {w.code for w in resp.warnings}
        if missing:
            failures.append(f"{f['id']}: missing warnings {missing}")
        rc = f["expected_refusal_code"]
        if rc is not None and (resp.refusal is None or resp.refusal.code != rc):
            failures.append(f"{f['id']}: refusal != {rc}")
    assert not failures, "service mismatches:\n" + "\n".join(failures)


def test_approved_response_has_export_and_report_stub():
    resp = advisor_design(_req("pairwise-finance-valid"))
    assert resp.status == "approved"
    assert resp.export_config is not None
    assert resp.evidence_ledger, "approved design should expose evidence ledger"
    assert resp.validation_report_stub.implemented is False


def test_warning_response_exports_with_warnings_preserved():
    resp = advisor_design(_req("leaderboard-small-budget-warning"))
    assert resp.status == "warning"
    assert resp.export_config is not None
    assert resp.export_config.warnings, "warnings must survive into the export"


def test_refused_response_has_no_export():
    resp = advisor_design(_req("underpowered-refusal"))
    assert resp.status == "refused"
    assert resp.refusal is not None
    assert resp.export_config is None


def test_final_answer_request_is_refused_without_export():
    resp = advisor_design(_req("final-answer-grading-refusal"))
    assert resp.status == "refused"
    assert resp.refusal.code == "unsupported_final_answer_claim"
    assert resp.export_config is None


def test_clarification_response_has_no_export_or_design():
    resp = advisor_design(_req("ambiguous-intent-clarification"))
    assert resp.status == "needs_clarification"
    assert resp.clarification is not None
    assert resp.export_config is None
    assert resp.design is None


def test_validate_route_revalidates_edited_design():
    # Plan a healthy pairwise design, then edit the budget down into the warning band.
    healthy = plan(_req("pairwise-finance-valid")).design
    edited = healthy.model_copy(update={"task_budget": 70})
    vreq = AdvisorValidationRequest(
        schema_version="benchmark_advisor.v1", design=edited, edited_fields=["task_budget"]
    )
    resp = advisor_validate(vreq)
    assert resp.status == "warning"
    assert any(w.code == "underpowered_design" for w in resp.warnings)
    assert resp.export_config is not None
    assert response_state_violations(resp) == []


def test_validate_route_refuses_stateful_without_sandbox():
    design = plan(_req("pairwise-finance-valid")).design
    bad = design.model_copy(
        update={
            "task_distribution": design.task_distribution.model_copy(update={"stateful_write_ratio": 0.2})
        }
    )
    vreq = AdvisorValidationRequest(schema_version="benchmark_advisor.v1", design=bad)
    resp = advisor_validate(vreq)
    assert resp.status == "refused"
    assert resp.refusal.code == "invalid_distribution"
    assert resp.export_config is None
