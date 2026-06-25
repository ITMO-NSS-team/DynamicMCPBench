"""Benchmark Advisor composition service (supports BA3.1 / T05).

Composes the deterministic planner, validator, and export builder into the two
public operations the Studio API exposes, returning a fully-formed
``AdvisorResponse`` that honors the response state matrix:

- ``advisor_design(request)``  -> plan, then validate, then (if exportable) export;
- ``advisor_validate(vreq)``   -> validate a user-edited structured design only.

The planner proposes and the validator decides; this layer never launches
generation or evaluation. Keeping it in the advisor package (not the Studio
backend) keeps it framework-free and unit-testable.
"""

from __future__ import annotations

from .export import build_export_config, is_exportable
from .planner import plan
from .schema import (
    AdvisorDesign,
    AdvisorRequest,
    AdvisorResponse,
    AdvisorValidationRequest,
    ClarificationRequest,
    EvidenceLedgerEntry,
    OutcomeTensorContract,
    Refusal,
    ValidationReportStub,
    WarningCard,
)
from .validator import ValidationOutcome, validate_design


def _report_stub() -> ValidationReportStub:
    """The Stage-2 interface placeholder carried on every response (not implemented)."""
    return ValidationReportStub(
        schema_version="benchmark_advisor.report.v1",
        implemented=False,
        outcome_tensor=OutcomeTensorContract(
            shape="X[task, model, attempt, metric, slice]",
            task_axis="task id, spec schema version, complexity profile, and slice labels",
            model_axis="candidate model label and provider family",
            attempt_axis="zero-based attempt index and deterministic replay seed if used",
            metric_axis="allowed metric labels from primary_metric",
            slice_axis="all plus diagnostic slice ids",
            missingness_policy="explicit_null_with_reason",
            stage_2_only=True,
        ),
        supported_future_questions=[
            "models_above_success_threshold",
            "pairwise_win_probability",
            "rank_stability",
            "slice_failure_diagnostics",
        ],
    )


def _response(
    status: str,
    *,
    design: AdvisorDesign | None,
    warnings: list[WarningCard],
    refusal: Refusal | None = None,
    clarification: ClarificationRequest | None = None,
    evidence: list[EvidenceLedgerEntry] | None = None,
    export_config=None,
) -> AdvisorResponse:
    return AdvisorResponse(
        schema_version="benchmark_advisor.v1",
        status=status,
        design=design,
        warnings=warnings,
        refusal=refusal,
        clarification=clarification,
        evidence_ledger=evidence or [],
        export_config=export_config,
        validation_report_stub=_report_stub(),
    )


def _compose(
    design: AdvisorDesign,
    outcome: ValidationOutcome,
    evidence: list[EvidenceLedgerEntry],
    *,
    sandbox_required: bool | None,
) -> AdvisorResponse:
    """Turn a validator verdict into a state-matrix-correct response."""
    if outcome.status in ("refused", "needs_clarification"):
        # refused/clarification carry no export and (for clarification) no design.
        return _response(
            outcome.status,
            design=design if outcome.status == "refused" else None,
            warnings=outcome.warnings,
            refusal=outcome.refusal,
            clarification=outcome.clarification,
            evidence=evidence,
        )
    export = None
    if is_exportable(outcome.status):
        export = build_export_config(design, outcome.warnings, sandbox_required=sandbox_required)
    return _response(
        outcome.status,
        design=design,
        warnings=outcome.warnings,
        evidence=evidence,
        export_config=export,
    )


def advisor_design(request: AdvisorRequest) -> AdvisorResponse:
    """Plan a design from intent, validate it, and attach an export preview."""
    proposal = plan(request)
    if proposal.refusal is not None:
        return _response(
            "refused", design=None, warnings=[], refusal=proposal.refusal, evidence=proposal.evidence_ledger
        )
    if proposal.clarification is not None:
        return _response(
            "needs_clarification",
            design=None,
            warnings=[],
            clarification=proposal.clarification,
            evidence=proposal.evidence_ledger,
        )
    outcome = validate_design(proposal.design, sandbox_required=proposal.sandbox_required)
    return _compose(
        proposal.design, outcome, proposal.evidence_ledger, sandbox_required=proposal.sandbox_required
    )


def advisor_validate(vreq: AdvisorValidationRequest) -> AdvisorResponse:
    """Validate a user-edited structured design (no planner; the validator decides)."""
    sandbox_required: bool | None = None
    if vreq.original_request is not None:
        ov = vreq.original_request.user_overrides or {}
        if "sandbox_required" in ov:
            sandbox_required = bool(ov["sandbox_required"])
    outcome = validate_design(vreq.design, sandbox_required=sandbox_required)
    return _compose(vreq.design, outcome, evidence=[], sandbox_required=sandbox_required)
