import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  createContext,
  type ReactNode,
} from "react";
import { Button, Textarea } from "../ui";
import { Slider } from "../components/Slider";
import { api } from "../api/client";
import { useStudio } from "../store/context";
import { advisorVerdict } from "../lib/verdict";
import { Verdict } from "../components/Verdict";
import type {
  AdvisorMode,
  AdvisorV2DesignRequest,
  AdvisorV2DesignResponse,
  DStatus,
  OutcomeTensor,
  StatisticalPlan,
  StatisticalReport,
  TaskDistribution,
} from "../types";

const ADVISOR_MODES: AdvisorMode[] = ["pairwise", "leaderboard", "regression", "diagnostic"];
const DISTRIBUTION_KEYS = [
  ["short_chain", "short chain"],
  ["medium_chain", "medium chain"],
  ["long_chain", "long chain"],
  ["cross_server_ratio", "cross-server"],
  ["recovery_required_ratio", "recovery"],
  ["prerequisite_strict_ratio", "prerequisite"],
  ["stateful_write_ratio", "stateful write"],
] as const;
const DEFAULT_ADVISOR_INTENT =
  "Compare two local agents on long, multi-step finance workflows and tell me which is better.";
const DEFAULT_ADVISOR_MODE: AdvisorMode = "pairwise";
const DEFAULT_ADVISOR_MODELS = "deepseek-v4-flash, minimax-m3";
const DEFAULT_ADVISOR_SERVER_SCOPE = "finance-tools";
const DEFAULT_ADVISOR_TASK_BUDGET = 100;
const DEFAULT_ADVISOR_ATTEMPTS = 1;
const DEFAULT_ADVISOR_TARGET_PP = 0;
const DEFAULT_ADVISOR_SANDBOX_REQUIRED = false;

type DistributionKey = (typeof DISTRIBUTION_KEYS)[number][0];
type DistributionEdit = Pick<TaskDistribution, DistributionKey>;
type BusyState = "design" | "validate" | "report" | null;
type FieldHelp = {
  title: string;
  body: string;
  detail?: string;
};
type FieldHelpContextValue = {
  show: (help: FieldHelp, x: number, y: number) => void;
  move: (x: number, y: number) => void;
  hide: () => void;
};

const FieldHelpContext = createContext<FieldHelpContextValue | null>(null);

const HELP = {
  planningRequest: {
    title: "Planning request",
    body: "User-facing input sent to the v2 design route. It says what you want the advisor to plan, before the statistical engine transforms it into a validated design.",
  },
  intent: {
    title: "Free-text planning request",
    body: "Natural-language benchmark question. The planner uses this to infer the evaluation question, claim scope, mode, task mix, and statistical method family.",
  },
  advisorMode: {
    title: "advisor mode",
    body: "Selects the benchmark question family: pairwise comparison, leaderboard ranking, regression/non-inferiority check, or diagnostic slice analysis.",
  },
  candidateModels: {
    title: "candidate models",
    body: "Comma-separated models or agents being evaluated. Pairwise and regression expect exactly two; leaderboard expects at least three.",
  },
  serverScope: {
    title: "server scope",
    body: "Comma-separated tool/server domains that constrain the benchmark environment. This is the environment under test, not the model list.",
  },
  requestedBudget: {
    title: "requested task budget",
    body: "Unique tasks requested by the user. Attempts do not multiply this into independent samples; unique tasks remain the main planning unit.",
  },
  requestedAttempts: {
    title: "requested attempts / task",
    body: "Repeated attempts per task. Useful for reliability metrics, but they do not create independent new tasks for power planning.",
  },
  requestedTarget: {
    title: "requested target effect",
    body: "Minimum detectable effect requested in percentage points. Zero means engine default. In regression mode this acts as the predeclared non-inferiority margin.",
  },
  sandbox: {
    title: "sandbox required",
    body: "Marks that the planned benchmark needs sandboxed execution. This is important for stateful-write tasks or tools with external side effects.",
  },
  advisorVerdict: {
    title: "Advisor verdict",
    body: "Current validated response status and issue count. Approved or warning designs can be carried forward; refused designs need repairs first.",
  },
  metricTasks: {
    title: "tasks",
    body: "Unique task budget in the selected statistical plan. This may differ from the requested budget if the engine recommends a different defensible design.",
  },
  metricAttempts: {
    title: "attempts",
    body: "Attempts per unique task in the selected plan. Attempts support reliability views but do not multiply iid sample size.",
  },
  plannedMde: {
    title: "planned MDE",
    body: "Pre-run minimum detectable effect estimate in percentage points. It is a planning heuristic, not a final inferential guarantee.",
  },
  ciWidth: {
    title: "CI width",
    body: "Pre-run confidence-interval width estimate. Smaller width means more planned precision, mostly from more unique tasks.",
  },
  launchable: {
    title: "launchable",
    body: "Whether the current response can be carried forward. Refused or clarification-needed designs are not launchable.",
  },
  editablePlan: {
    title: "Editable statistical plan",
    body: "The advisor's structured output. Editing these fields revalidates the plan through the v2 validate route, rather than merely changing local UI text.",
  },
  planModels: {
    title: "plan models",
    body: "Candidate models inside the selected statistical plan. Changing them can invalidate mode-specific requirements.",
  },
  planServerScope: {
    title: "plan server scope",
    body: "Server scope used when revalidating the edited plan. It updates the validation context around the plan.",
  },
  planBudget: {
    title: "plan task budget",
    body: "Unique task count in the selected plan. Increasing it usually lowers planned MDE and narrows CI width.",
  },
  planAttempts: {
    title: "plan attempts / task",
    body: "Attempts per task in the plan. This can support reliability metrics, but unique tasks remain the power unit.",
  },
  planTarget: {
    title: "plan target effect",
    body: "Target detectable effect in percentage points. Positive values are explicit targets; zero means not set.",
  },
  planSandbox: {
    title: "plan sandbox required",
    body: "Sandbox flag used for the current plan validation context. It is especially relevant when stateful-write coverage is nonzero.",
  },
  taskDistribution: {
    title: "task distribution",
    body: "Planned coverage ratios for task properties. These sliders are not a single partition; one task can be long-chain, cross-server, and stateful-write.",
  },
  shortChain: {
    title: "short chain",
    body: "Ratio of short workflows. High coverage supports short-workflow claims, not long-horizon claims.",
  },
  mediumChain: {
    title: "medium chain",
    body: "Ratio of medium workflows. This is bridge coverage for mixed workflow claims.",
  },
  longChain: {
    title: "long chain",
    body: "Ratio of long multi-step workflows. Low coverage weakens long-workflow or production-like claims.",
  },
  crossServer: {
    title: "cross-server",
    body: "Ratio of tasks requiring multi-server orchestration. Important for wrong-server and composition claims.",
  },
  recovery: {
    title: "recovery",
    body: "Ratio of tasks requiring retry, repair, or error recovery. Needed for robustness/recovery claims.",
  },
  prerequisite: {
    title: "prerequisite",
    body: "Ratio of tasks with strict step dependencies. These stress workflow ordering and prerequisite handling.",
  },
  statefulWrite: {
    title: "stateful write",
    body: "Ratio of tasks that mutate state. These usually require sandboxing and reset/replay policy.",
  },
  claimCard: {
    title: "Claim card",
    body: "States what the design can and cannot support. It prevents a narrow design from being overread as a universal benchmark result.",
  },
  methodCard: {
    title: "Method card",
    body: "Shows the selected statistical method family, alpha, target power, and engine provenance for the current plan.",
  },
  alpha: {
    title: "alpha",
    body: "Significance level for the primary criterion. The default request uses 0.05.",
  },
  targetPower: {
    title: "target power",
    body: "Target probability of detecting the target effect under planning assumptions. Beta 0.2 corresponds to power 0.8.",
  },
  method: {
    title: "method",
    body: "Primary test family, such as paired bootstrap, non-inferiority margin, rank-stability bootstrap, or diagnostic descriptive.",
  },
  engineCandidates: {
    title: "engine candidates",
    body: "Number of candidate designs considered by the deterministic engine. Edited-plan validation usually refreshes one candidate.",
  },
  powerCurve: {
    title: "Power curve",
    body: "Budget-to-precision preview over unique tasks. It shows how planned MDE and CI width change with task budget.",
  },
  assumptions: {
    title: "Assumptions",
    body: "Assumption ledger behind power and claim planning: baseline rate, independence, attempts policy, missingness, and multiplicity.",
  },
  baselineRate: {
    title: "baseline rate",
    body: "Assumed pass/success rate used for MDE and CI planning. The current UI usually shows the engine default.",
  },
  independence: {
    title: "independence",
    body: "States that unique tasks are the planning unit and effective sample size can be smaller under shared templates, servers, or trajectories.",
  },
  attemptsPolicy: {
    title: "attempts",
    body: "Explains that repeated attempts can support reliability metrics but do not multiply unique-task power.",
  },
  missingness: {
    title: "missingness",
    body: "Policy for absent outcomes. Missing cells should be explicit nulls with reasons before post-run reporting.",
  },
  multiplicity: {
    title: "multiplicity",
    body: "Policy for multiple tests or slices. Diagnostics remain exploratory unless predeclared, powered, and corrected.",
  },
  alternatives: {
    title: "Alternatives",
    body: "Other searched designs, such as cheaper, recommended, stronger, or narrowed-claim options, with their status and tradeoff.",
  },
  issues: {
    title: "Issues and repairs",
    body: "All validation issues currently attached to the design. Each issue includes severity, reason, failed field or criterion, and repairs.",
  },
  citations: {
    title: "Citations",
    body: "Local guide cards that justify the design. These come from the static statistical guide, not live web retrieval.",
  },
  postRun: {
    title: "Post-run report view",
    body: "Preview of the Stage 2 report shape. On this Design page it is built from a fixture tensor, not from a real completed benchmark run.",
    detail:
      "Read it as: if this plan later has outcomes, this is the kind of report Studio will show.",
  },
  reportStatus: {
    title: "status",
    body: "Post-run report status after analyzing outcomes. It can differ from pre-run design status if results are missing or invalid.",
  },
  reportMissing: {
    title: "missing",
    body: "Number of missing outcome cells in the report tensor. Missing outcomes weaken or can block claims.",
  },
  confirmatory: {
    title: "confirmatory",
    body: "Number of predeclared tests that can support stronger claims when the plan and multiplicity policy allow it.",
  },
  exploratory: {
    title: "exploratory",
    body: "Number of diagnostic or non-primary tests. Useful for discovery, but not automatically confirmatory.",
  },
  effectSizes: {
    title: "Effect sizes",
    body: "Observed post-run estimates, such as paired task delta or model pass rate. In the current preview these come from fixture outcomes.",
  },
  confidenceIntervals: {
    title: "Confidence intervals",
    body: "Post-run uncertainty intervals computed from outcome data. In the current preview these come from fixture outcomes.",
  },
  rankStability: {
    title: "rank stability",
    body: "Leaderboard stability estimate from task bootstrap. It helps avoid overclaiming exact rankings from noisy samples.",
  },
  reportClaims: {
    title: "Report claims",
    body: "Claims supported by the completed outcome tensor. On this page they are only a preview because the tensor is synthetic.",
  },
  reportBoundaries: {
    title: "Report boundaries",
    body: "Claims the final report must not make, such as universal best-model or private-deployment guarantees.",
  },
  exportPreview: {
    title: "Export preview",
    body: "Typed dry-run export configuration when the design is launchable. It previews handoff data; it is not a completed launch.",
  },
} satisfies Record<string, FieldHelp>;

const DISTRIBUTION_HELP: Record<DistributionKey, FieldHelp> = {
  short_chain: HELP.shortChain,
  medium_chain: HELP.mediumChain,
  long_chain: HELP.longChain,
  cross_server_ratio: HELP.crossServer,
  recovery_required_ratio: HELP.recovery,
  prerequisite_strict_ratio: HELP.prerequisite,
  stateful_write_ratio: HELP.statefulWrite,
};

export function Design() {
  const s = useStudio();
  const [intent, setIntent] = useState(DEFAULT_ADVISOR_INTENT);
  const [requestMode, setRequestMode] = useState<AdvisorMode>(DEFAULT_ADVISOR_MODE);
  const [requestModels, setRequestModels] = useState(DEFAULT_ADVISOR_MODELS);
  const [requestServerScope, setRequestServerScope] = useState(DEFAULT_ADVISOR_SERVER_SCOPE);
  const [requestBudget, setRequestBudget] = useState(DEFAULT_ADVISOR_TASK_BUDGET);
  const [requestAttempts, setRequestAttempts] = useState(DEFAULT_ADVISOR_ATTEMPTS);
  const [requestTarget, setRequestTarget] = useState(DEFAULT_ADVISOR_TARGET_PP);
  const [requestSandbox, setRequestSandbox] = useState(DEFAULT_ADVISOR_SANDBOX_REQUIRED);

  const [planBudget, setPlanBudget] = useState(DEFAULT_ADVISOR_TASK_BUDGET);
  const [planAttempts, setPlanAttempts] = useState(DEFAULT_ADVISOR_ATTEMPTS);
  const [planTarget, setPlanTarget] = useState(DEFAULT_ADVISOR_TARGET_PP);
  const [planModels, setPlanModels] = useState(DEFAULT_ADVISOR_MODELS);
  const [planServerScope, setPlanServerScope] = useState(DEFAULT_ADVISOR_SERVER_SCOPE);
  const [planSandbox, setPlanSandbox] = useState(DEFAULT_ADVISOR_SANDBOX_REQUIRED);
  const [planDistribution, setPlanDistribution] = useState<DistributionEdit | null>(null);

  const [resp, setResp] = useState<AdvisorV2DesignResponse | null>(null);
  const [report, setReport] = useState<StatisticalReport | null>(null);
  const [busy, setBusy] = useState<BusyState>(null);
  const [error, setError] = useState<string | null>(null);

  const requestId = useRef(0);
  const reportId = useRef(0);

  const requestModelList = useMemo(() => csv(requestModels), [requestModels]);
  const requestServerList = useMemo(() => csv(requestServerScope), [requestServerScope]);
  const currentPlan = resp?.statistical_plan ?? null;

  const buildRequest = useCallback(
    (): AdvisorV2DesignRequest => ({
      schema_version: "benchmark_advisor.v2",
      intent: intent.trim() || "Compare two agents.",
      mode: requestMode,
      task_budget: requestBudget,
      attempts_per_task: requestAttempts,
      candidate_models: requestModelList,
      target_detectable_effect_pp: requestTarget > 0 ? requestTarget : null,
      alpha: 0.05,
      beta: 0.2,
      deployment_context: null,
      server_scope: requestServerList,
      user_overrides: { sandbox_required: requestSandbox },
      retrieval_mode: "local_only",
    }),
    [
      intent,
      requestAttempts,
      requestBudget,
      requestMode,
      requestModelList,
      requestSandbox,
      requestServerList,
      requestTarget,
    ],
  );

  const syncPlanControls = useCallback((plan: StatisticalPlan, req: AdvisorV2DesignRequest) => {
    const design = plan.design;
    setPlanBudget(design.task_budget);
    setPlanAttempts(design.attempts_per_task);
    setPlanTarget(design.target_detectable_effect_pp ?? 0);
    setPlanModels(design.candidate_models.join(", "));
    setPlanServerScope(req.server_scope.join(", "));
    setPlanSandbox(Boolean(req.user_overrides.sandbox_required));
    setPlanDistribution(pickDistribution(design.task_distribution));
  }, []);

  const requestDesign = useCallback(async () => {
    const req = buildRequest();
    const id = ++requestId.current;
    setBusy("design");
    try {
      const health = await api.health();
      if (health.capabilities?.advisor_v2 !== true) {
        if (id === requestId.current) {
          setResp(null);
          setPlanDistribution(null);
          setError("Studio backend is stale. Restart Studio so the v2 advisor routes are loaded.");
        }
        return;
      }
      const next = await api.advisorV2Design(req);
      if (id !== requestId.current) return;
      setResp(next);
      setError(null);
      if (next.statistical_plan) syncPlanControls(next.statistical_plan, req);
      if (!next.statistical_plan) setPlanDistribution(null);
    } catch (err) {
      if (id === requestId.current) {
        const message = err instanceof Error ? err.message : "";
        setError(
          message.includes("/api/advisor/v2/design")
            ? "Studio backend is stale. Restart Studio so the v2 advisor routes are loaded."
            : "Could not reach the Studio backend.",
        );
      }
    } finally {
      if (id === requestId.current) setBusy(null);
    }
  }, [buildRequest, syncPlanControls]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void requestDesign();
    }, 180);
    return () => window.clearTimeout(handle);
  }, [requestDesign]);

  const validationOriginalRequest = useCallback(
    (serverScopeCsv = planServerScope, sandboxRequired = planSandbox): AdvisorV2DesignRequest => {
      const base = buildRequest();
      return {
        ...base,
        server_scope: csv(serverScopeCsv),
        user_overrides: {
          ...base.user_overrides,
          sandbox_required: sandboxRequired,
        },
      };
    },
    [buildRequest, planSandbox, planServerScope],
  );

  const validateEditedPlan = useCallback(
    async (
      nextPlan: StatisticalPlan,
      editedFields: string[],
      originalRequest = validationOriginalRequest(),
    ) => {
      const id = ++requestId.current;
      setBusy("validate");
      try {
        const next = await api.advisorV2Validate({
          schema_version: "benchmark_advisor.v2",
          statistical_plan: nextPlan,
          original_request: originalRequest,
          edited_fields: editedFields,
        });
        if (id !== requestId.current) return;
        setResp(next);
        setError(null);
        if (next.statistical_plan) syncPlanControls(next.statistical_plan, originalRequest);
      } catch {
        if (id === requestId.current) setError("Could not validate the edited v2 plan.");
      } finally {
        if (id === requestId.current) setBusy(null);
      }
    },
    [syncPlanControls, validationOriginalRequest],
  );

  const editPlan = useCallback(
    (editedFields: string[], mutate: (plan: StatisticalPlan) => void) => {
      if (!currentPlan) return;
      const nextPlan = structuredClone(currentPlan);
      mutate(nextPlan);
      void validateEditedPlan(nextPlan, editedFields);
    },
    [currentPlan, validateEditedPlan],
  );

  useEffect(() => {
    if (!currentPlan) {
      setReport(null);
      return;
    }
    const id = ++reportId.current;
    setBusy((value) => value ?? "report");
    void api
      .advisorV2Report({
        schema_version: "benchmark_advisor.v2",
        outcome_tensor: reportFixtureForPlan(currentPlan),
        statistical_plan: currentPlan,
      })
      .then((next) => {
        if (id === reportId.current) setReport(next.report);
      })
      .catch(() => {
        if (id === reportId.current) setReport(null);
      })
      .finally(() => {
        if (id === reportId.current) setBusy((value) => (value === "report" ? null : value));
      });
  }, [currentPlan]);

  const status = resp?.status ?? null;
  const verdict = status ? advisorVerdict(status) : null;
  const canProceed = resp?.launchable === true && resp.status !== "refused";
  const issueCount = resp?.issues.length ?? 0;

  const changePlanBudget = (value: number) => {
    setPlanBudget(value);
    editPlan(["design.task_budget"], (plan) => {
      plan.design.task_budget = value;
    });
  };

  const changePlanAttempts = (value: number) => {
    setPlanAttempts(value);
    editPlan(["design.attempts_per_task"], (plan) => {
      plan.design.attempts_per_task = value;
    });
  };

  const changePlanTarget = (value: number) => {
    setPlanTarget(value);
    editPlan(["design.target_detectable_effect_pp"], (plan) => {
      plan.design.target_detectable_effect_pp = value > 0 ? value : null;
    });
  };

  const changePlanModels = (value: string) => {
    setPlanModels(value);
    editPlan(["design.candidate_models"], (plan) => {
      plan.design.candidate_models = csv(value);
    });
  };

  const changePlanServerScope = (value: string) => {
    setPlanServerScope(value);
    if (!currentPlan) return;
    void validateEditedPlan(
      currentPlan,
      ["server_scope"],
      validationOriginalRequest(value, planSandbox),
    );
  };

  const changePlanSandbox = (value: boolean) => {
    setPlanSandbox(value);
    if (!currentPlan) return;
    void validateEditedPlan(
      currentPlan,
      ["user_overrides.sandbox_required"],
      validationOriginalRequest(planServerScope, value),
    );
  };

  const changeDistribution = (key: DistributionKey, value: number) => {
    setPlanDistribution((prev) => (prev ? { ...prev, [key]: value } : prev));
    editPlan([`design.task_distribution.${key}`], (plan) => {
      plan.design.task_distribution[key] = value;
    });
  };

  return (
    <FieldHelpProvider>
      <section className="stage advisor-v2">
        <div className="eyebrow">Stage 0 - Statistical Advisor v2</div>
        <h1>Statistical benchmark design</h1>
        <p className="lede">
          Claim scope, method choice, power, assumptions, repairs, citations, and post-run report
          shape are visible before the benchmark moves forward.
        </p>

        {error && (
          <div className="error-banner" role="alert">
            <b>{error}</b>
            <button type="button" className="error-dismiss" onClick={() => setError(null)}>
              x
            </button>
          </div>
        )}

        <div className="split advisor-layout" style={{ marginTop: 28 }}>
          <div className="panel sticky-col">
            <div className="panel-head">
              <FieldHelpTarget help={HELP.planningRequest}>
                <span className="panel-title">Planning request</span>
              </FieldHelpTarget>
              <span className="panel-sub">{busy === "design" ? "designing..." : requestMode}</span>
            </div>
            <div className="panel-body stack-gap">
              <FieldHelpTarget help={HELP.intent}>
                <Textarea
                  width="100%"
                  rows={3}
                  value={intent}
                  onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setIntent(e.target.value)}
                  placeholder="What do you want to find out?"
                />
              </FieldHelpTarget>

              <FieldHelpTarget help={HELP.advisorMode}>
                <div className="section-label">advisor mode</div>
                <div className="seg seg-wrap" role="group" aria-label="advisor mode">
                  {ADVISOR_MODES.map((mode) => (
                    <button
                      type="button"
                      key={mode}
                      data-on={requestMode === mode}
                      onClick={() => setRequestMode(mode)}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </FieldHelpTarget>

              <TextField
                label="candidate models"
                value={requestModels}
                onChange={setRequestModels}
                help={HELP.candidateModels}
              />
              <TextField
                label="server scope"
                value={requestServerScope}
                onChange={setRequestServerScope}
                help={HELP.serverScope}
              />

              <Field
                label="requested task budget"
                value={String(requestBudget)}
                help={HELP.requestedBudget}
              >
                <Slider
                  label="requested task budget"
                  value={requestBudget}
                  min={10}
                  max={300}
                  step={5}
                  onChange={setRequestBudget}
                />
              </Field>
              <Field
                label="requested attempts / task"
                value={String(requestAttempts)}
                help={HELP.requestedAttempts}
              >
                <Slider
                  label="requested attempts per task"
                  value={requestAttempts}
                  min={1}
                  max={5}
                  step={1}
                  onChange={setRequestAttempts}
                />
              </Field>
              <Field
                label="requested target effect"
                value={requestTarget > 0 ? `${requestTarget} pp` : "engine default"}
                help={HELP.requestedTarget}
              >
                <Slider
                  label="requested target effect"
                  value={requestTarget}
                  min={0}
                  max={30}
                  step={1}
                  onChange={setRequestTarget}
                />
              </Field>
              <CheckField
                label="sandbox required"
                checked={requestSandbox}
                onChange={setRequestSandbox}
                help={HELP.sandbox}
              />
            </div>
          </div>

          <div className="col-stack">
            <div className="panel">
              <div className="panel-head">
                <FieldHelpTarget help={HELP.advisorVerdict}>
                  <span className="panel-title">Advisor verdict</span>
                </FieldHelpTarget>
                <span className="panel-sub">
                  {status ? `${status.replace("_", " ")} · ${issueCount} issue(s)` : "planning..."}
                </span>
              </div>
              <div className="panel-body stack-gap">
                <Verdict
                  tone={verdict ? verdict.tone : ""}
                  chip={verdict ? verdict.chip : "-"}
                  mode={verdict ? verdict.mode : "awaiting v2 design"}
                >
                  {advisorSummary(resp)}
                </Verdict>
                {currentPlan && <MetricStrip plan={currentPlan} response={resp} />}
              </div>
            </div>

            {currentPlan && planDistribution && (
              <PlanEditor
                budget={planBudget}
                attempts={planAttempts}
                target={planTarget}
                models={planModels}
                serverScope={planServerScope}
                sandboxRequired={planSandbox}
                distribution={planDistribution}
                busy={busy === "validate"}
                onBudget={changePlanBudget}
                onAttempts={changePlanAttempts}
                onTarget={changePlanTarget}
                onModels={changePlanModels}
                onServerScope={changePlanServerScope}
                onSandbox={changePlanSandbox}
                onDistribution={changeDistribution}
              />
            )}

            {currentPlan ? (
              <>
                <div className="stat-grid">
                  <ClaimCard plan={currentPlan} />
                  <MethodCard plan={currentPlan} />
                </div>
                <PowerCurve plan={currentPlan} />
                <div className="stat-grid">
                  <AssumptionsPanel plan={currentPlan} />
                  <AlternativesPanel plan={currentPlan} />
                </div>
                <IssuesPanel issues={resp?.issues ?? currentPlan.issues} />
                <CitationsPanel plan={currentPlan} />
                <ReportPanel report={report} busy={busy === "report"} />
              </>
            ) : (
              <IssuesPanel issues={resp?.issues ?? []} />
            )}
          </div>
        </div>

        <ExportDetails response={resp} />

        <div className="footer-nav">
          <span className="panel-sub">{resp?.launchable ? "dry-run export is available" : ""}</span>
          <Button
            type="secondary"
            scale={0.85}
            disabled={!canProceed}
            onClick={() => {
              if (resp) s.carryAdvisorDesign(resp);
            }}
          >
            Carry this design into Collect
          </Button>
        </div>
      </section>
    </FieldHelpProvider>
  );
}

function FieldHelpProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<(FieldHelp & { x: number; y: number }) | null>(null);

  const value = useMemo<FieldHelpContextValue>(
    () => ({
      show: (help, x, y) => setTip({ ...help, x, y }),
      move: (x, y) => setTip((prev) => (prev ? { ...prev, x, y } : prev)),
      hide: () => setTip(null),
    }),
    [],
  );

  return (
    <FieldHelpContext.Provider value={value}>
      {children}
      {tip && (
        <div
          className="field-help-card"
          role="tooltip"
          style={
            {
              "--help-x": `${tip.x + 14}px`,
              "--help-y": `${tip.y + 14}px`,
            } as CSSProperties
          }
        >
          <b>{tip.title}</b>
          <span>{tip.body}</span>
          {tip.detail && <em>{tip.detail}</em>}
        </div>
      )}
    </FieldHelpContext.Provider>
  );
}

function FieldHelpTarget({ help, children }: { help?: FieldHelp; children: ReactNode }) {
  const tooltip = useContext(FieldHelpContext);
  if (!help || !tooltip) return <>{children}</>;
  return (
    <div
      className="field-help-target"
      onPointerEnter={(event) => tooltip.show(help, event.clientX, event.clientY)}
      onPointerMove={(event) => tooltip.move(event.clientX, event.clientY)}
      onPointerLeave={tooltip.hide}
      onFocusCapture={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        tooltip.show(help, rect.left, rect.bottom);
      }}
      onBlurCapture={tooltip.hide}
    >
      {children}
    </div>
  );
}

function Field({
  label,
  value,
  help,
  children,
}: {
  label: string;
  value: string;
  help?: FieldHelp;
  children: ReactNode;
}) {
  return (
    <FieldHelpTarget help={help}>
      <div className="row-between" style={{ marginBottom: 4 }}>
        <span className="section-label" style={{ margin: 0 }}>
          {label}
        </span>
        <span className="mono" style={{ fontSize: 12.5 }}>
          {value}
        </span>
      </div>
      {children}
    </FieldHelpTarget>
  );
}

function TextField({
  label,
  value,
  onChange,
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  help?: FieldHelp;
}) {
  return (
    <FieldHelpTarget help={help}>
      <label className="field-block">
        <span className="section-label">{label}</span>
        <input
          className="text-input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    </FieldHelpTarget>
  );
}

function CheckField({
  label,
  checked,
  onChange,
  help,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  help?: FieldHelp;
}) {
  return (
    <FieldHelpTarget help={help}>
      <label className="check-row">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{label}</span>
      </label>
    </FieldHelpTarget>
  );
}

function PlanEditor({
  budget,
  attempts,
  target,
  models,
  serverScope,
  sandboxRequired,
  distribution,
  busy,
  onBudget,
  onAttempts,
  onTarget,
  onModels,
  onServerScope,
  onSandbox,
  onDistribution,
}: {
  budget: number;
  attempts: number;
  target: number;
  models: string;
  serverScope: string;
  sandboxRequired: boolean;
  distribution: DistributionEdit;
  busy: boolean;
  onBudget: (value: number) => void;
  onAttempts: (value: number) => void;
  onTarget: (value: number) => void;
  onModels: (value: string) => void;
  onServerScope: (value: string) => void;
  onSandbox: (value: boolean) => void;
  onDistribution: (key: DistributionKey, value: number) => void;
}) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.editablePlan}>
          <span className="panel-title">Editable statistical plan</span>
        </FieldHelpTarget>
        <span className="panel-sub">{busy ? "validating..." : "v2 validate on edit"}</span>
      </div>
      <div className="panel-body stack-gap">
        <div className="edit-grid">
          <TextField
            label="plan models"
            value={models}
            onChange={onModels}
            help={HELP.planModels}
          />
          <TextField
            label="plan server scope"
            value={serverScope}
            onChange={onServerScope}
            help={HELP.planServerScope}
          />
        </div>
        <div className="edit-grid">
          <Field label="plan task budget" value={String(budget)} help={HELP.planBudget}>
            <Slider
              label="edit task budget"
              value={budget}
              min={10}
              max={320}
              step={5}
              onChange={onBudget}
            />
          </Field>
          <Field label="plan attempts / task" value={String(attempts)} help={HELP.planAttempts}>
            <Slider
              label="edit attempts per task"
              value={attempts}
              min={1}
              max={5}
              step={1}
              onChange={onAttempts}
            />
          </Field>
        </div>
        <Field
          label="plan target effect"
          value={target > 0 ? `${target} pp` : "not set"}
          help={HELP.planTarget}
        >
          <Slider
            label="edit target effect"
            value={target}
            min={0}
            max={30}
            step={1}
            onChange={onTarget}
          />
        </Field>
        <CheckField
          label="plan sandbox required"
          checked={sandboxRequired}
          onChange={onSandbox}
          help={HELP.planSandbox}
        />
        <DistributionEditor distribution={distribution} onChange={onDistribution} />
      </div>
    </div>
  );
}

function DistributionEditor({
  distribution,
  onChange,
}: {
  distribution: DistributionEdit;
  onChange: (key: DistributionKey, value: number) => void;
}) {
  return (
    <div>
      <FieldHelpTarget help={HELP.taskDistribution}>
        <div className="section-label">task distribution</div>
      </FieldHelpTarget>
      <div className="distribution-grid">
        {DISTRIBUTION_KEYS.map(([key, label]) => (
          <Field
            key={key}
            label={label}
            value={ratioLabel(distribution[key])}
            help={DISTRIBUTION_HELP[key]}
          >
            <Slider
              label={`edit ${label} ratio`}
              value={distribution[key]}
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => onChange(key, value)}
            />
          </Field>
        ))}
      </div>
    </div>
  );
}

function MetricStrip({
  plan,
  response,
}: {
  plan: StatisticalPlan;
  response: AdvisorV2DesignResponse | null;
}) {
  const power = plan.power_analysis;
  return (
    <div className="metric-strip">
      <Metric label="tasks" value={String(plan.design.task_budget)} help={HELP.metricTasks} />
      <Metric
        label="attempts"
        value={String(plan.design.attempts_per_task)}
        help={HELP.metricAttempts}
      />
      <Metric
        label="planned MDE"
        value={`${power.planned_mde_pp.toFixed(1)} pp`}
        help={HELP.plannedMde}
      />
      <Metric label="CI width" value={`${power.ci_width_pp.toFixed(1)} pp`} help={HELP.ciWidth} />
      <Metric
        label="launchable"
        value={response?.launchable ? "yes" : "no"}
        help={HELP.launchable}
      />
    </div>
  );
}

function Metric({ label, value, help }: { label: string; value: string; help?: FieldHelp }) {
  return (
    <FieldHelpTarget help={help}>
      <div className="metric">
        <span>{label}</span>
        <b>{value}</b>
      </div>
    </FieldHelpTarget>
  );
}

function ClaimCard({ plan }: { plan: StatisticalPlan }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.claimCard}>
          <span className="panel-title">Claim card</span>
        </FieldHelpTarget>
        <span className="panel-sub">{plan.design.claim_scope}</span>
      </div>
      <div className="panel-body stack-gap">
        <p className="compact-copy">{plan.claim_card.plain_language_summary}</p>
        <ClaimList
          title="Allowed"
          items={plan.claim_card.allowed_claims}
          help={{
            title: "Allowed",
            body: "Pre-run claim type this design may support if the benchmark is run according to the plan and produces suitable outcomes.",
          }}
        />
        <ClaimList
          title="Not allowed"
          items={plan.claim_card.not_allowed_claims}
          help={{
            title: "Not allowed",
            body: "Claims this design must not support, even if the run completes. These boundaries prevent overclaiming.",
          }}
        />
      </div>
    </div>
  );
}

function MethodCard({ plan }: { plan: StatisticalPlan }) {
  const trace = plan.engine_decision?.computation_trace;
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.methodCard}>
          <span className="panel-title">Method card</span>
        </FieldHelpTarget>
        <span className="panel-sub">{plan.power_analysis.method}</span>
      </div>
      <div className="panel-body stack-gap">
        <div className="method-grid">
          <Metric label="alpha" value={plan.power_analysis.alpha.toFixed(2)} help={HELP.alpha} />
          <Metric
            label="target power"
            value={plan.power_analysis.target_power.toFixed(2)}
            help={HELP.targetPower}
          />
          <Metric label="method" value={plan.design.criteria[0].test_family} help={HELP.method} />
          <Metric
            label="engine candidates"
            value={String(trace?.candidate_count ?? "-")}
            help={HELP.engineCandidates}
          />
        </div>
        <div className="pill-row">
          {(trace?.formula_versions ?? [plan.power_analysis.method]).map((formula) => (
            <span key={formula} className="tag">
              {formula}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function PowerCurve({ plan }: { plan: StatisticalPlan }) {
  const curve = plan.power_analysis.power_curve;
  const maxMde = Math.max(1, ...curve.map((point) => point.mde_pp));
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.powerCurve}>
          <span className="panel-title">Power curve</span>
        </FieldHelpTarget>
        <span className="panel-sub">unique-task planning</span>
      </div>
      <div className="panel-body">
        {curve.length === 0 ? (
          <div className="empty">No power curve returned.</div>
        ) : (
          <div className="curve-list">
            {curve.map((point) => (
              <div key={point.task_budget} className="curve-row">
                <span className="mono">{point.task_budget} tasks</span>
                <div className="curve-track" aria-hidden="true">
                  <div
                    className="curve-fill"
                    style={{ width: `${Math.max(8, (point.mde_pp / maxMde) * 100)}%` }}
                  />
                </div>
                <span className="mono">{point.mde_pp.toFixed(1)} pp MDE</span>
                <span className="faint">{point.ci_width_pp.toFixed(1)} pp CI</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AssumptionsPanel({ plan }: { plan: StatisticalPlan }) {
  const assumptions = plan.assumption_ledger;
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.assumptions}>
          <span className="panel-title">Assumptions</span>
        </FieldHelpTarget>
        <span className="panel-sub">{assumptions.paired_design ? "paired" : "unpaired"}</span>
      </div>
      <div className="panel-body stack-gap">
        <InfoRow
          label="baseline rate"
          value={assumptions.baseline_rate?.toFixed(2) ?? "not set"}
          help={HELP.baselineRate}
        />
        <InfoRow
          label="independence"
          value={assumptions.independence_assumption}
          help={HELP.independence}
        />
        <InfoRow
          label="attempts"
          value={assumptions.repeated_attempts_policy}
          help={HELP.attemptsPolicy}
        />
        <InfoRow
          label="missingness"
          value={assumptions.missingness_policy}
          help={HELP.missingness}
        />
        <InfoRow
          label="multiplicity"
          value={assumptions.multiplicity_policy}
          help={HELP.multiplicity}
        />
        {assumptions.sensitivity_notes.map((note) => (
          <div key={note} className="note-row">
            {note}
          </div>
        ))}
      </div>
    </div>
  );
}

function AlternativesPanel({ plan }: { plan: StatisticalPlan }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.alternatives}>
          <span className="panel-title">Alternatives</span>
        </FieldHelpTarget>
        <span className="panel-sub">{plan.design_alternatives.length} options</span>
      </div>
      <div className="panel-body stack-gap">
        {plan.design_alternatives.map((alt) => (
          <div key={alt.alternative_id} className="alt-row">
            <div>
              <span className={statusTag(alt.status)}>{alt.status}</span>
              <b>{alt.label}</b>
              <p>{alt.tradeoff}</p>
            </div>
            <div className="mono alt-budget">
              {alt.task_budget} x {alt.attempts_per_task}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssuesPanel({ issues }: { issues: AdvisorV2DesignResponse["issues"] }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.issues}>
          <span className="panel-title">Issues and repairs</span>
        </FieldHelpTarget>
        <span className="panel-sub">{issues.length ? `${issues.length} open` : "clear"}</span>
      </div>
      <div className="panel-body stack-gap">
        {issues.length === 0 ? (
          <div className="empty">No v2 issues returned.</div>
        ) : (
          issues.map((issue) => (
            <div key={`${issue.code}-${issue.failed_field ?? ""}`} className="issue-card">
              <div className="row-between">
                <span className={statusTag(issue.severity === "critical" ? "refused" : "warning")}>
                  {issue.severity}
                </span>
                <span className="mono faint">
                  {issue.failed_field ?? issue.failed_criterion_id}
                </span>
              </div>
              <h3>{issue.code}</h3>
              <p>{issue.message}</p>
              <p className="faint">{issue.statistical_reason}</p>
              <div className="repair-list">
                {issue.repair_options.map((repair) => (
                  <span key={repair}>{repair}</span>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function CitationsPanel({ plan }: { plan: StatisticalPlan }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.citations}>
          <span className="panel-title">Citations</span>
        </FieldHelpTarget>
        <span className="panel-sub">{plan.citations.length} local guide cards</span>
      </div>
      <div className="panel-body citation-grid">
        {plan.citations.map((citation) => (
          <div key={citation.source_id} className="citation-card">
            <div className="mono">{citation.source_id}</div>
            <b>{citation.section}</b>
            <p>{citation.snippet}</p>
            <div className="pill-row">
              {citation.source_keys.map((key) => (
                <span key={key} className="tag">
                  {key}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportPanel({ report, busy }: { report: StatisticalReport | null; busy: boolean }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <FieldHelpTarget help={HELP.postRun}>
          <span className="panel-title">Post-run report view</span>
        </FieldHelpTarget>
        <span className="panel-sub">
          {busy ? "building fixture..." : (report?.mode ?? "no report")}
        </span>
      </div>
      <div className="panel-body stack-gap">
        {!report ? (
          <div className="empty">Report appears once a v2 statistical plan is available.</div>
        ) : (
          <>
            <div className="metric-strip">
              <Metric label="status" value={report.status} help={HELP.reportStatus} />
              <Metric
                label="missing"
                value={`${report.missingness.missing_count}`}
                help={HELP.reportMissing}
              />
              <Metric
                label="confirmatory"
                value={String(report.multiplicity.confirmatory_tests)}
                help={HELP.confirmatory}
              />
              <Metric
                label="exploratory"
                value={String(report.multiplicity.exploratory_tests)}
                help={HELP.exploratory}
              />
            </div>
            <RecordList
              title="Effect sizes"
              rows={report.effect_sizes.map(effectLabel)}
              help={HELP.effectSizes}
            />
            <RecordList
              title="Confidence intervals"
              rows={report.confidence_intervals.map(ciLabel)}
              help={HELP.confidenceIntervals}
            />
            {report.rank_stability && (
              <InfoRow
                label="rank stability"
                value={report.rank_stability.summary}
                help={HELP.rankStability}
              />
            )}
            <InfoRow
              label="multiplicity"
              value={report.multiplicity.note}
              help={HELP.multiplicity}
            />
            <ClaimList
              title="Report claims"
              items={report.allowed_claims}
              help={HELP.reportClaims}
            />
            <ClaimList
              title="Report boundaries"
              items={report.not_allowed_claims}
              help={HELP.reportBoundaries}
            />
          </>
        )}
      </div>
    </div>
  );
}

function ExportDetails({ response }: { response: AdvisorV2DesignResponse | null }) {
  return (
    <details className="panel" style={{ marginTop: 16 }}>
      <summary className="panel-head">
        <FieldHelpTarget help={HELP.exportPreview}>
          <span className="panel-title">Export preview</span>
        </FieldHelpTarget>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="panel-sub">
            {response?.export_config ? "typed dry-run config" : "unavailable"}
          </span>
          <span className="summary-chev">▶</span>
        </span>
      </summary>
      <div className="panel-body">
        <pre className="export">
          {response?.export_config
            ? JSON.stringify(response.export_config, null, 2)
            : "- no export (design refused or needs clarification)"}
        </pre>
      </div>
    </details>
  );
}

function ClaimList({ title, items, help }: { title: string; items: string[]; help?: FieldHelp }) {
  return (
    <div>
      <FieldHelpTarget help={help}>
        <div className="section-label">{title}</div>
      </FieldHelpTarget>
      {items.length === 0 ? (
        <div className="faint" style={{ fontSize: 13 }}>
          none
        </div>
      ) : (
        <ul className="claim-list">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecordList({ title, rows, help }: { title: string; rows: string[]; help?: FieldHelp }) {
  return (
    <div>
      <FieldHelpTarget help={help}>
        <div className="section-label">{title}</div>
      </FieldHelpTarget>
      {rows.length === 0 ? (
        <div className="faint" style={{ fontSize: 13 }}>
          none
        </div>
      ) : (
        rows.map((row) => (
          <div key={row} className="record-row">
            {row}
          </div>
        ))
      )}
    </div>
  );
}

function InfoRow({ label, value, help }: { label: string; value: string; help?: FieldHelp }) {
  return (
    <FieldHelpTarget help={help}>
      <div className="info-row">
        <span>{label}</span>
        <b>{value}</b>
      </div>
    </FieldHelpTarget>
  );
}

function advisorSummary(response: AdvisorV2DesignResponse | null): string {
  if (!response) return "Waiting for the v2 statistical engine.";
  if (response.statistical_plan) return response.statistical_plan.claim_card.plain_language_summary;
  if (response.issues[0]) return response.issues[0].message;
  return "No statistical plan returned.";
}

function pickDistribution(distribution: TaskDistribution): DistributionEdit {
  return {
    short_chain: distribution.short_chain,
    medium_chain: distribution.medium_chain,
    long_chain: distribution.long_chain,
    cross_server_ratio: distribution.cross_server_ratio,
    recovery_required_ratio: distribution.recovery_required_ratio,
    prerequisite_strict_ratio: distribution.prerequisite_strict_ratio,
    stateful_write_ratio: distribution.stateful_write_ratio,
  };
}

function csv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function ratioLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function statusTag(status: DStatus): string {
  return `status-tag ${status}`;
}

function effectLabel(effect: StatisticalReport["effect_sizes"][number]): string {
  return `${effect.label}: ${effect.estimate_pp.toFixed(1)} pp (${effect.method})`;
}

function ciLabel(interval: StatisticalReport["confidence_intervals"][number]): string {
  return `${interval.label}: ${interval.low_pp.toFixed(1)} to ${interval.high_pp.toFixed(1)} pp (${interval.method})`;
}

function reportFixtureForPlan(plan: StatisticalPlan): OutcomeTensor {
  const models = plan.design.candidate_models.length ? plan.design.candidate_models : ["model-a"];
  const tasks = ["task.1", "task.2", "task.3", "task.4"];
  const metric = plan.design.criteria[0]?.primary_metric ?? "trace_effect_pass_rate";
  const patterns = [
    [true, true, false, false],
    [true, true, true, false],
    [true, false, false, false],
    [true, true, false, true],
  ];
  return {
    schema_version: "benchmark_advisor.outcome_tensor.v2",
    shape: "X[task, model, attempt, metric, slice]",
    tasks: tasks.map((task) => ({ axis_id: task, label: task, metadata: {} })),
    models: models.map((model) => ({ axis_id: model, label: model, metadata: {} })),
    attempts: [{ axis_id: "attempt.0", label: "attempt 0", metadata: {} }],
    metrics: [{ axis_id: metric, label: metric, metadata: { advisor_mode: plan.design.mode } }],
    slices: [{ axis_id: "all", label: "all tasks", metadata: { primary: true } }],
    values: models.flatMap((model, modelIndex) =>
      tasks.map((task, taskIndex) => ({
        task_id: task,
        model_id: model,
        attempt_id: "attempt.0",
        metric_id: metric,
        slice_id: "all",
        value: patterns[modelIndex % patterns.length][taskIndex],
        missing_reason: null,
      })),
    ),
  };
}
