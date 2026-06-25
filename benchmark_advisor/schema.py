"""Benchmark Advisor v1 schema layer (BA1.1 / T01).

Typed, frozen wire/disk contracts for the statistically aware pre-run planning
module described in ``docs_benchmark_advisor/planning/INTERFACES.md``. Every model
here is a faithful Pydantic v2 transcription of that doc's field lists, enum
registries, and the response state matrix.

Scope of v1 (this module):
- shared types, enum registries, and version constants;
- ``ConfigDict(extra="forbid")`` everywhere; nullable-but-required fields are
  declared nullable AND required (absent != null, per the contract);
- a pure ``response_state_violations`` helper so the response state matrix can be
  checked at the helper level.

Out of scope (other tasks own these):
- the planner adapter (T03), the deterministic validator (T02), planning
  statistics (T04), the Studio API/UI (T05/T06), and the export handoff (T07).
  No statistical judgment, no distribution-sum checks, no cross-field defensibility
  logic lives here — only structural validation and serialization.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# --- version constants (frozen; changing these is an integration decision) -----

SCHEMA_VERSION = "benchmark_advisor.v1"
REPORT_SCHEMA_VERSION = "benchmark_advisor.report.v1"
GUIDE_VERSION = "statistical_guide.v1"

# --- reusable constrained scalar types -----------------------------------------

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]
"""Float in [0, 1]."""
PercentPoints = Annotated[float, Field(gt=0.0, le=100.0)]
"""Float in (0, 100]."""
CountGe1 = Annotated[int, Field(ge=1)]
"""Integer >= 1."""
UnitOpen = Annotated[float, Field(gt=0.0, lt=1.0)]
"""Float in (0, 1) — alpha/beta/power."""

# --- enum registries (string literals; part of the frozen contract) ------------

Status = Literal["approved", "warning", "refused", "needs_clarification"]
Mode = Literal["pairwise", "leaderboard", "regression", "diagnostic"]
ClaimScope = Literal[
    "confirmatory_model_selection",
    "leaderboard_ranking",
    "regression_non_inferiority",
    "diagnostic_slice",
    "smoke_test_only",
]
PrimaryMetric = Literal[
    "trace_effect_pass_rate",
    "pass_at_3",
    "pairwise_delta_pp",
    "non_inferiority_margin_pp",
    "rank_stability",
    "slice_failure_rate",
]
TestFamily = Literal[
    "paired_bootstrap",
    "two_proportion_wilson",
    "non_inferiority_margin",
    "rank_stability_bootstrap",
    "diagnostic_descriptive",
]
CIMethod = Literal["wilson_score", "paired_bootstrap", "stratified_bootstrap"]
MDEMethod = Literal["normal_approx_two_proportion", "paired_bootstrap_heuristic"]
RankStabilityMethod = Literal["bootstrap_tasks_within_strata", "not_applicable"]
WarningCode = Literal[
    "underpowered_design",
    "too_few_repeats",
    "task_mix_bias",
    "insufficient_cross_server_coverage",
    "insufficient_long_chain_coverage",
    "insufficient_recovery_coverage",
    "too_many_secondary_slices",
    "public_logs_are_prior_only",
    "smoke_test_only",
]
RefusalCode = Literal[
    "cannot_support_claim",
    "invalid_distribution",
    "insufficient_budget",
    "unsupported_final_answer_claim",
    "generation_launch_forbidden",
    "missing_required_design_field",
]
ValidatorStatus = Literal["approved", "warning", "refused", "needs_clarification"]
RationaleRole = Literal[
    "intent_mapping",
    "metric_choice",
    "criterion_choice",
    "distribution_choice",
    "budget_power",
    "claim_boundary",
    "ui_explanation",
]
Severity = Literal["info", "warning", "critical"]
GoalStrategy = Literal[
    "deployment_slice",
    "leaderboard_mix",
    "regression_replay",
    "diagnostic_slice",
]
FutureQuestion = Literal[
    "models_above_success_threshold",
    "pairwise_win_probability",
    "rank_stability",
    "slice_failure_diagnostics",
]

# Tuple views of the registries, for downstream validators/fixtures (T02/T08).
STATUSES = get_args(Status)
MODES = get_args(Mode)
CLAIM_SCOPES = get_args(ClaimScope)
PRIMARY_METRICS = get_args(PrimaryMetric)
TEST_FAMILIES = get_args(TestFamily)
CI_METHODS = get_args(CIMethod)
MDE_METHODS = get_args(MDEMethod)
RANK_STABILITY_METHODS = get_args(RankStabilityMethod)
WARNING_CODES = get_args(WarningCode)
REFUSAL_CODES = get_args(RefusalCode)
VALIDATOR_STATUSES = get_args(ValidatorStatus)
RATIONALE_ROLES = get_args(RationaleRole)
SEVERITIES = get_args(Severity)
GOAL_STRATEGIES = get_args(GoalStrategy)
FUTURE_QUESTIONS = get_args(FutureQuestion)


class _Base(BaseModel):
    """All advisor schemas forbid unknown fields (CLAUDE.md schema discipline)."""

    model_config = ConfigDict(extra="forbid")


# --- shared leaf types ---------------------------------------------------------


class StatisticalGuideReference(_Base):
    guide_version: Literal["statistical_guide.v1"]
    rule_id: NonEmptyStr
    section: NonEmptyStr
    role: RationaleRole


class HypothesisPlan(_Base):
    # Field is named ``null`` in the contract (the null hypothesis); not a Python
    # keyword, so it is a valid attribute name.
    null: NonEmptyStr
    alternative: NonEmptyStr
    non_inferiority_margin_pp: PercentPoints | None


class DistractorPolicy(_Base):
    same_name_fraction: Ratio
    near_miss_fraction: Ratio
    cross_domain_fraction: Ratio
    random_fraction: Ratio


class DiagnosticSlice(_Base):
    slice_id: NonEmptyStr
    label: NonEmptyStr
    ratio: Ratio
    confirmatory: bool


class TaskDistribution(_Base):
    short_chain: Ratio
    medium_chain: Ratio
    long_chain: Ratio
    cross_server_ratio: Ratio
    recovery_required_ratio: Ratio
    prerequisite_strict_ratio: Ratio
    stateful_write_ratio: Ratio
    categories: Annotated[list[NonEmptyStr], Field(min_length=1)]
    distractors: DistractorPolicy
    diagnostic_slices: list[DiagnosticSlice]


class AnalysisPlan(_Base):
    ci_method: CIMethod
    mde_method: MDEMethod
    rank_stability_method: RankStabilityMethod
    pairwise_test: TestFamily | None
    alpha: UnitOpen
    beta: UnitOpen
    planning_assumptions: Annotated[list[NonEmptyStr], Field(min_length=1)]
    heuristic_label: Literal["planning_heuristic"]


class Criterion(_Base):
    criterion_id: NonEmptyStr
    purpose: NonEmptyStr
    estimand: NonEmptyStr
    null_hypothesis: NonEmptyStr
    alternative_hypothesis: NonEmptyStr
    primary_metric: PrimaryMetric
    test_family: TestFamily
    alpha: UnitOpen
    beta_or_target_power: UnitOpen
    minimum_detectable_effect_pp: PercentPoints | None
    required_data: list[NonEmptyStr]
    decision_rule: NonEmptyStr
    allowed_claim: NonEmptyStr
    failure_modes: list[NonEmptyStr]
    confirmatory: bool
    guide_references: Annotated[list[StatisticalGuideReference], Field(min_length=1)]
    selection_rationale: NonEmptyStr


class WarningCard(_Base):
    severity: Severity
    code: WarningCode
    message: NonEmptyStr
    failed_criterion_id: str | None
    statistical_reason: NonEmptyStr | None
    repair_suggestion: NonEmptyStr


class Refusal(_Base):
    code: RefusalCode
    reason: NonEmptyStr
    statistical_reason: NonEmptyStr
    failed_criterion_id: NonEmptyStr
    repair_options: Annotated[list[NonEmptyStr], Field(min_length=1)]


class ClarificationRequest(_Base):
    missing_fields: Annotated[list[NonEmptyStr], Field(min_length=1)]
    questions: Annotated[list[NonEmptyStr], Field(min_length=1)]
    why_needed: NonEmptyStr


class EvidenceLedgerEntry(_Base):
    parameter: NonEmptyStr
    value: Any
    intent_evidence: NonEmptyStr | None
    statistical_rationale: NonEmptyStr
    guide_references: Annotated[list[StatisticalGuideReference], Field(min_length=1)]
    hover_text: NonEmptyStr
    judge_validation_hint: str | None
    validator_status: ValidatorStatus
    repair_suggestion: str | None


class DeploymentContext(_Base):
    """Advisory-only deployment notes carried on a request (never graded)."""

    notes: str | None = None
    private_server_constraints: list[str] = Field(default_factory=list)
    unavailable_servers: list[str] = Field(default_factory=list)


# --- design + export -----------------------------------------------------------


class AdvisorDesign(_Base):
    evaluation_question: NonEmptyStr
    mode: Mode
    claim_scope: ClaimScope
    # May be empty only for diagnostic/smoke designs — enforced by the validator,
    # not here.
    candidate_models: list[NonEmptyStr]
    task_budget: CountGe1
    attempts_per_task: CountGe1
    target_detectable_effect_pp: PercentPoints | None
    estimand: NonEmptyStr
    hypotheses: HypothesisPlan
    criteria: Annotated[list[Criterion], Field(min_length=1)]
    task_distribution: TaskDistribution
    analysis_plan: AnalysisPlan
    claim_boundary: NonEmptyStr
    intent_evidence: list[NonEmptyStr]
    statistical_guide_version: Literal["statistical_guide.v1"]


class ExportGenerationKnobs(_Base):
    handoff_target: Literal["scripts/build_corpus.py"]
    dry_run_only: Literal[True]
    goal_strategy: GoalStrategy
    max_tool_calls_per_task: CountGe1
    server_scope: list[NonEmptyStr]
    sandbox_required: bool
    generation_notes: list[str]


class ExportConfig(_Base):
    schema_version: Literal["benchmark_advisor.v1"]
    mode: Mode
    candidate_models: list[NonEmptyStr]
    evaluation_question: NonEmptyStr
    estimand: NonEmptyStr
    hypotheses: HypothesisPlan
    criteria: Annotated[list[Criterion], Field(min_length=1)]
    tasks: CountGe1
    attempts_per_task: CountGe1
    task_distribution: TaskDistribution
    # Must equal task_distribution.distractors; duplicated for export consumers.
    # Equality is an export-handoff check (T07), not a schema check.
    distractors: DistractorPolicy
    analysis_plan: AnalysisPlan
    warnings: list[WarningCard]
    claim_boundary: NonEmptyStr
    generation_knobs: ExportGenerationKnobs


# --- Stage-2 interface placeholders (declared, not implemented in v1) ----------


class OutcomeTensorContract(_Base):
    shape: Literal["X[task, model, attempt, metric, slice]"]
    task_axis: NonEmptyStr
    model_axis: NonEmptyStr
    attempt_axis: NonEmptyStr
    metric_axis: NonEmptyStr
    slice_axis: NonEmptyStr
    missingness_policy: Literal["explicit_null_with_reason"]
    stage_2_only: Literal[True]


class ValidationReportStub(_Base):
    schema_version: Literal["benchmark_advisor.report.v1"]
    implemented: Literal[False]
    outcome_tensor: OutcomeTensorContract
    supported_future_questions: list[FutureQuestion]


# --- top-level request/response shapes -----------------------------------------


class AdvisorRequest(_Base):
    schema_version: Literal["benchmark_advisor.v1"]
    intent: NonEmptyStr
    mode: Mode
    task_budget: CountGe1
    attempts_per_task: CountGe1
    # Optional fields (see INTERFACES.md "AdvisorRequest").
    candidate_models: list[NonEmptyStr] = Field(default_factory=list)
    target_detectable_effect_pp: PercentPoints | None = None
    alpha: UnitOpen = 0.05
    beta: UnitOpen = 0.2
    deployment_context: DeploymentContext | None = None
    user_overrides: dict[str, Any] = Field(default_factory=dict)


class AdvisorResponse(_Base):
    schema_version: Literal["benchmark_advisor.v1"]
    status: Status
    design: AdvisorDesign | None
    warnings: list[WarningCard]
    refusal: Refusal | None
    clarification: ClarificationRequest | None
    evidence_ledger: list[EvidenceLedgerEntry]
    export_config: ExportConfig | None
    validation_report_stub: ValidationReportStub


class AdvisorValidationRequest(_Base):
    schema_version: Literal["benchmark_advisor.v1"]
    design: AdvisorDesign
    original_request: AdvisorRequest | None = None
    edited_fields: list[str] = Field(default_factory=list)


# --- response state matrix (helper-level check; INTERFACES.md "Response State Matrix")


def response_state_violations(resp: AdvisorResponse) -> list[str]:
    """Return human-readable violations of the response state matrix (empty = ok).

    Pure structural check — no statistical judgment. Kept as a free function so the
    schema classes stay free of validator logic while the matrix is still testable.
    """

    v: list[str] = []
    s = resp.status
    has_blocking = any(w.severity in ("warning", "critical") for w in resp.warnings)

    if s == "approved":
        if resp.design is None:
            v.append("approved requires a non-null design")
        if resp.refusal is not None:
            v.append("approved must not carry a refusal")
        if resp.clarification is not None:
            v.append("approved must not carry a clarification")
        if resp.export_config is None:
            v.append("approved requires a non-null export_config")
        if has_blocking:
            v.append("approved warnings must be severity 'info' only")
    elif s == "warning":
        if resp.design is None:
            v.append("warning requires a non-null design")
        if resp.refusal is not None:
            v.append("warning must not carry a refusal")
        if resp.clarification is not None:
            v.append("warning must not carry a clarification")
        if resp.export_config is None:
            v.append("warning requires a non-null export_config")
        if not has_blocking:
            v.append("warning requires at least one 'warning' or 'critical' card")
    elif s == "refused":
        if resp.refusal is None:
            v.append("refused requires a non-null refusal")
        if resp.clarification is not None:
            v.append("refused must not carry a clarification")
        if resp.export_config is not None:
            v.append("refused must not carry an export_config")
    elif s == "needs_clarification":
        if resp.clarification is None:
            v.append("needs_clarification requires a non-null clarification")
        if resp.refusal is not None:
            v.append("needs_clarification must not carry a refusal")
        if resp.export_config is not None:
            v.append("needs_clarification must not carry an export_config")
    return v
