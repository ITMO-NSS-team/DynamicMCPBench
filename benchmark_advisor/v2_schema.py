"""Benchmark Advisor v2 statistical-advisor contracts (BA5.1 / T11).

V2 is additive: these models do not replace the frozen v1 schemas in
``benchmark_advisor.schema``. They define the richer statistical workbench
surface used by the next advisor wave: statistical plans, all-issue validation,
outcome tensors, reports, and guarded launch job contracts.

Scope of this module:
- strict Pydantic v2 contracts with ``extra="forbid"`` everywhere;
- version constants for v2 route payloads;
- structural checks that keep launch/report payloads honest.

Out of scope:
- planner/RAG implementation, statistical calculations, report generation, and
  background job execution.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import (
    AdvisorDesign,
    DeploymentContext,
    ExportConfig,
    Mode,
    NonEmptyStr,
    PercentPoints,
    Ratio,
    Severity,
    StatisticalGuideReference,
    Status,
    TaskDistribution,
    UnitOpen,
)

V2_SCHEMA_VERSION = "benchmark_advisor.v2"
STATISTICAL_PLAN_SCHEMA_VERSION = "benchmark_advisor.statistical_plan.v2"
OUTCOME_TENSOR_SCHEMA_VERSION = "benchmark_advisor.outcome_tensor.v2"
STATISTICAL_REPORT_SCHEMA_VERSION = "benchmark_advisor.report.v2"
LAUNCH_SCHEMA_VERSION = "benchmark_advisor.launch.v2"
LAUNCH_JOB_SCHEMA_VERSION = "benchmark_advisor.launch_job.v2"

LaunchStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
LaunchPhase = Literal[
    "queued",
    "corpus",
    "top_up",
    "select_corpus",
    "eval",
    "report",
    "succeeded",
    "failed",
    "cancelled",
]


class _Base(BaseModel):
    """All v2 schemas forbid unknown fields."""

    model_config = ConfigDict(extra="forbid")


class LocalStatisticalCitation(_Base):
    source_id: NonEmptyStr
    title: NonEmptyStr
    section: NonEmptyStr
    evidence_status: NonEmptyStr
    source_keys: list[NonEmptyStr] = Field(default_factory=list)
    snippet: NonEmptyStr
    guide_references: list[StatisticalGuideReference] = Field(default_factory=list)


class StatisticalIssue(_Base):
    severity: Severity
    code: NonEmptyStr
    message: NonEmptyStr
    failed_field: str | None
    failed_criterion_id: str | None
    statistical_reason: NonEmptyStr
    repair_options: Annotated[list[NonEmptyStr], Field(min_length=1)]
    guide_references: list[StatisticalGuideReference] = Field(default_factory=list)


class AssumptionLedger(_Base):
    baseline_rate: Ratio | None
    paired_design: bool
    independence_assumption: NonEmptyStr
    repeated_attempts_policy: NonEmptyStr
    missingness_policy: NonEmptyStr
    multiplicity_policy: NonEmptyStr
    sensitivity_notes: list[str] = Field(default_factory=list)
    guide_references: list[StatisticalGuideReference] = Field(default_factory=list)


class PowerCurvePoint(_Base):
    task_budget: Annotated[int, Field(ge=1)]
    mde_pp: PercentPoints
    ci_width_pp: PercentPoints


class BudgetAlternative(_Base):
    task_budget: Annotated[int, Field(ge=1)]
    detectable_effect_pp: PercentPoints
    claim_status: Status


class PlanningDiagnostic(_Base):
    diagnostic_id: NonEmptyStr
    label: NonEmptyStr
    value: float | int | str
    unit: str | None = None
    status: Status | None = None
    interpretation: NonEmptyStr
    guide_references: list[StatisticalGuideReference] = Field(default_factory=list)


class PowerAnalysis(_Base):
    alpha: UnitOpen
    target_power: UnitOpen
    planned_mde_pp: PercentPoints
    ci_width_pp: PercentPoints
    method: NonEmptyStr
    power_curve: list[PowerCurvePoint] = Field(default_factory=list)
    budget_alternatives: list[BudgetAlternative] = Field(default_factory=list)
    planning_diagnostics: list[PlanningDiagnostic] = Field(default_factory=list)
    assumptions: AssumptionLedger


class DesignAlternative(_Base):
    alternative_id: NonEmptyStr
    label: NonEmptyStr
    task_budget: Annotated[int, Field(ge=1)]
    attempts_per_task: Annotated[int, Field(ge=1)]
    target_detectable_effect_pp: PercentPoints | None
    status: Status
    tradeoff: NonEmptyStr
    repair_actions: list[str] = Field(default_factory=list)


class ClaimCard(_Base):
    allowed_claims: Annotated[list[NonEmptyStr], Field(min_length=1)]
    not_allowed_claims: list[str] = Field(default_factory=list)
    plain_language_summary: NonEmptyStr


class ParameterSearchSpace(_Base):
    task_budget_grid: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1)]
    attempts_grid: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1)]
    effect_target_grid_pp: Annotated[list[PercentPoints], Field(min_length=1)]
    distribution_candidates: Annotated[list[TaskDistribution], Field(min_length=1)]
    confirmatory_slice_limit: Annotated[int, Field(ge=1)]
    method_families: Annotated[list[NonEmptyStr], Field(min_length=1)]
    server_scope_options: list[list[NonEmptyStr]] = Field(default_factory=list)


class ParameterCandidate(_Base):
    candidate_id: NonEmptyStr
    design: AdvisorDesign
    power_analysis: PowerAnalysis
    assumption_ledger: AssumptionLedger
    issues: list[StatisticalIssue] = Field(default_factory=list)
    score: float
    status: Status
    rejection_reasons: list[str] = Field(default_factory=list)
    repair_actions: list[str] = Field(default_factory=list)


class EngineComputationTrace(_Base):
    engine_version: NonEmptyStr
    guide_version: Literal["statistical_guide.v1"]
    guide_snapshot_id: str | None
    random_seed: int | None
    candidate_count: Annotated[int, Field(ge=1)]
    formula_versions: Annotated[list[NonEmptyStr], Field(min_length=1)]
    empirical_prior_sources: list[str] = Field(default_factory=list)
    validator_rule_ids: list[str] = Field(default_factory=list)
    selected_reason: NonEmptyStr


class EngineDecision(_Base):
    schema_version: Literal["benchmark_advisor.engine_decision.v2"]
    recommended_candidate_id: NonEmptyStr
    recommended_design: AdvisorDesign
    parameter_search_space: ParameterSearchSpace
    parameter_candidates: Annotated[list[ParameterCandidate], Field(min_length=1)]
    design_alternatives: list[DesignAlternative] = Field(default_factory=list)
    power_analysis: PowerAnalysis
    assumption_ledger: AssumptionLedger
    claim_card: ClaimCard
    issues: list[StatisticalIssue] = Field(default_factory=list)
    citations: list[LocalStatisticalCitation] = Field(default_factory=list)
    computation_trace: EngineComputationTrace


class StatisticalPlan(_Base):
    schema_version: Literal["benchmark_advisor.statistical_plan.v2"]
    design: AdvisorDesign
    engine_decision: EngineDecision | None = None
    power_analysis: PowerAnalysis
    design_alternatives: list[DesignAlternative] = Field(default_factory=list)
    assumption_ledger: AssumptionLedger
    issues: list[StatisticalIssue] = Field(default_factory=list)
    citations: list[LocalStatisticalCitation] = Field(default_factory=list)
    claim_card: ClaimCard


class AdvisorV2DesignRequest(_Base):
    schema_version: Literal["benchmark_advisor.v2"]
    intent: NonEmptyStr
    mode: Mode
    task_budget: Annotated[int, Field(ge=1)]
    attempts_per_task: Annotated[int, Field(ge=1)]
    candidate_models: list[NonEmptyStr] = Field(default_factory=list)
    target_detectable_effect_pp: PercentPoints | None = None
    alpha: UnitOpen = 0.05
    beta: UnitOpen = 0.2
    deployment_context: DeploymentContext | None = None
    server_scope: list[NonEmptyStr] = Field(default_factory=list)
    user_overrides: dict[str, Any] = Field(default_factory=dict)
    retrieval_mode: Literal["local_only"] = "local_only"


class AdvisorV2DesignResponse(_Base):
    schema_version: Literal["benchmark_advisor.v2"]
    status: Status
    statistical_plan: StatisticalPlan | None
    issues: list[StatisticalIssue] = Field(default_factory=list)
    export_config: ExportConfig | None
    launchable: bool


class AdvisorV2ValidationRequest(_Base):
    schema_version: Literal["benchmark_advisor.v2"]
    statistical_plan: StatisticalPlan
    original_request: AdvisorV2DesignRequest | None = None
    edited_fields: list[str] = Field(default_factory=list)


class AdvisorV2ValidationResponse(AdvisorV2DesignResponse):
    pass


class AxisMetadata(_Base):
    axis_id: NonEmptyStr
    label: NonEmptyStr
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutcomeValue(_Base):
    task_id: NonEmptyStr
    model_id: NonEmptyStr
    attempt_id: NonEmptyStr
    metric_id: NonEmptyStr
    slice_id: NonEmptyStr
    value: float | bool | str | None
    missing_reason: str | None

    @model_validator(mode="after")
    def missing_values_need_reason(self) -> OutcomeValue:
        if self.value is None and not self.missing_reason:
            raise ValueError("missing outcome values require missing_reason")
        if self.value is not None and self.missing_reason is not None:
            raise ValueError("present outcome values must not carry missing_reason")
        return self


class OutcomeTensor(_Base):
    schema_version: Literal["benchmark_advisor.outcome_tensor.v2"]
    shape: Literal["X[task, model, attempt, metric, slice]"]
    tasks: Annotated[list[AxisMetadata], Field(min_length=1)]
    models: Annotated[list[AxisMetadata], Field(min_length=1)]
    attempts: Annotated[list[AxisMetadata], Field(min_length=1)]
    metrics: Annotated[list[AxisMetadata], Field(min_length=1)]
    slices: Annotated[list[AxisMetadata], Field(min_length=1)]
    values: list[OutcomeValue]


class EffectSizeRecord(_Base):
    label: NonEmptyStr
    estimate_pp: float
    method: NonEmptyStr


class ConfidenceIntervalRecord(_Base):
    label: NonEmptyStr
    low_pp: float
    high_pp: float
    method: NonEmptyStr


class RankStabilityResult(_Base):
    method: NonEmptyStr
    stable_top_k: Annotated[int, Field(ge=1)]
    bootstrap_replicates: Annotated[int, Field(ge=1)]
    summary: NonEmptyStr


class SliceDiagnosticResult(_Base):
    slice_id: NonEmptyStr
    label: NonEmptyStr
    metric: NonEmptyStr
    estimate: float
    interpretation: NonEmptyStr


class MissingnessSummary(_Base):
    missing_count: Annotated[int, Field(ge=0)]
    total_count: Annotated[int, Field(ge=0)]
    policy: NonEmptyStr
    reasons: dict[str, int] = Field(default_factory=dict)


class MultiplicitySummary(_Base):
    policy: NonEmptyStr
    confirmatory_tests: Annotated[int, Field(ge=0)]
    exploratory_tests: Annotated[int, Field(ge=0)]
    note: NonEmptyStr


class StatisticalReport(_Base):
    schema_version: Literal["benchmark_advisor.report.v2"]
    mode: Mode
    status: Status
    effect_sizes: list[EffectSizeRecord] = Field(default_factory=list)
    confidence_intervals: list[ConfidenceIntervalRecord] = Field(default_factory=list)
    rank_stability: RankStabilityResult | None
    slice_diagnostics: list[SliceDiagnosticResult] = Field(default_factory=list)
    missingness: MissingnessSummary
    multiplicity: MultiplicitySummary
    allowed_claims: Annotated[list[NonEmptyStr], Field(min_length=1)]
    not_allowed_claims: list[str] = Field(default_factory=list)
    issues: list[StatisticalIssue] = Field(default_factory=list)


class AdvisorV2ReportRequest(_Base):
    schema_version: Literal["benchmark_advisor.v2"]
    outcome_tensor: OutcomeTensor
    statistical_plan: StatisticalPlan | None = None


class AdvisorV2ReportResponse(_Base):
    schema_version: Literal["benchmark_advisor.v2"]
    report: StatisticalReport


class LaunchRequest(_Base):
    schema_version: Literal["benchmark_advisor.launch.v2"]
    export_config: ExportConfig
    advisor_status: Literal["approved", "warning"]
    confirmation: Literal[True]
    sandbox_confirmed: bool = False
    dry_run: bool
    requested_by_ui: bool
    execution_server_ids: list[NonEmptyStr] = Field(default_factory=list)
    run_benchmark: bool = False


class LaunchArtifacts(_Base):
    goals: str | None = None
    specs: str | None = None
    traces: str | None = None
    coverage: str | None = None
    combined_specs: str | None = None
    combined_traces: str | None = None
    evals: dict[str, str] = Field(default_factory=dict)
    candidate_traces: dict[str, str] = Field(default_factory=dict)
    statistical_summary: str | None = None
    replay_demo_report: str | None = None


class LaunchJob(_Base):
    schema_version: Literal["benchmark_advisor.launch_job.v2"]
    job_id: NonEmptyStr
    status: LaunchStatus
    phase: LaunchPhase = "queued"
    progress: dict[str, int | float | str] = Field(default_factory=dict)
    command_preview: Annotated[list[NonEmptyStr], Field(min_length=1)]
    logs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: LaunchArtifacts
