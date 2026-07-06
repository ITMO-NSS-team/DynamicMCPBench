import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { StudioContext, type Studio } from "../store/context";
import { initialState } from "../store/reducer";
import { Collect } from "./Collect";
import type { AdvisorCarryState } from "../store/reducer";
import type { ExportConfig, LaunchJob, StatisticalPlan } from "../types";

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

function studioValue(advisorCarry: AdvisorCarryState | null = carriedState()): Studio {
  return {
    ...initialState(),
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

describe("Collect advisor handoff", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders carried advisor state and launch job artifacts", async () => {
    const launchSpy = vi.spyOn(api, "advisorV2Launch").mockResolvedValue(launchJob());

    render(
      <StudioContext.Provider value={studioValue()}>
        <Collect />
      </StudioContext.Provider>,
    );

    expect(screen.getByText("Advisor handoff")).toBeInTheDocument();
    expect(screen.getByText("deployment_slice")).toBeInTheDocument();
    expect(screen.getByText("unique tasks are the planning unit")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Start corpus handoff" });
    expect(button).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Confirm guarded corpus/specs/traces launch"));
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    await waitFor(() => expect(launchSpy).toHaveBeenCalledOnce());
    expect(launchSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        schema_version: "benchmark_advisor.launch.v2",
        advisor_status: "approved",
        confirmation: true,
        dry_run: false,
        requested_by_ui: true,
      }),
    );
    expect(await screen.findByText("Launch job")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getAllByText(/scripts\/build_corpus\.py/).length).toBeGreaterThan(0);
    expect(screen.getByText("specs: data/advisor_runs/demo/specs.jsonl")).toBeInTheDocument();
    expect(screen.getByText(/scripts\/build_corpus\.py exited with 0/)).toBeInTheDocument();
  });

  it("shows the backend launch refusal detail", async () => {
    vi.spyOn(api, "advisorV2Launch").mockRejectedValue(
      new Error("/api/advisor/v2/launch -> 400: sandbox requirements must be explicitly confirmed"),
    );

    render(
      <StudioContext.Provider value={studioValue()}>
        <Collect />
      </StudioContext.Provider>,
    );

    fireEvent.click(screen.getByLabelText("Confirm guarded corpus/specs/traces launch"));
    fireEvent.click(await screen.findByRole("button", { name: "Start corpus handoff" }));

    expect(
      await screen.findByText(/sandbox requirements must be explicitly confirmed/),
    ).toBeInTheDocument();
  });
});
