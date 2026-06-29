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

// ---- Benchmark Advisor (Stage 0) ----
export const DStatusSchema = z.enum(["approved", "warning", "refused", "needs_clarification"]);

export const DWarningSchema = z.object({
  severity: z.string(),
  code: z.string(),
  message: z.string(),
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
  status: DStatusSchema,
  warnings: z.array(DWarningSchema),
  refusal: DRefusalSchema.nullable(),
  clarification: DClarSchema.nullable(),
  evidence_ledger: z.array(DEvidenceSchema),
  export_config: z.unknown().nullable(),
  design: z.unknown().nullable(),
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
export type DStatus = z.infer<typeof DStatusSchema>;
export type DWarning = z.infer<typeof DWarningSchema>;
export type DRefusal = z.infer<typeof DRefusalSchema>;
export type DClar = z.infer<typeof DClarSchema>;
export type DEvidence = z.infer<typeof DEvidenceSchema>;
export type DResponse = z.infer<typeof DResponseSchema>;

// Local (non-wire) unions.
export type Mode = "replay" | "live";
export type ScoreMode = "effect" | "answer";
