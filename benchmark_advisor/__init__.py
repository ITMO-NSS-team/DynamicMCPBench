"""Benchmark Advisor — statistically aware pre-run planning module for DMCP Studio.

This top-level package is a separate logical module from the core ``dmcp``
pipeline (architecture dependency direction: ``dmcp-studio`` -> ``benchmark_advisor``
-> lightweight ``dmcp`` stats helpers; the advisor never imports Studio). v1 ships
the Stage-1 planning loop; Stage 2 is interface-only.

See ``docs_benchmark_advisor/`` for the concept, plan, and frozen contracts.

Scope of this ``__init__``: re-export the v1 schema layer and version constants.
"""

from __future__ import annotations

from .schema import (
    GUIDE_VERSION,
    REPORT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AdvisorDesign,
    AdvisorRequest,
    AdvisorResponse,
    AdvisorValidationRequest,
    AnalysisPlan,
    ClarificationRequest,
    Criterion,
    DeploymentContext,
    DiagnosticSlice,
    DistractorPolicy,
    EvidenceLedgerEntry,
    ExportConfig,
    ExportGenerationKnobs,
    HypothesisPlan,
    OutcomeTensorContract,
    Refusal,
    StatisticalGuideReference,
    TaskDistribution,
    ValidationReportStub,
    WarningCard,
    response_state_violations,
)

__all__ = [
    "GUIDE_VERSION",
    "REPORT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "AdvisorDesign",
    "AdvisorRequest",
    "AdvisorResponse",
    "AdvisorValidationRequest",
    "AnalysisPlan",
    "ClarificationRequest",
    "Criterion",
    "DeploymentContext",
    "DiagnosticSlice",
    "DistractorPolicy",
    "EvidenceLedgerEntry",
    "ExportConfig",
    "ExportGenerationKnobs",
    "HypothesisPlan",
    "OutcomeTensorContract",
    "Refusal",
    "StatisticalGuideReference",
    "TaskDistribution",
    "ValidationReportStub",
    "WarningCard",
    "response_state_violations",
]
