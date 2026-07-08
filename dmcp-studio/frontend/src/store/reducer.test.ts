import { describe, expect, it } from "vitest";
import { equivOverrides, initialState, reducer, type StudioState } from "./reducer";
import { LaunchRequestSchema } from "../api/schemas";
import type { AdvisorV2DesignResponse, ExportConfig, ServerCard, StatisticalPlan } from "../types";

const servers: ServerCard[] = [
  { server_id: "yfinance", dynamism: "live_read", sandbox: false, description: "", tools: [] },
  { server_id: "arxiv", dynamism: "live_read", sandbox: false, description: "", tools: [] },
];

const carriedResponse: AdvisorV2DesignResponse = {
  schema_version: "benchmark_advisor.v2",
  status: "warning",
  statistical_plan: {
    schema_version: "benchmark_advisor.statistical_plan.v2",
    design: {} as StatisticalPlan["design"],
    power_analysis: {} as StatisticalPlan["power_analysis"],
    design_alternatives: [],
    assumption_ledger: {
      baseline_rate: 0.5,
      paired_design: true,
      independence_assumption: "unique tasks are the planning unit",
      repeated_attempts_policy: "attempts do not multiply iid N",
      missingness_policy: "explicit null with reason",
      multiplicity_policy: "single primary criterion",
      sensitivity_notes: [],
      guide_references: [],
    },
    issues: [],
    citations: [],
    claim_card: {
      allowed_claims: ["scoped claim"],
      not_allowed_claims: [],
      plain_language_summary: "approved with a warning",
    },
  },
  issues: [],
  export_config: {
    schema_version: "benchmark_advisor.v1",
    mode: "pairwise",
    candidate_models: ["agent-a", "agent-b"],
    evaluation_question: "Compare two local agents on finance workflows.",
    estimand: "paired pass-rate delta",
    hypotheses: {
      null: "No difference",
      alternative: "agent-b outperforms agent-a",
      non_inferiority_margin_pp: null,
    },
    criteria: [
      {
        criterion_id: "primary_effect",
        purpose: "primary model comparison",
        estimand: "paired pass-rate delta",
        null_hypothesis: "No difference",
        alternative_hypothesis: "agent-b outperforms agent-a",
        primary_metric: "trace_effect_pass_rate",
        test_family: "paired_bootstrap",
        alpha: 0.05,
        beta_or_target_power: 0.8,
        minimum_detectable_effect_pp: 10,
        required_data: ["paired task outcomes"],
        decision_rule: "bootstrap CI excludes zero",
        allowed_claim: "agent-b improves this scoped benchmark",
        failure_modes: ["missing outcomes"],
        confirmatory: true,
        guide_references: [
          {
            guide_version: "statistical_guide.v1",
            rule_id: "G4.budget.mode_thresholds",
            section: "Budget thresholds",
            role: "budget_power",
          },
        ],
        selection_rationale: "pairwise comparison",
      },
    ],
    tasks: 120,
    attempts_per_task: 3,
    task_distribution: {
      short_chain: 0.6,
      medium_chain: 0.3,
      long_chain: 0.1,
      cross_server_ratio: 0.3,
      recovery_required_ratio: 0.1,
      prerequisite_strict_ratio: 0.1,
      stateful_write_ratio: 0,
      distractors: {
        same_name_fraction: 0.3,
        near_miss_fraction: 0.3,
        cross_domain_fraction: 0.2,
        random_fraction: 0.2,
      },
      categories: ["finance"],
      diagnostic_slices: [],
    },
    distractors: {
      same_name_fraction: 0.3,
      near_miss_fraction: 0.3,
      cross_domain_fraction: 0.2,
      random_fraction: 0.2,
    },
    analysis_plan: {
      ci_method: "wilson_score",
      mde_method: "normal_approx_two_proportion",
      rank_stability_method: "bootstrap_tasks_within_strata",
      pairwise_test: "paired_bootstrap",
      alpha: 0.05,
      beta: 0.2,
      planning_assumptions: ["unique tasks are iid planning units"],
      heuristic_label: "planning_heuristic",
    },
    warnings: [],
    claim_boundary: "Scoped finance workflows only.",
    generation_knobs: {
      handoff_target: "scripts/build_corpus.py",
      dry_run_only: true,
      server_scope: ["finance-tools"],
      sandbox_required: true,
      goal_strategy: "deployment_slice",
      max_tool_calls_per_task: 6,
      generation_notes: ["dry-run preview only"],
    },
    intent_evidence: ["compare two finance agents"],
    statistical_guide_version: "statistical_guide.v1",
  } as ExportConfig,
  launchable: true,
};

describe("reducer", () => {
  it("auto-selects the first server only when nothing is selected", () => {
    const s = reducer(initialState(), { type: "servers_loaded", servers });
    expect(s.selected).toEqual(["yfinance"]);
    const s2 = reducer({ ...s, selected: ["arxiv"] }, { type: "servers_loaded", servers });
    expect(s2.selected).toEqual(["arxiv"]);
  });

  it("toggles server selection", () => {
    let s = reducer(initialState(), { type: "toggle_server", id: "arxiv" });
    expect(s.selected).toContain("arxiv");
    s = reducer(s, { type: "toggle_server", id: "arxiv" });
    expect(s.selected).not.toContain("arxiv");
  });

  it("enables every equivalence-set tool on distill", () => {
    const s = reducer(initialState(), {
      type: "distilled",
      spec: { checkpoints: [], minefields: [] },
      equivSets: { cp3: ["download", "get_price_history"] },
    });
    expect(s.equivOn).toEqual({ download: true, get_price_history: true });
    expect(s.distilled).toBe(true);
  });

  it("keeps at least one equivalence member enabled", () => {
    const base = reducer(initialState(), {
      type: "distilled",
      spec: { checkpoints: [], minefields: [] },
      equivSets: { cp3: ["download", "get_price_history"] },
    });
    const off = reducer(base, { type: "toggle_equiv", tool: "download" });
    expect(off.equivOn.download).toBe(false);
    // turning off the last remaining member is a no-op
    const stillOn = reducer(off, { type: "toggle_equiv", tool: "get_price_history" });
    expect(stillOn.equivOn.get_price_history).toBe(true);
  });

  it("computes equiv overrides only for a strict enabled subset", () => {
    const full: StudioState = {
      ...initialState(),
      equivSets: { cp3: ["download", "get_price_history"] },
      equivOn: { download: true, get_price_history: true },
    };
    expect(equivOverrides(full.equivOn, full.equivSets)).toBe("");
    expect(equivOverrides({ download: true, get_price_history: false }, full.equivSets)).toBe(
      "download",
    );
  });

  it("resets the walkthrough on mode change", () => {
    const dirty: StudioState = { ...initialState(), explored: true, distilled: true, ran: true };
    const s = reducer(dirty, { type: "reset_for_mode", mode: "live" });
    expect(s).toMatchObject({
      mode: "live",
      view: "collect",
      explored: false,
      distilled: false,
      ran: false,
    });
  });

  it("persists launchable advisor state when carrying a design into Collect", () => {
    const s = reducer(initialState(), { type: "carry_advisor_design", response: carriedResponse });
    expect(s.view).toBe("collect");
    expect(s.selected).toEqual(["finance-tools"]);
    expect(s.advisorCarry).toMatchObject({
      responseStatus: "warning",
      launchable: true,
      sandboxRequired: true,
      serverScope: ["finance-tools"],
    });
    expect(s.advisorCarry?.exportConfig.tasks).toBe(120);
    expect(() =>
      LaunchRequestSchema.parse({
        schema_version: "benchmark_advisor.launch.v2",
        export_config: s.advisorCarry?.exportConfig,
        advisor_status: s.advisorCarry?.responseStatus,
        confirmation: true,
        sandbox_confirmed: true,
        dry_run: false,
        requested_by_ui: true,
      }),
    ).not.toThrow();
  });

  it("does not carry refused or incomplete advisor responses", () => {
    const refused = { ...carriedResponse, launchable: false, export_config: null };
    const s = reducer(initialState(), { type: "carry_advisor_design", response: refused });
    expect(s.view).toBe("design");
    expect(s.advisorCarry).toBeNull();
  });
});
