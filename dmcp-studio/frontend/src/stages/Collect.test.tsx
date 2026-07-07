import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { StudioContext, type Studio } from "../store/context";
import { initialState } from "../store/reducer";
import { Collect } from "./Collect";
import type { AdvisorCarryState } from "../store/reducer";
import type { ExportConfig, LaunchJob, StatisticalPlan } from "../types";
import type { ReplayDemoReport } from "../types";

function carriedState(): AdvisorCarryState {
  const exportConfig = {
    tasks: 120,
    attempts_per_task: 3,
    generation_knobs: {
      goal_strategy: "deployment_slice",
      server_scope: ["finance-tools"],
      sandbox_required: false,
    },
  } as ExportConfig;
  return {
    responseStatus: "approved",
    statisticalPlan: {
      assumption_ledger: {
        independence_assumption: "unique tasks are the planning unit",
        repeated_attempts_policy: "attempts do not multiply unique-task power",
      },
    } as StatisticalPlan,
    exportConfig,
    launchable: true,
    sandboxRequired: false,
    serverScope: ["finance-tools"],
  };
}

function studioValue(
  advisorCarry: AdvisorCarryState | null = carriedState(),
  mode: "replay" | "live" = "replay",
): Studio {
  return {
    ...initialState(mode),
    advisorCarry,
    servers: [
      {
        server_id: "finance-tools",
        dynamism: "live_read",
        sandbox: false,
        description: "Finance data tools",
        tools: ["quote"],
      },
    ],
    selected: ["finance-tools"],
    go: vi.fn(),
    carryAdvisorDesign: vi.fn(),
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

function launchJob(): LaunchJob {
  return {
    schema_version: "benchmark_advisor.launch_job.v2",
    job_id: "advisor-job-1",
    status: "succeeded",
    command_preview: [
      "python",
      "scripts/build_corpus.py",
      "--out",
      "data/advisor_runs/demo",
      "--strategies",
      "hard_neg,complementary",
    ],
    logs: ["queued guarded corpus handoff", "scripts/build_corpus.py exited with 0"],
    artifacts: {
      goals: "data/advisor_runs/demo/goals_full.json",
      specs: "data/advisor_runs/demo/specs.jsonl",
      traces: "data/advisor_runs/demo/traces.jsonl",
      coverage: "data/advisor_runs/demo/coverage.json",
    },
  };
}

function replayDemoReport(): ReplayDemoReport {
  return {
    schema_version: "benchmark_advisor.replay_demo_report.v1",
    experiment_id: "BA7.hydra.finance.deepseek-vs-minimax.combined100",
    title: "Pairwise replay report for the default Advisor intent",
    headline:
      "deepseek-v4-flash and minimax-m3 remain statistically tied on generated finance tasks.",
    condition: "live-generated corpus, yfinance finance-tools scope, 100 tasks, pass^1",
    sample_size: 100,
    model_count: 2,
    metric: "pass^1",
    mode: "replay",
    report: {
      schema_version: "benchmark_advisor.report.v2",
      mode: "pairwise",
      status: "warning",
      effect_sizes: [
        {
          label: "deepseek-v4-flash - minimax-m3 on generated finance corpus",
          estimate_pp: 2.0,
          method: "paired_bootstrap_tasks",
        },
        {
          label: "planned MDE for 100 unique paired tasks",
          estimate_pp: 19.81,
          method: "planning_heuristic_mde",
        },
      ],
      confidence_intervals: [
        {
          label: "deepseek-v4-flash - minimax-m3 paired delta",
          low_pp: -8.0,
          high_pp: 12.0,
          method: "paired_bootstrap_tasks",
        },
      ],
      rank_stability: null,
      slice_diagnostics: [],
      missingness: {
        missing_count: 0,
        total_count: 200,
        policy: "combined full pairwise eval",
        reasons: {},
      },
      multiplicity: {
        policy: "one primary paired comparison with exploratory slices",
        confirmatory_tests: 1,
        exploratory_tests: 5,
        note: "One primary generated-corpus pairwise comparison.",
      },
      allowed_claims: ["Scoped generated finance-corpus pairwise comparison."],
      not_allowed_claims: [
        "claim about pass^3 reliability; these evals used attempts_per_task=1",
        "universal best-model claim outside this finance/yfinance generated corpus",
      ],
      issues: [
        {
          severity: "warning",
          code: "paired_delta_ci_crosses_zero",
          message: "The paired delta CI crosses zero.",
          failed_field: "report.confidence_intervals",
          failed_criterion_id: "criterion.primary",
          statistical_reason: "observed delta is below planned MDE",
          repair_options: ["Report this as an inconclusive scoped demo comparison."],
          guide_references: [],
        },
      ],
    },
    leaderboard: [
      {
        rank: 1,
        model: "deepseek-v4-flash",
        passed: 39,
        n: 100,
        acc: 0.39,
        lo: 0.300,
        hi: 0.488,
        old_acc: 0,
        delta: 2.0,
      },
      {
        rank: 2,
        model: "minimax-m3",
        passed: 37,
        n: 100,
        acc: 0.37,
        lo: 0.282,
        hi: 0.468,
        old_acc: 0,
        delta: -2.0,
      },
    ],
    focus_slices: [
      {
        slice_id: "long_chain",
        label: "Long chain",
        model_a_passed: 17,
        model_b_passed: 13,
        n: 55,
        delta_pp: 7.273,
      },
    ],
    provenance: {
      source_docs: [
        "data/advisor_runs/ba7_default_design_corpus_20260707_123630_combined100/eval_combined100/summary_pairwise_deepseek_minimax_combined100.json",
      ],
      discarded_sources: [],
      corpus: "BA7 combined100 generated finance corpus",
      execution: "Hydra OpenAI-compatible routing",
      generated_by_current_handoff: true,
      server_filter_available: true,
      server_filter_note: "All 100 combined tasks use yfinance under finance-tools scope.",
    },
    data_quality: ["Eval metric is pass^1 because attempts_per_task=1 was used."],
    figures: [],
  };
}

describe("Collect advisor handoff", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders carried advisor state and replay-only statistical report", async () => {
    const launchSpy = vi.spyOn(api, "advisorV2Launch");
    vi.spyOn(api, "health").mockResolvedValue({
      status: "ok",
      mode_default: "replay",
      capabilities: { advisor_v2_replay_demo_report: true },
    });
    vi.spyOn(api, "advisorV2ReplayDemoReport").mockResolvedValue(replayDemoReport());

    render(
      <StudioContext.Provider value={studioValue()}>
        <Collect />
      </StudioContext.Provider>,
    );

    expect(screen.getByText("Advisor handoff")).toBeInTheDocument();
    expect(screen.getByText("deployment_slice")).toBeInTheDocument();
    expect(screen.getByText("unique tasks are the planning unit")).toBeInTheDocument();
    expect(screen.getByText("replay report available after confirmation")).toBeInTheDocument();
    expect(screen.getByText("replay mode: no corpus launch")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Start replay demo" });
    expect(button).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Confirm replay demo report load"));
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(await screen.findByText("Launch job")).toBeInTheDocument();
    expect(launchSpy).not.toHaveBeenCalled();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText(/replay-only no-corpus-handoff load/)).toBeInTheDocument();
    expect(screen.getByText("specs: -")).toBeInTheDocument();
    expect(
      screen.getByText(/replay mode: no real corpus handoff was launched/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/loading frozen Benchmark Advisor post-run report fixture/),
    ).toBeInTheDocument();
    expect(await screen.findByText("Replay statistical report")).toBeInTheDocument();
    expect(
      screen.getByText("BA7.hydra.finance.deepseek-vs-minimax.combined100"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("deepseek-v4-flash").length).toBeGreaterThan(0);
    expect(screen.getByText("Long chain")).toBeInTheDocument();
    expect(screen.getByText(/19.8 pp/)).toBeInTheDocument();
    expect(screen.getByText(/pass\^3 reliability/)).toBeInTheDocument();
  });

  it("shows the backend launch refusal detail", async () => {
    vi.spyOn(api, "advisorV2Launch").mockRejectedValue(
      new Error("/api/advisor/v2/launch -> 400: sandbox requirements must be explicitly confirmed"),
    );

    render(
      <StudioContext.Provider value={studioValue(carriedState(), "live")}>
        <Collect />
      </StudioContext.Provider>,
    );

    fireEvent.click(screen.getByLabelText("Confirm guarded corpus/specs/traces launch"));
    fireEvent.click(await screen.findByRole("button", { name: "Start corpus handoff" }));

    expect(
      await screen.findByText(/sandbox requirements must be explicitly confirmed/),
    ).toBeInTheDocument();
  });

  it("does not show the replay demo report in live mode", async () => {
    const launchSpy = vi.spyOn(api, "advisorV2Launch").mockResolvedValue(launchJob());
    vi.spyOn(api, "health").mockResolvedValue({
      status: "ok",
      mode_default: "replay",
      capabilities: { advisor_v2_replay_demo_report: true },
    });
    const reportSpy = vi
      .spyOn(api, "advisorV2ReplayDemoReport")
      .mockResolvedValue(replayDemoReport());

    render(
      <StudioContext.Provider value={studioValue(carriedState(), "live")}>
        <Collect />
      </StudioContext.Provider>,
    );

    fireEvent.click(screen.getByLabelText("Confirm guarded corpus/specs/traces launch"));
    fireEvent.click(await screen.findByRole("button", { name: "Start corpus handoff" }));

    await waitFor(() => expect(screen.getByText("Launch job")).toBeInTheDocument());
    expect(launchSpy).toHaveBeenCalledOnce();
    expect(screen.queryByText("Replay statistical report")).not.toBeInTheDocument();
    expect(reportSpy).not.toHaveBeenCalled();
  });
});
