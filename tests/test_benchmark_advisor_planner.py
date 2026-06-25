"""Tests for the deterministic Benchmark Advisor planner (BA2.2 / T03).

Includes the full intent -> design -> validate loop against every golden fixture:
the planner proposes, the validator decides, and the composed verdict must match
each fixture's expected oracle. This is the integration oracle the API (T05) will
also satisfy.
"""

from __future__ import annotations

from benchmark_advisor.guide import is_known_rule
from benchmark_advisor.planner import plan
from benchmark_advisor.schema import AdvisorRequest
from benchmark_advisor.validator import validate_design
from tests import advisor_fixtures as fx

ALL = fx.load_all()
IDS = [f["id"] for f in ALL]


def _resolve(request: AdvisorRequest):
    """Compose planner + validator the way the API (T05) will."""
    pr = plan(request)
    if pr.refusal is not None:
        return "refused", [], pr.refusal.code
    if pr.clarification is not None:
        return "needs_clarification", [], None
    out = validate_design(pr.design, sandbox_required=pr.sandbox_required)
    return out.status, sorted(w.code for w in out.warnings), (out.refusal.code if out.refusal else None)


# --- end-to-end against the golden oracles ------------------------------------


def test_every_fixture_resolves_to_its_expected_oracle():
    failures = []
    for f in ALL:
        req = AdvisorRequest.model_validate(f["request"])
        status, codes, refusal_code = _resolve(req)
        if status != f["expected_status"]:
            failures.append(f"{f['id']}: status {status} != {f['expected_status']}")
            continue
        missing = set(f["expected_warning_codes"]) - set(codes)
        if missing:
            failures.append(f"{f['id']}: missing warning codes {missing} (got {codes})")
        if f["expected_refusal_code"] is not None and refusal_code != f["expected_refusal_code"]:
            failures.append(f"{f['id']}: refusal {refusal_code} != {f['expected_refusal_code']}")
    assert not failures, "fixture mismatches:\n" + "\n".join(failures)


# --- planner-only properties --------------------------------------------------


def _design_for(fixture_id: str):
    req = AdvisorRequest.model_validate(fx.load(fixture_id)["request"])
    return plan(req)


def test_golden_intents_produce_schema_valid_designs():
    # plan() builds AdvisorDesign via the schema, so a returned design is valid.
    built = 0
    for f in ALL:
        pr = plan(AdvisorRequest.model_validate(f["request"]))
        if pr.design is not None:
            assert pr.design.statistical_guide_version == "statistical_guide.v1"
            built += 1
    assert built >= 8


def test_regression_intent_maps_to_regression_criteria():
    pr = _design_for("regression-non-inferiority")
    assert pr.design.mode == "regression"
    assert pr.design.claim_scope == "regression_non_inferiority"
    assert pr.design.criteria[0].test_family == "non_inferiority_margin"
    assert pr.design.hypotheses.non_inferiority_margin_pp is not None


def test_diagnostic_intent_maps_to_diagnostic_claim_boundary():
    pr = _design_for("diagnostic-same-name")
    assert pr.design.claim_scope == "diagnostic_slice"
    assert "diagnostic slice" in pr.design.claim_boundary.lower()
    assert any(s.slice_id == "slice.same_name" for s in pr.design.task_distribution.diagnostic_slices)


def test_reliability_intent_selects_pass_at_3():
    pr = _design_for("too-few-repeats-warning")
    assert pr.design.criteria[0].primary_metric == "pass_at_3"


def test_ambiguous_intent_is_clarification_ready():
    pr = _design_for("ambiguous-intent-clarification")
    assert pr.design is None
    assert pr.clarification is not None
    assert "candidate_models" in pr.clarification.missing_fields


def test_final_answer_intent_is_refused():
    pr = _design_for("final-answer-grading-refusal")
    assert pr.design is None
    assert pr.refusal is not None and pr.refusal.code == "unsupported_final_answer_claim"


def test_every_criterion_cites_known_guide_rules():
    for f in ALL:
        pr = plan(AdvisorRequest.model_validate(f["request"]))
        if pr.design is None:
            continue
        for c in pr.design.criteria:
            assert c.guide_references, f"{f['id']}: criterion without guide refs"
            for ref in c.guide_references:
                assert is_known_rule(ref.rule_id), f"{f['id']}: unknown rule {ref.rule_id}"


def test_evidence_ledger_has_hover_for_major_parameters():
    pr = _design_for("low-cross-server-coverage-warning")
    params = {e.parameter for e in pr.evidence_ledger}
    assert "primary_metric" in params
    assert "task_budget" in params
    assert "attempts_per_task" in params
    assert any(p.startswith("task_distribution") for p in params)
    assert any(p.startswith("criteria") for p in params)
    for e in pr.evidence_ledger:
        assert e.hover_text.strip(), f"empty hover for {e.parameter}"


def test_no_overclaiming_language_in_designs():
    banned = ("universally better", "universally best", "final answer", "best model overall")
    for f in ALL:
        pr = plan(AdvisorRequest.model_validate(f["request"]))
        if pr.design is None:
            continue
        text = " ".join([pr.design.claim_boundary, *[c.allowed_claim for c in pr.design.criteria]]).lower()
        for phrase in banned:
            assert phrase not in text, f"{f['id']}: overclaiming phrase '{phrase}'"


def test_planner_is_deterministic():
    req = AdvisorRequest.model_validate(fx.load("pairwise-finance-valid")["request"])
    a, b = plan(req), plan(req)
    assert a.design.model_dump() == b.design.model_dump()
    assert [e.model_dump() for e in a.evidence_ledger] == [e.model_dump() for e in b.evidence_ledger]
