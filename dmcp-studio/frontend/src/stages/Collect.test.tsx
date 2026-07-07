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
    experiment_id: "E8.10d.qwen-vs-glm.workflow-stress",
    title: "Pairwise replay report for the default Advisor intent",
    headline: "qwen3.7-max and glm-5.1 remain statistically tied on workflow-stress tasks.",
    condition: "replay,target,p_alt=0.5,pool=8,budget=12,pass^3",
    sample_size: 200,
    model_count: 2,
    metric: "pass^3",
    mode: "replay",
    report: {
      schema_version: "benchmark_advisor.report.v2",
      mode: "pairwise",
      status: "warning",
      effect_sizes: [],
      confidence_intervals: [],
      rank_stability: null,
      slice_diagnostics: [],
      missingness: {
        missing_count: 0,
        total_count: 400,
        policy: "aggregate fixture",
        reasons: {},
      },
      multiplicity: {
        policy: "descriptive leaderboard with uncertainty",
        confirmatory_tests: 1,
        exploratory_tests: 15,
        note: "One primary corrected leaderboard.",
      },
      allowed_claims: ["Scoped corrected replay leaderboard."],
      not_allowed_claims: [
        "claim that the current corpus handoff itself already ran evaluation",
        "server-filtered claim over yfinance or finance-tools",
      ],
      issues: [
        {
          severity: "warning",
          code: "server_axis_unavailable_in_source_artifacts",
          message: "Server axis unavailable.",
          failed_field: "provenance.source_docs",
          failed_criterion_id: null,
          statistical_reason: "server metadata is absent",
          repair_options: ["Use raw eval/spec rows when available."],
          guide_references: [],
        },
      ],
    },
    leaderboard: [
      {
        rank: 1,
        model: "qwen3.7-max",
        passed: 99,
        n: 200,
        acc: 0.495,
        lo: 0.426,
        hi: 0.564,
        old_acc: 30.1,
        delta: 3.0,
      },
      {
        rank: 2,
        model: "glm-5.1",
        passed: 93,
        n: 200,
        acc: 0.465,
        lo: 0.397,
        hi: 0.534,
        old_acc: 47.9,
        delta: -3.0,
      },
    ],
    focus_slices: [
      {
        slice_id: "long_similar_chain",
        label: "Long similar chain",
        qwen_passed: 28,
        glm_passed: 26,
        n: 50,
        delta_pp: 4.0,
      },
    ],
    provenance: {
      source_docs: ["docs/experiments/e8.10d-corrected-leaderboard.md"],
      discarded_sources: ["docs/experiments/e8.8b-leaderboard-cleaned-750.md"],
      corpus: "TokenWasteGroup/DynamicMCPBench cleaned 750-task leaderboard slice",
      execution: "provider-pinned replay correction",
      generated_by_current_handoff: false,
      server_filter_available: false,
      server_filter_note:
        "The checked E8.10d JSON artifacts do not contain server/category metadata.",
    },
    data_quality: ["A finance/server-specific filter is not available."],
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
    expect(screen.getByText("E8.10d.qwen-vs-glm.workflow-stress")).toBeInTheDocument();
    expect(screen.getByText("qwen3.7-max")).toBeInTheDocument();
    expect(screen.getByText("Long similar chain")).toBeInTheDocument();
    expect(screen.getByText(/server\/category metadata/)).toBeInTheDocument();
    expect(
      screen.getByText(/current corpus handoff itself already ran evaluation/),
    ).toBeInTheDocument();
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
