// Pure state machine for the studio walkthrough. No React, no I/O — every
// transition is a pure function of (state, action), so it is unit-testable.
import type {
  AdvisorV2DesignResponse,
  ExportConfig,
  CandidateCard,
  ExploreCall,
  Mode,
  ScoreDone,
  ScoreMode,
  StatisticalPlan,
  ServerCard,
  TaskSpecView,
} from "../types";

export type View = "design" | "collect" | "explore" | "distill" | "score";

export interface AdvisorCarryState {
  responseStatus: AdvisorV2DesignResponse["status"];
  statisticalPlan: StatisticalPlan;
  exportConfig: ExportConfig;
  launchable: boolean;
  sandboxRequired: boolean;
  serverScope: string[];
}

export interface StudioState {
  mode: Mode;
  view: View;
  advisorCarry: AdvisorCarryState | null;
  servers: ServerCard[];
  selected: string[];
  goal: string;
  persona: string | null;
  fellback: boolean;
  refCalls: ExploreCall[];
  exploring: boolean;
  explored: boolean;
  spec: TaskSpecView | null;
  equivSets: Record<string, string[]>;
  equivOn: Record<string, boolean>;
  distilled: boolean;
  candidates: CandidateCard[];
  candidate: string | null;
  scoreMode: ScoreMode;
  candCalls: ExploreCall[];
  scoring: boolean;
  ran: boolean;
  lastDone: ScoreDone | null;
  error: string | null;
}

export type Action =
  | { type: "set_view"; view: View }
  | { type: "carry_advisor_design"; response: AdvisorV2DesignResponse }
  | { type: "reset_for_mode"; mode: Mode }
  | { type: "servers_loaded"; servers: ServerCard[] }
  | { type: "toggle_server"; id: string }
  | { type: "goal_loaded"; goal: string; persona: string | null; fellback: boolean }
  | { type: "explore_start" }
  | { type: "explore_call"; call: ExploreCall }
  | { type: "explore_fellback" }
  | { type: "explore_done" }
  | { type: "explore_error" }
  | { type: "distilled"; spec: TaskSpecView; equivSets: Record<string, string[]> }
  | { type: "toggle_equiv"; tool: string }
  | { type: "candidates_loaded"; candidates: CandidateCard[] }
  | { type: "set_candidate"; name: string }
  | { type: "set_score_mode"; mode: ScoreMode }
  | { type: "score_start" }
  | { type: "score_call"; call: ExploreCall }
  | { type: "score_done"; done: ScoreDone }
  | { type: "score_error" }
  | { type: "error"; message: string }
  | { type: "clear_error" };

export function initialState(mode: Mode = "replay", view: View = "design"): StudioState {
  return {
    mode,
    view,
    advisorCarry: null,
    servers: [],
    selected: [],
    goal: "",
    persona: null,
    fellback: false,
    refCalls: [],
    exploring: false,
    explored: false,
    spec: null,
    equivSets: {},
    equivOn: {},
    distilled: false,
    candidates: [],
    candidate: null,
    scoreMode: "effect",
    candCalls: [],
    scoring: false,
    ran: false,
    lastDone: null,
    error: null,
  };
}

export function reducer(state: StudioState, action: Action): StudioState {
  switch (action.type) {
    case "set_view":
      return { ...state, view: action.view };

    case "carry_advisor_design": {
      const plan = action.response.statistical_plan;
      const exportConfig = action.response.export_config;
      if (!plan || !exportConfig || !action.response.launchable) return state;
      return {
        ...state,
        advisorCarry: {
          responseStatus: action.response.status,
          statisticalPlan: plan,
          exportConfig,
          launchable: action.response.launchable,
          sandboxRequired: exportConfig.generation_knobs.sandbox_required,
          serverScope: exportConfig.generation_knobs.server_scope,
        },
        selected: exportConfig.generation_knobs.server_scope.length
          ? exportConfig.generation_knobs.server_scope
          : state.selected,
        view: "collect",
      };
    }

    case "reset_for_mode":
      // restart the whole walkthrough in the new data mode
      return { ...initialState(action.mode, "collect") };

    case "servers_loaded": {
      const selected =
        state.selected.length > 0
          ? state.selected
          : action.servers.length
            ? [action.servers[0].server_id]
            : [];
      return { ...state, servers: action.servers, selected, error: null };
    }

    case "toggle_server": {
      const selected = state.selected.includes(action.id)
        ? state.selected.filter((s) => s !== action.id)
        : [...state.selected, action.id];
      return { ...state, selected };
    }

    case "goal_loaded":
      return {
        ...state,
        goal: action.goal,
        persona: action.persona,
        fellback: action.fellback,
        error: null,
      };

    case "explore_start":
      // A fresh trace invalidates the distilled spec and any prior score.
      return {
        ...state,
        refCalls: [],
        exploring: true,
        explored: false,
        spec: null,
        equivSets: {},
        equivOn: {},
        distilled: false,
        candCalls: [],
        scoring: false,
        ran: false,
        lastDone: null,
        error: null,
      };

    case "explore_call":
      return { ...state, refCalls: [...state.refCalls, action.call] };

    case "explore_fellback":
      return { ...state, fellback: true };

    case "explore_done":
      return { ...state, exploring: false, explored: true };

    case "explore_error":
      return { ...state, exploring: false };

    case "distilled": {
      const equivOn: Record<string, boolean> = {};
      for (const tools of Object.values(action.equivSets)) {
        for (const tool of tools) equivOn[tool] = true;
      }
      return {
        ...state,
        spec: action.spec,
        equivSets: action.equivSets,
        equivOn,
        distilled: true,
        // a new spec invalidates any score from a previous spec
        candCalls: [],
        scoring: false,
        ran: false,
        lastDone: null,
        error: null,
      };
    }

    case "toggle_equiv": {
      const entry = Object.entries(state.equivSets).find(([, ts]) => ts.includes(action.tool));
      if (!entry) return state;
      const others = entry[1].filter((p) => p !== action.tool);
      // keep at least one member of the set enabled
      if (state.equivOn[action.tool] && !others.some((p) => state.equivOn[p])) return state;
      return {
        ...state,
        equivOn: { ...state.equivOn, [action.tool]: !state.equivOn[action.tool] },
      };
    }

    case "candidates_loaded":
      return {
        ...state,
        candidates: action.candidates,
        candidate: state.candidate ?? (action.candidates[0]?.name || null),
        error: null,
      };

    case "set_candidate":
      return { ...state, candidate: action.name, ran: false, lastDone: null, candCalls: [] };

    case "set_score_mode":
      return { ...state, scoreMode: action.mode };

    case "score_start":
      return { ...state, candCalls: [], scoring: true, error: null };

    case "score_call":
      return { ...state, candCalls: [...state.candCalls, action.call] };

    case "score_done":
      return { ...state, scoring: false, ran: true, lastDone: action.done };

    case "score_error":
      return { ...state, scoring: false };

    case "error":
      return { ...state, error: action.message };

    case "clear_error":
      return { ...state, error: null };
  }
}

/** Tools to send as equiv overrides: enabled members, only when a strict subset. */
export function equivOverrides(
  equivOn: Record<string, boolean>,
  equivSets: Record<string, string[]>,
): string {
  const enabled = Object.entries(equivOn)
    .filter(([, on]) => on)
    .map(([t]) => t);
  const all = new Set(Object.values(equivSets).flat());
  return enabled.length && enabled.length < all.size ? enabled.join(",") : "";
}
