// Runtime-validated API contract. These zod schemas mirror backend/models.py
// and the benchmark_advisor schema; the TypeScript types are inferred from them
// (single source of truth), and responses are parsed at the network boundary.
import { z } from "zod";

export const ServerCardSchema = z.object({
  server_id: z.string(),
  dynamism: z.string(),
  sandbox: z.boolean(),
  description: z.string(),
  tools: z.array(z.string()),
});

export const GoalOutSchema = z.object({
  goal: z.string(),
  persona: z.string().nullable(),
  fellback: z.string().optional(),
});

export const ExploreCallSchema = z.object({
  idx: z.number(),
  server_id: z.string(),
  tool_name: z.string(),
  arguments: z.record(z.unknown()),
  ok: z.boolean(),
});

export const ExploreDoneSchema = z.object({
  trace_id: z.string(),
  n_calls: z.number(),
  success: z.boolean(),
});

export const CheckpointVerdictSchema = z.object({
  n: z.number(),
  checkpoint_id: z.string(),
  kind: z.string(),
  met: z.boolean(),
  reason: z.string(),
});

export const ScoreDoneSchema = z.object({
  effect_pass: z.boolean(),
  answer_pass: z.boolean(),
  final_answer: z.string(),
  met_count: z.number(),
  required: z.number(),
  checkpoints: z.array(CheckpointVerdictSchema),
});

export const ToolRefSchema = z.object({
  server_id: z.string(),
  tool_name: z.string(),
});

export const CheckpointSchema = z.object({
  kind: z.string(),
  checkpoint_id: z.string(),
  description: z.string(),
  equivalence_set: z.array(ToolRefSchema).optional(),
});

export const TaskSpecViewSchema = z.object({
  checkpoints: z.array(CheckpointSchema),
  minefields: z.array(z.unknown()),
});

export const DistillOutSchema = z.object({
  task_spec: TaskSpecViewSchema,
  equivalence_sets: z.record(z.array(z.string())),
});

export const CandidateCardSchema = z.object({
  name: z.string(),
  note: z.string(),
});

export const LeaderboardRowSchema = z.object({
  model: z.string(),
  group: z.string(),
  pass3: z.number(),
});

export const LeaderboardSchema = z.object({
  placeholder: z.boolean(),
  note: z.string().nullable(),
  rows: z.array(LeaderboardRowSchema),
});

export const HealthSchema = z.object({
  status: z.string(),
  mode_default: z.string(),
  capabilities: z
    .object({
      advisor_v2: z.boolean().optional(),
      advisor_v2_report: z.boolean().optional(),
      advisor_v2_launch: z.boolean().optional(),
      advisor_v2_replay_demo_report: z.boolean().optional(),
    })
    .optional(),
});

// ---- Benchmark Advisor (Stage 0) ----
export const AdvisorModeSchema = z.enum(["pairwise", "leaderboard", "regression", "diagnostic"]);
export const DStatusSchema = z.enum(["approved", "warning", "refused", "needs_clarification"]);
export const SeveritySchema = z.enum(["info", "warning", "critical"]);

export const ClaimScopeSchema = z.enum([
  "confirmatory_model_selection",
  "leaderboard_ranking",
  "regression_non_inferiority",
  "diagnostic_slice",
  "smoke_test_only",
]);

export const PrimaryMetricSchema = z.enum([
  "trace_effect_pass_rate",
  "pass_at_3",
  "pairwise_delta_pp",
  "non_inferiority_margin_pp",
  "rank_stability",
  "slice_failure_rate",
]);

export const TestFamilySchema = z.enum([
  "paired_bootstrap",
  "two_proportion_wilson",
  "non_inferiority_margin",
  "rank_stability_bootstrap",
  "diagnostic_descriptive",
]);

export const CIMethodSchema = z.enum(["wilson_score", "paired_bootstrap", "stratified_bootstrap"]);
export const MDEMethodSchema = z.enum([
  "normal_approx_two_proportion",
  "paired_bootstrap_heuristic",
]);
export const RankStabilityMethodSchema = z.enum([
  "bootstrap_tasks_within_strata",
  "not_applicable",
]);

export const RationaleRoleSchema = z.enum([
  "intent_mapping",
  "metric_choice",
  "criterion_choice",
  "distribution_choice",
  "budget_power",
  "claim_boundary",
  "ui_explanation",
]);

export const GoalStrategySchema = z.enum([
  "deployment_slice",
  "leaderboard_mix",
  "regression_replay",
  "diagnostic_slice",
]);

const RatioSchema = z.number().min(0).max(1);
const PercentPointsSchema = z.number().gt(0).max(100);
const UnitOpenSchema = z.number().gt(0).lt(1);

export const StatisticalGuideReferenceSchema = z.object({
  guide_version: z.literal("statistical_guide.v1"),
  rule_id: z.string().min(1),
  section: z.string().min(1),
  role: RationaleRoleSchema,
});

export const HypothesisPlanSchema = z.object({
  null: z.string().min(1),
  alternative: z.string().min(1),
  non_inferiority_margin_pp: PercentPointsSchema.nullable(),
});

export const DistractorPolicySchema = z.object({
  same_name_fraction: RatioSchema,
  near_miss_fraction: RatioSchema,
  cross_domain_fraction: RatioSchema,
  random_fraction: RatioSchema,
});

export const DiagnosticSliceSchema = z.object({
  slice_id: z.string().min(1),
  label: z.string().min(1),
  ratio: RatioSchema,
  confirmatory: z.boolean(),
});

export const TaskDistributionSchema = z.object({
  short_chain: RatioSchema,
  medium_chain: RatioSchema,
  long_chain: RatioSchema,
  cross_server_ratio: RatioSchema,
  recovery_required_ratio: RatioSchema,
  prerequisite_strict_ratio: RatioSchema,
  stateful_write_ratio: RatioSchema,
  categories: z.array(z.string().min(1)).min(1),
  distractors: DistractorPolicySchema,
  diagnostic_slices: z.array(DiagnosticSliceSchema),
});

export const AnalysisPlanSchema = z.object({
  ci_method: CIMethodSchema,
  mde_method: MDEMethodSchema,
  rank_stability_method: RankStabilityMethodSchema,
  pairwise_test: TestFamilySchema.nullable(),
  alpha: UnitOpenSchema,
  beta: UnitOpenSchema,
  planning_assumptions: z.array(z.string().min(1)).min(1),
  heuristic_label: z.literal("planning_heuristic"),
});

export const CriterionSchema = z.object({
  criterion_id: z.string().min(1),
  purpose: z.string().min(1),
  estimand: z.string().min(1),
  null_hypothesis: z.string().min(1),
  alternative_hypothesis: z.string().min(1),
  primary_metric: PrimaryMetricSchema,
  test_family: TestFamilySchema,
  alpha: UnitOpenSchema,
  beta_or_target_power: UnitOpenSchema,
  minimum_detectable_effect_pp: PercentPointsSchema.nullable(),
  required_data: z.array(z.string().min(1)),
  decision_rule: z.string().min(1),
  allowed_claim: z.string().min(1),
  failure_modes: z.array(z.string().min(1)),
  confirmatory: z.boolean(),
  guide_references: z.array(StatisticalGuideReferenceSchema).min(1),
  selection_rationale: z.string().min(1),
});

export const WarningCardSchema = z.object({
  severity: SeveritySchema,
  code: z.string().min(1),
  message: z.string().min(1),
  failed_criterion_id: z.string().nullable().optional(),
  statistical_reason: z.string().nullable(),
  repair_suggestion: z.string().min(1),
});

export const AdvisorDesignSchema = z.object({
  evaluation_question: z.string().min(1),
  mode: AdvisorModeSchema,
  claim_scope: ClaimScopeSchema,
  candidate_models: z.array(z.string().min(1)),
  task_budget: z.number().int().min(1),
  attempts_per_task: z.number().int().min(1),
  target_detectable_effect_pp: PercentPointsSchema.nullable(),
  estimand: z.string().min(1),
  hypotheses: HypothesisPlanSchema,
  criteria: z.array(CriterionSchema).min(1),
  task_distribution: TaskDistributionSchema,
  analysis_plan: AnalysisPlanSchema,
  claim_boundary: z.string().min(1),
  intent_evidence: z.array(z.string().min(1)),
  statistical_guide_version: z.literal("statistical_guide.v1"),
});

export const ExportGenerationKnobsSchema = z.object({
  handoff_target: z.literal("scripts/build_corpus.py"),
  dry_run_only: z.literal(true),
  goal_strategy: GoalStrategySchema,
  max_tool_calls_per_task: z.number().int().min(1),
  server_scope: z.array(z.string().min(1)),
  sandbox_required: z.boolean(),
  generation_notes: z.array(z.string()),
});

export const ExportConfigSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v1"),
  mode: AdvisorModeSchema,
  candidate_models: z.array(z.string().min(1)),
  evaluation_question: z.string().min(1),
  estimand: z.string().min(1),
  hypotheses: HypothesisPlanSchema,
  criteria: z.array(CriterionSchema).min(1),
  tasks: z.number().int().min(1),
  attempts_per_task: z.number().int().min(1),
  task_distribution: TaskDistributionSchema,
  distractors: DistractorPolicySchema,
  analysis_plan: AnalysisPlanSchema,
  warnings: z.array(WarningCardSchema),
  claim_boundary: z.string().min(1),
  generation_knobs: ExportGenerationKnobsSchema,
});

export const DWarningSchema = z.object({
  severity: SeveritySchema,
  code: z.string(),
  message: z.string(),
  failed_criterion_id: z.string().nullable().optional(),
  statistical_reason: z.string().nullable(),
  repair_suggestion: z.string(),
});

export const DRefusalSchema = z.object({
  code: z.string(),
  reason: z.string(),
  statistical_reason: z.string(),
  repair_options: z.array(z.string()),
});

export const DClarSchema = z.object({
  missing_fields: z.array(z.string()),
  questions: z.array(z.string()),
  why_needed: z.string(),
});

export const DEvidenceSchema = z.object({
  parameter: z.string(),
  value: z.unknown(),
  intent_evidence: z.string().nullable(),
  statistical_rationale: z.string(),
  guide_references: z.array(z.object({ rule_id: z.string() })),
  hover_text: z.string(),
});

export const DResponseSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v1").optional(),
  status: DStatusSchema,
  warnings: z.array(DWarningSchema),
  refusal: DRefusalSchema.nullable(),
  clarification: DClarSchema.nullable(),
  evidence_ledger: z.array(DEvidenceSchema),
  export_config: ExportConfigSchema.nullable(),
  design: AdvisorDesignSchema.nullable(),
});

export const LocalStatisticalCitationSchema = z.object({
  source_id: z.string().min(1),
  title: z.string().min(1),
  section: z.string().min(1),
  evidence_status: z.string().min(1),
  source_keys: z.array(z.string().min(1)),
  snippet: z.string().min(1),
  guide_references: z.array(StatisticalGuideReferenceSchema),
});

export const StatisticalIssueSchema = z.object({
  severity: SeveritySchema,
  code: z.string().min(1),
  message: z.string().min(1),
  failed_field: z.string().nullable(),
  failed_criterion_id: z.string().nullable(),
  statistical_reason: z.string().min(1),
  repair_options: z.array(z.string().min(1)).min(1),
  guide_references: z.array(StatisticalGuideReferenceSchema),
});

export const AssumptionLedgerSchema = z.object({
  baseline_rate: RatioSchema.nullable(),
  paired_design: z.boolean(),
  independence_assumption: z.string().min(1),
  repeated_attempts_policy: z.string().min(1),
  missingness_policy: z.string().min(1),
  multiplicity_policy: z.string().min(1),
  sensitivity_notes: z.array(z.string()),
  guide_references: z.array(StatisticalGuideReferenceSchema),
});

export const PowerCurvePointSchema = z.object({
  task_budget: z.number().int().min(1),
  mde_pp: PercentPointsSchema,
  ci_width_pp: PercentPointsSchema,
});

export const BudgetAlternativeSchema = z.object({
  task_budget: z.number().int().min(1),
  detectable_effect_pp: PercentPointsSchema,
  claim_status: DStatusSchema,
});

export const PlanningDiagnosticSchema = z.object({
  diagnostic_id: z.string().min(1),
  label: z.string().min(1),
  value: z.union([z.number(), z.string()]),
  unit: z.string().nullable(),
  status: DStatusSchema.nullable(),
  interpretation: z.string().min(1),
  guide_references: z.array(StatisticalGuideReferenceSchema),
});

export const PowerAnalysisSchema = z.object({
  alpha: UnitOpenSchema,
  target_power: UnitOpenSchema,
  planned_mde_pp: PercentPointsSchema,
  ci_width_pp: PercentPointsSchema,
  method: z.string().min(1),
  power_curve: z.array(PowerCurvePointSchema),
  budget_alternatives: z.array(BudgetAlternativeSchema),
  planning_diagnostics: z.array(PlanningDiagnosticSchema),
  assumptions: AssumptionLedgerSchema,
});

export const DesignAlternativeSchema = z.object({
  alternative_id: z.string().min(1),
  label: z.string().min(1),
  task_budget: z.number().int().min(1),
  attempts_per_task: z.number().int().min(1),
  target_detectable_effect_pp: PercentPointsSchema.nullable(),
  status: DStatusSchema,
  tradeoff: z.string().min(1),
  repair_actions: z.array(z.string()),
});

export const ClaimCardSchema = z.object({
  allowed_claims: z.array(z.string().min(1)).min(1),
  not_allowed_claims: z.array(z.string()),
  plain_language_summary: z.string().min(1),
});

export const ParameterSearchSpaceSchema = z.object({
  task_budget_grid: z.array(z.number().int().min(1)).min(1),
  attempts_grid: z.array(z.number().int().min(1)).min(1),
  effect_target_grid_pp: z.array(PercentPointsSchema).min(1),
  distribution_candidates: z.array(TaskDistributionSchema).min(1),
  confirmatory_slice_limit: z.number().int().min(1),
  method_families: z.array(z.string().min(1)).min(1),
  server_scope_options: z.array(z.array(z.string().min(1))),
});

export const ParameterCandidateSchema = z.object({
  candidate_id: z.string().min(1),
  design: AdvisorDesignSchema,
  power_analysis: PowerAnalysisSchema,
  assumption_ledger: AssumptionLedgerSchema,
  issues: z.array(StatisticalIssueSchema),
  score: z.number(),
  status: DStatusSchema,
  rejection_reasons: z.array(z.string()),
  repair_actions: z.array(z.string()),
});

export const EngineComputationTraceSchema = z.object({
  engine_version: z.string().min(1),
  guide_version: z.literal("statistical_guide.v1"),
  guide_snapshot_id: z.string().nullable(),
  random_seed: z.number().int().nullable(),
  candidate_count: z.number().int().min(1),
  formula_versions: z.array(z.string().min(1)).min(1),
  empirical_prior_sources: z.array(z.string()),
  validator_rule_ids: z.array(z.string()),
  selected_reason: z.string().min(1),
});

export const EngineDecisionSchema = z.object({
  schema_version: z.literal("benchmark_advisor.engine_decision.v2"),
  recommended_candidate_id: z.string().min(1),
  recommended_design: AdvisorDesignSchema,
  parameter_search_space: ParameterSearchSpaceSchema,
  parameter_candidates: z.array(ParameterCandidateSchema).min(1),
  design_alternatives: z.array(DesignAlternativeSchema),
  power_analysis: PowerAnalysisSchema,
  assumption_ledger: AssumptionLedgerSchema,
  claim_card: ClaimCardSchema,
  issues: z.array(StatisticalIssueSchema),
  citations: z.array(LocalStatisticalCitationSchema),
  computation_trace: EngineComputationTraceSchema,
});

export const StatisticalPlanSchema = z.object({
  schema_version: z.literal("benchmark_advisor.statistical_plan.v2"),
  design: AdvisorDesignSchema,
  engine_decision: EngineDecisionSchema.nullable().optional(),
  power_analysis: PowerAnalysisSchema,
  design_alternatives: z.array(DesignAlternativeSchema),
  assumption_ledger: AssumptionLedgerSchema,
  issues: z.array(StatisticalIssueSchema),
  citations: z.array(LocalStatisticalCitationSchema),
  claim_card: ClaimCardSchema,
});

export const DeploymentContextSchema = z.object({
  notes: z.string().nullable().optional(),
  private_server_constraints: z.array(z.string()).optional(),
  unavailable_servers: z.array(z.string()).optional(),
});

export const AdvisorV2DesignRequestSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v2"),
  intent: z.string().min(1),
  mode: AdvisorModeSchema,
  task_budget: z.number().int().min(1),
  attempts_per_task: z.number().int().min(1),
  candidate_models: z.array(z.string().min(1)),
  target_detectable_effect_pp: PercentPointsSchema.nullable(),
  alpha: UnitOpenSchema,
  beta: UnitOpenSchema,
  deployment_context: DeploymentContextSchema.nullable(),
  server_scope: z.array(z.string().min(1)),
  user_overrides: z.record(z.unknown()),
  retrieval_mode: z.literal("local_only"),
});

export const AdvisorV2DesignResponseSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v2"),
  status: DStatusSchema,
  statistical_plan: StatisticalPlanSchema.nullable(),
  issues: z.array(StatisticalIssueSchema),
  export_config: ExportConfigSchema.nullable(),
  launchable: z.boolean(),
});

export const AdvisorV2ValidationRequestSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v2"),
  statistical_plan: StatisticalPlanSchema,
  original_request: AdvisorV2DesignRequestSchema.nullable(),
  edited_fields: z.array(z.string()),
});

export const AdvisorV2ValidationResponseSchema = AdvisorV2DesignResponseSchema;

export const AxisMetadataSchema = z.object({
  axis_id: z.string().min(1),
  label: z.string().min(1),
  metadata: z.record(z.unknown()),
});

export const OutcomeValueSchema = z.object({
  task_id: z.string().min(1),
  model_id: z.string().min(1),
  attempt_id: z.string().min(1),
  metric_id: z.string().min(1),
  slice_id: z.string().min(1),
  value: z.union([z.number(), z.boolean(), z.string()]).nullable(),
  missing_reason: z.string().nullable(),
});

export const OutcomeTensorSchema = z.object({
  schema_version: z.literal("benchmark_advisor.outcome_tensor.v2"),
  shape: z.literal("X[task, model, attempt, metric, slice]"),
  tasks: z.array(AxisMetadataSchema).min(1),
  models: z.array(AxisMetadataSchema).min(1),
  attempts: z.array(AxisMetadataSchema).min(1),
  metrics: z.array(AxisMetadataSchema).min(1),
  slices: z.array(AxisMetadataSchema).min(1),
  values: z.array(OutcomeValueSchema),
});

export const EffectSizeRecordSchema = z.object({
  label: z.string().min(1),
  estimate_pp: z.number(),
  method: z.string().min(1),
});

export const ConfidenceIntervalRecordSchema = z.object({
  label: z.string().min(1),
  low_pp: z.number(),
  high_pp: z.number(),
  method: z.string().min(1),
});

export const RankStabilityResultSchema = z.object({
  method: z.string().min(1),
  stable_top_k: z.number().int().min(1),
  bootstrap_replicates: z.number().int().min(1),
  summary: z.string().min(1),
});

export const SliceDiagnosticResultSchema = z.object({
  slice_id: z.string().min(1),
  label: z.string().min(1),
  metric: z.string().min(1),
  estimate: z.number(),
  interpretation: z.string().min(1),
});

export const MissingnessSummarySchema = z.object({
  missing_count: z.number().int().min(0),
  total_count: z.number().int().min(0),
  policy: z.string().min(1),
  reasons: z.record(z.number().int().min(0)),
});

export const MultiplicitySummarySchema = z.object({
  policy: z.string().min(1),
  confirmatory_tests: z.number().int().min(0),
  exploratory_tests: z.number().int().min(0),
  note: z.string().min(1),
});

export const StatisticalReportSchema = z.object({
  schema_version: z.literal("benchmark_advisor.report.v2"),
  mode: AdvisorModeSchema,
  status: DStatusSchema,
  effect_sizes: z.array(EffectSizeRecordSchema),
  confidence_intervals: z.array(ConfidenceIntervalRecordSchema),
  rank_stability: RankStabilityResultSchema.nullable(),
  slice_diagnostics: z.array(SliceDiagnosticResultSchema),
  missingness: MissingnessSummarySchema,
  multiplicity: MultiplicitySummarySchema,
  allowed_claims: z.array(z.string().min(1)).min(1),
  not_allowed_claims: z.array(z.string()),
  issues: z.array(StatisticalIssueSchema),
});

export const AdvisorV2ReportRequestSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v2"),
  outcome_tensor: OutcomeTensorSchema,
  statistical_plan: StatisticalPlanSchema.nullable(),
});

export const AdvisorV2ReportResponseSchema = z.object({
  schema_version: z.literal("benchmark_advisor.v2"),
  report: StatisticalReportSchema,
});

export const ReplayDemoLeaderboardRowSchema = z.object({
  rank: z.number().int().min(1),
  model: z.string().min(1),
  passed: z.number().int().min(0),
  n: z.number().int().min(1),
  acc: z.number(),
  lo: z.number(),
  hi: z.number(),
  old_acc: z.number(),
  delta: z.number(),
});

export const ReplayDemoFigureSchema = z.object({
  figure_id: z.string().min(1),
  title: z.string().min(1),
  url: z.string().min(1),
  alt: z.string().min(1),
});

export const ReplayDemoFocusSliceSchema = z.object({
  slice_id: z.string().min(1),
  label: z.string().min(1),
  model_a_passed: z.number().int().min(0).optional(),
  model_b_passed: z.number().int().min(0).optional(),
  qwen_passed: z.number().int().min(0).optional(),
  glm_passed: z.number().int().min(0).optional(),
  n: z.number().int().min(1),
  delta_pp: z.number(),
});

export const ReplayDemoProvenanceSchema = z.object({
  source_docs: z.array(z.string().min(1)),
  discarded_sources: z.array(z.string().min(1)),
  corpus: z.string().min(1),
  execution: z.string().min(1),
  generated_by_current_handoff: z.boolean(),
  server_filter_available: z.boolean().optional(),
  server_filter_note: z.string().min(1).optional(),
});

export const ReplayDemoReportSchema = z.object({
  schema_version: z.literal("benchmark_advisor.replay_demo_report.v1"),
  experiment_id: z.string().min(1),
  title: z.string().min(1),
  headline: z.string().min(1),
  condition: z.string().min(1),
  sample_size: z.number().int().min(1),
  model_count: z.number().int().min(1),
  metric: z.string().min(1),
  mode: z.literal("replay"),
  report: StatisticalReportSchema,
  leaderboard: z.array(ReplayDemoLeaderboardRowSchema).min(1),
  focus_slices: z.array(ReplayDemoFocusSliceSchema).optional(),
  provenance: ReplayDemoProvenanceSchema,
  data_quality: z.array(z.string().min(1)),
  figures: z.array(ReplayDemoFigureSchema),
});

export const LaunchRequestSchema = z.object({
  schema_version: z.literal("benchmark_advisor.launch.v2"),
  export_config: ExportConfigSchema,
  advisor_status: z.enum(["approved", "warning"]),
  confirmation: z.literal(true),
  sandbox_confirmed: z.boolean(),
  dry_run: z.boolean(),
  requested_by_ui: z.boolean(),
});

export const LaunchArtifactsSchema = z.object({
  goals: z.string().nullable(),
  specs: z.string().nullable(),
  traces: z.string().nullable(),
  coverage: z.string().nullable(),
});

export const LaunchJobSchema = z.object({
  schema_version: z.literal("benchmark_advisor.launch_job.v2"),
  job_id: z.string().min(1),
  status: z.enum(["queued", "running", "succeeded", "failed", "cancelled"]),
  command_preview: z.array(z.string().min(1)).min(1),
  logs: z.array(z.string()),
  artifacts: LaunchArtifactsSchema,
});

export const ServerListSchema = z.array(ServerCardSchema);
export const CandidateListSchema = z.array(CandidateCardSchema);

export type ServerCard = z.infer<typeof ServerCardSchema>;
export type GoalOut = z.infer<typeof GoalOutSchema>;
export type ExploreCall = z.infer<typeof ExploreCallSchema>;
export type ExploreDone = z.infer<typeof ExploreDoneSchema>;
export type CheckpointVerdict = z.infer<typeof CheckpointVerdictSchema>;
export type ScoreDone = z.infer<typeof ScoreDoneSchema>;
export type ToolRef = z.infer<typeof ToolRefSchema>;
export type Checkpoint = z.infer<typeof CheckpointSchema>;
export type TaskSpecView = z.infer<typeof TaskSpecViewSchema>;
export type DistillOut = z.infer<typeof DistillOutSchema>;
export type CandidateCard = z.infer<typeof CandidateCardSchema>;
export type LeaderboardRow = z.infer<typeof LeaderboardRowSchema>;
export type Leaderboard = z.infer<typeof LeaderboardSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type AdvisorMode = z.infer<typeof AdvisorModeSchema>;
export type DStatus = z.infer<typeof DStatusSchema>;
export type DWarning = z.infer<typeof DWarningSchema>;
export type DRefusal = z.infer<typeof DRefusalSchema>;
export type DClar = z.infer<typeof DClarSchema>;
export type DEvidence = z.infer<typeof DEvidenceSchema>;
export type DResponse = z.infer<typeof DResponseSchema>;
export type StatisticalGuideReference = z.infer<typeof StatisticalGuideReferenceSchema>;
export type HypothesisPlan = z.infer<typeof HypothesisPlanSchema>;
export type DistractorPolicy = z.infer<typeof DistractorPolicySchema>;
export type DiagnosticSlice = z.infer<typeof DiagnosticSliceSchema>;
export type TaskDistribution = z.infer<typeof TaskDistributionSchema>;
export type AnalysisPlan = z.infer<typeof AnalysisPlanSchema>;
export type Criterion = z.infer<typeof CriterionSchema>;
export type AdvisorDesign = z.infer<typeof AdvisorDesignSchema>;
export type ExportConfig = z.infer<typeof ExportConfigSchema>;
export type LocalStatisticalCitation = z.infer<typeof LocalStatisticalCitationSchema>;
export type StatisticalIssue = z.infer<typeof StatisticalIssueSchema>;
export type AssumptionLedger = z.infer<typeof AssumptionLedgerSchema>;
export type PowerCurvePoint = z.infer<typeof PowerCurvePointSchema>;
export type BudgetAlternative = z.infer<typeof BudgetAlternativeSchema>;
export type PlanningDiagnostic = z.infer<typeof PlanningDiagnosticSchema>;
export type PowerAnalysis = z.infer<typeof PowerAnalysisSchema>;
export type DesignAlternative = z.infer<typeof DesignAlternativeSchema>;
export type ClaimCard = z.infer<typeof ClaimCardSchema>;
export type ParameterSearchSpace = z.infer<typeof ParameterSearchSpaceSchema>;
export type ParameterCandidate = z.infer<typeof ParameterCandidateSchema>;
export type EngineComputationTrace = z.infer<typeof EngineComputationTraceSchema>;
export type EngineDecision = z.infer<typeof EngineDecisionSchema>;
export type StatisticalPlan = z.infer<typeof StatisticalPlanSchema>;
export type AdvisorV2DesignRequest = z.infer<typeof AdvisorV2DesignRequestSchema>;
export type AdvisorV2DesignResponse = z.infer<typeof AdvisorV2DesignResponseSchema>;
export type AdvisorV2ValidationRequest = z.infer<typeof AdvisorV2ValidationRequestSchema>;
export type AdvisorV2ValidationResponse = z.infer<typeof AdvisorV2ValidationResponseSchema>;
export type AxisMetadata = z.infer<typeof AxisMetadataSchema>;
export type OutcomeValue = z.infer<typeof OutcomeValueSchema>;
export type OutcomeTensor = z.infer<typeof OutcomeTensorSchema>;
export type EffectSizeRecord = z.infer<typeof EffectSizeRecordSchema>;
export type ConfidenceIntervalRecord = z.infer<typeof ConfidenceIntervalRecordSchema>;
export type RankStabilityResult = z.infer<typeof RankStabilityResultSchema>;
export type SliceDiagnosticResult = z.infer<typeof SliceDiagnosticResultSchema>;
export type MissingnessSummary = z.infer<typeof MissingnessSummarySchema>;
export type MultiplicitySummary = z.infer<typeof MultiplicitySummarySchema>;
export type StatisticalReport = z.infer<typeof StatisticalReportSchema>;
export type AdvisorV2ReportRequest = z.infer<typeof AdvisorV2ReportRequestSchema>;
export type AdvisorV2ReportResponse = z.infer<typeof AdvisorV2ReportResponseSchema>;
export type ReplayDemoReport = z.infer<typeof ReplayDemoReportSchema>;
export type LaunchRequest = z.infer<typeof LaunchRequestSchema>;
export type LaunchArtifacts = z.infer<typeof LaunchArtifactsSchema>;
export type LaunchJob = z.infer<typeof LaunchJobSchema>;

// Local (non-wire) unions.
export type Mode = "replay" | "live";
export type ScoreMode = "effect" | "answer";
