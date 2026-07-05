import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DResponseSchema } from "../api/schemas";
import { StudioContext, type Studio } from "../store/context";
import { initialState } from "../store/reducer";
import { Design } from "./Design";
import type {
  AdvisorDesign,
  AdvisorV2DesignResponse,
  AnalysisPlan,
  AssumptionLedger,
  Criterion,
  ExportConfig,
  PowerAnalysis,
  StatisticalIssue,
  StatisticalGuideReference,
  StatisticalPlan,
  StatisticalReport,
  TaskDistribution,
} from "../types";

const guideRef: StatisticalGuideReference = {
  guide_version: "statistical_guide.v1",
  rule_id: "G4.budget.mode_thresholds",
  section: "G4 - Budget, Power, And Repeats",
  role: "budget_power",
};

const distribution: TaskDistribution = {
  short_chain: 0.25,
  medium_chain: 0.45,
  long_chain: 0.3,
  cross_server_ratio: 0.35,
  recovery_required_ratio: 0.1,
  prerequisite_strict_ratio: 0.1,
  stateful_write_ratio: 0,
  categories: ["finance", "long_chain"],
  distractors: {
    same_name_fraction: 0.15,
    near_miss_fraction: 0.2,
    cross_domain_fraction: 0.2,
    random_fraction: 0.45,
  },
  diagnostic_slices: [],
};

const analysisPlan: AnalysisPlan = {
  ci_method: "paired_bootstrap",
  mde_method: "paired_bootstrap_heuristic",
  rank_stability_method: "not_applicable",
  pairwise_test: "paired_bootstrap",
  alpha: 0.05,
  beta: 0.2,
  planning_assumptions: ["unique tasks are the planning unit"],
  heuristic_label: "planning_heuristic",
};

const criterion: Criterion = {
  criterion_id: "criterion.primary",
  purpose: "model comparison",
  estimand: "paired task delta",
  null_hypothesis: "no difference",
  alternative_hypothesis: "non-zero difference",
  primary_metric: "trace_effect_pass_rate",
  test_family: "paired_bootstrap",
  alpha: 0.05,
  beta_or_target_power: 0.8,
  minimum_detectable_effect_pp: 18,
  required_data: ["task-level outcomes"],
  decision_rule: "paired bootstrap CI excludes zero",
  allowed_claim: "scoped pairwise difference",
  failure_modes: ["underpowered design"],
  confirmatory: true,
  guide_references: [guideRef],
  selection_rationale: "Pairwise claims use paired task deltas.",
};

function design(overrides: Partial<AdvisorDesign> = {}): AdvisorDesign {
  return {
    evaluation_question: "Compare two local agents on finance workflows.",
    mode: "pairwise",
    claim_scope: "confirmatory_model_selection",
    candidate_models: ["model-a", "model-b"],
    task_budget: 120,
    attempts_per_task: 3,
    target_detectable_effect_pp: 18,
    estimand: "paired task delta",
    hypotheses: {
      null: "model-b equals model-a",
      alternative: "model-b differs from model-a",
      non_inferiority_margin_pp: null,
    },
    criteria: [criterion],
    task_distribution: distribution,
    analysis_plan: analysisPlan,
    claim_boundary: "Only the planned finance task distribution.",
    intent_evidence: ["finance workflows"],
    statistical_guide_version: "statistical_guide.v1",
    ...overrides,
  };
}

const assumptions: AssumptionLedger = {
  baseline_rate: 0.5,
  paired_design: true,
  independence_assumption: "unique tasks are the iid planning unit",
  repeated_attempts_policy: "attempts do not multiply unique-task power",
  missingness_policy: "explicit null with reason",
  multiplicity_policy: "single primary criterion",
  sensitivity_notes: ["Baseline-rate sensitivity branches at task_budget=120."],
  guide_references: [guideRef],
};

const powerAnalysis: PowerAnalysis = {
  alpha: 0.05,
  target_power: 0.8,
  planned_mde_pp: 18,
  ci_width_pp: 16,
  method: "paired_bootstrap_heuristic",
  power_curve: [
    { task_budget: 60, mde_pp: 25, ci_width_pp: 24 },
    { task_budget: 120, mde_pp: 18, ci_width_pp: 16 },
    { task_budget: 180, mde_pp: 14, ci_width_pp: 12 },
  ],
  budget_alternatives: [
    { task_budget: 80, detectable_effect_pp: 22, claim_status: "warning" },
    { task_budget: 160, detectable_effect_pp: 15, claim_status: "approved" },
  ],
  planning_diagnostics: [
    {
      diagnostic_id: "diagnostic.n_eff.unique_tasks",
      label: "Effective sample size caveat",
      value: 120,
      unit: "unique_tasks",
      status: "approved",
      interpretation: "Repeated attempts do not multiply iid N.",
      guide_references: [guideRef],
    },
  ],
  assumptions,
};

const citation = {
  source_id: "statistical_guide.v1.G4",
  title: "Benchmark Advisor statistical guide",
  section: "G4 - Budget, Power, And Repeats",
  evidence_status: "curated",
  source_keys: ["ProjectInterfaces2026"],
  snippet: "Budget and power gates are planning constraints.",
  guide_references: [guideRef],
};

const issue: StatisticalIssue = {
  severity: "critical",
  code: "unsupported_candidate_model_count",
  message: "Pairwise planning requires exactly two candidate models.",
  failed_field: "candidate_models",
  failed_criterion_id: "criterion.primary",
  statistical_reason: "paired task-level comparisons need one A/B candidate pair",
  repair_options: ["Use exactly two candidate models."],
  guide_references: [guideRef],
};

function plan(overrides: Partial<StatisticalPlan> = {}): StatisticalPlan {
  const planDesign = design();
  return {
    schema_version: "benchmark_advisor.statistical_plan.v2",
    design: planDesign,
    power_analysis: powerAnalysis,
    design_alternatives: [
      {
        alternative_id: "alt.recommended",
        label: "Recommended",
        task_budget: 120,
        attempts_per_task: 3,
        target_detectable_effect_pp: 18,
        status: "approved",
        tradeoff: "Cheapest approved candidate under engine scoring.",
        repair_actions: [],
      },
      {
        alternative_id: "alt.stronger",
        label: "Stronger",
        task_budget: 180,
        attempts_per_task: 3,
        target_detectable_effect_pp: 14,
        status: "approved",
        tradeoff: "Higher budget alternative with lower planned MDE.",
        repair_actions: [],
      },
    ],
    assumption_ledger: assumptions,
    issues: [],
    citations: [citation],
    claim_card: {
      allowed_claims: ["Scoped pairwise difference on the planned task distribution."],
      not_allowed_claims: ["universal best-model claim"],
      plain_language_summary: "This pairwise plan is approved for the scoped claim shown here.",
    },
    ...overrides,
  };
}

function exportConfig(planObj = plan()): ExportConfig {
  const planDesign = planObj.design;
  return {
    schema_version: "benchmark_advisor.v1",
    mode: planDesign.mode,
    candidate_models: planDesign.candidate_models,
    evaluation_question: planDesign.evaluation_question,
    estimand: planDesign.estimand,
    hypotheses: planDesign.hypotheses,
    criteria: planDesign.criteria,
    tasks: planDesign.task_budget,
    attempts_per_task: planDesign.attempts_per_task,
    task_distribution: planDesign.task_distribution,
    distractors: planDesign.task_distribution.distractors,
    analysis_plan: planDesign.analysis_plan,
    warnings: [],
    claim_boundary: planDesign.claim_boundary,
    generation_knobs: {
      handoff_target: "scripts/build_corpus.py",
      dry_run_only: true,
      goal_strategy: "deployment_slice",
      max_tool_calls_per_task: 6,
      server_scope: ["finance-tools"],
      sandbox_required: false,
      generation_notes: ["dry-run preview only"],
    },
  };
}

function approvedResponse(): AdvisorV2DesignResponse {
  const planObj = plan();
  return {
    schema_version: "benchmark_advisor.v2",
    status: "approved",
    statistical_plan: planObj,
    issues: [],
    export_config: exportConfig(planObj),
    launchable: true,
  };
}

function refusedResponse(): AdvisorV2DesignResponse {
  return {
    schema_version: "benchmark_advisor.v2",
    status: "refused",
    statistical_plan: null,
    issues: [issue],
    export_config: null,
    launchable: false,
  };
}

function validationResponse(): AdvisorV2DesignResponse {
  const refusedPlan = plan({
    design: design({ candidate_models: ["model-a", "model-b", "model-c"] }),
    issues: [issue],
    claim_card: {
      allowed_claims: ["No confirmatory claim until the critical issues are repaired."],
      not_allowed_claims: ["model selection", "universal model ranking"],
      plain_language_summary: "The current request cannot support the requested statistical claim.",
    },
  });
  return {
    schema_version: "benchmark_advisor.v2",
    status: "refused",
    statistical_plan: refusedPlan,
    issues: [issue],
    export_config: null,
    launchable: false,
  };
}

function report(): StatisticalReport {
  return {
    schema_version: "benchmark_advisor.report.v2",
    mode: "pairwise",
    status: "approved",
    effect_sizes: [{ label: "model-b - model-a", estimate_pp: 25, method: "paired_task_delta" }],
    confidence_intervals: [
      { label: "model-b - model-a", low_pp: 0, high_pp: 50, method: "paired_bootstrap_tasks" },
    ],
    rank_stability: null,
    slice_diagnostics: [
      {
        slice_id: "all",
        label: "all tasks: model-b",
        metric: "trace_effect_pass_rate",
        estimate: 0.75,
        interpretation: "descriptive task-level mean",
      },
    ],
    missingness: {
      missing_count: 0,
      total_count: 8,
      policy: "explicit null with reason",
      reasons: {},
    },
    multiplicity: {
      policy: "single primary criterion",
      confirmatory_tests: 1,
      exploratory_tests: 0,
      note: "One primary confirmatory test.",
    },
    allowed_claims: ["Scoped pairwise difference for model-b - model-a."],
    not_allowed_claims: ["universal best-model claim"],
    issues: [],
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function studioValue(): Studio {
  return {
    ...initialState(),
    go: vi.fn(),
    setMode: vi.fn(),
    loadServers: vi.fn(),
    toggleServer: vi.fn(),
    ensureGoal: vi.fn(),
    runExplore: vi.fn(),
    runDistill: vi.fn(),
    toggleEquiv: vi.fn(),
    loadCandidates: vi.fn(),
    setCandidate: vi.fn(),
    setScoreMode: vi.fn(),
    runCandidate: vi.fn(),
    clearError: vi.fn(),
  };
}

function renderDesign() {
  return render(
    <StudioContext.Provider value={studioValue()}>
      <Design />
    </StudioContext.Provider>,
  );
}

function installFetchMock(initial: AdvisorV2DesignResponse = approvedResponse()) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/health") {
      return jsonResponse({
        status: "ok",
        mode_default: "replay",
        capabilities: { advisor_v2: true, advisor_v2_report: true },
      });
    }
    if (url === "/api/advisor/v2/design") return jsonResponse(initial);
    if (url === "/api/advisor/v2/validate") return jsonResponse(validationResponse());
    if (url === "/api/advisor/v2/report") {
      return jsonResponse({ schema_version: "benchmark_advisor.v2", report: report() });
    }
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Design v2 advisor workbench", () => {
  beforeEach(() => {
    vi.stubGlobal("scrollTo", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders v2 statistical plan fields from typed route responses", async () => {
    installFetchMock();
    renderDesign();

    expect(await screen.findByText("Claim card")).toBeInTheDocument();
    expect(screen.getByText("Power curve")).toBeInTheDocument();
    expect(screen.getAllByText("paired_bootstrap_heuristic").length).toBeGreaterThan(0);
    expect(screen.getByText("statistical_guide.v1.G4")).toBeInTheDocument();
    expect(
      screen.getByText("Scoped pairwise difference on the planned task distribution."),
    ).toBeInTheDocument();
  });

  it("shows readable field help cards on hover", async () => {
    installFetchMock();
    renderDesign();

    await screen.findByText("Claim card");
    fireEvent.pointerEnter(screen.getByText("requested task budget"), {
      clientX: 120,
      clientY: 160,
    });

    expect(
      await screen.findByText(
        "Unique tasks requested by the user. Attempts do not multiply this into independent samples; unique tasks remain the main planning unit.",
      ),
    ).toBeInTheDocument();
  });

  it("detects a stale backend before calling v2 design", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/health") {
        return jsonResponse({ status: "ok", mode_default: "replay" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDesign();

    expect(
      await screen.findByText(
        "Studio backend is stale. Restart Studio so the v2 advisor routes are loaded.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/advisor/v2/design",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls v2 validate after a structured plan edit and renders all returned issues", async () => {
    const fetchMock = installFetchMock();
    renderDesign();
    await screen.findByText("Editable statistical plan");
    await screen.findByText("model-b - model-a: 25.0 pp (paired_task_delta)");
    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText("edit task budget"), { target: { value: "70" } });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/advisor/v2/validate",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText("unsupported_candidate_model_count")).toBeInTheDocument();
    expect(screen.getByText("Use exactly two candidate models.")).toBeInTheDocument();
  });

  it("disables carry-forward controls for refused v2 designs", async () => {
    installFetchMock(refusedResponse());
    renderDesign();

    expect(await screen.findByText("REFUSED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Carry this design into Collect" })).toBeDisabled();
    expect(
      screen.getAllByText("Pairwise planning requires exactly two candidate models.").length,
    ).toBeGreaterThan(0);
  });

  it("renders the typed post-run report fixture", async () => {
    installFetchMock();
    renderDesign();

    expect(await screen.findByText("Post-run report view")).toBeInTheDocument();
    expect(
      await screen.findByText("model-b - model-a: 25.0 pp (paired_task_delta)"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("universal best-model claim").length).toBeGreaterThan(0);
  });

  it("keeps the v1 Stage 0 response schema typed during migration", () => {
    const planObj = plan();
    const parsed = DResponseSchema.parse({
      schema_version: "benchmark_advisor.v1",
      status: "approved",
      warnings: [],
      refusal: null,
      clarification: null,
      evidence_ledger: [],
      design: planObj.design,
      export_config: exportConfig(planObj),
    });

    expect(parsed.design?.task_budget).toBe(120);
    expect(parsed.export_config?.generation_knobs.handoff_target).toBe("scripts/build_corpus.py");
  });
});
