import { useCallback, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { api, openSSE } from "../api/client";
import type { AdvisorV2DesignResponse, ExploreCall, Mode, ScoreDone, ScoreMode } from "../types";
import { equivOverrides, initialState, reducer, type View } from "./reducer";
import { StudioContext, type Studio } from "./context";

const DELAY = 0.4;

export function StudioProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, () => initialState());

  const closeSSE = useRef<(() => void) | null>(null);
  const goalLoaded = useRef(false);
  const candsLoaded = useRef(false);
  const distillStarted = useRef(false);

  const go = useCallback((view: View) => {
    // leaving a stage ends any stream it owns (explore/score), so frames can't
    // keep mutating state from another stage
    closeSSE.current?.();
    dispatch({ type: "set_view", view });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const carryAdvisorDesign = useCallback((response: AdvisorV2DesignResponse) => {
    closeSSE.current?.();
    dispatch({ type: "carry_advisor_design", response });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const clearError = useCallback(() => dispatch({ type: "clear_error" }), []);
  const toggleServer = useCallback((id: string) => dispatch({ type: "toggle_server", id }), []);
  const toggleEquiv = useCallback((tool: string) => dispatch({ type: "toggle_equiv", tool }), []);
  const setCandidate = useCallback((name: string) => {
    // abandon any in-flight score so its frames/verdict can't land on the new candidate
    closeSSE.current?.();
    dispatch({ type: "set_candidate", name });
  }, []);
  const setScoreMode = useCallback(
    (mode: ScoreMode) => dispatch({ type: "set_score_mode", mode }),
    [],
  );

  const loadServers = useCallback(async () => {
    try {
      dispatch({ type: "servers_loaded", servers: await api.servers(state.mode) });
    } catch {
      dispatch({ type: "error", message: "Couldn't reach the backend to list servers." });
    }
  }, [state.mode]);

  const ensureGoal = useCallback(async () => {
    if (goalLoaded.current) return;
    goalLoaded.current = true;
    try {
      const g = await api.goal(state.mode, state.selected);
      dispatch({
        type: "goal_loaded",
        goal: g.goal,
        persona: g.persona,
        fellback: Boolean(g.fellback),
      });
    } catch {
      goalLoaded.current = false;
      dispatch({ type: "error", message: "The goal generator didn't respond." });
    }
  }, [state.mode, state.selected]);

  const runExplore = useCallback(() => {
    closeSSE.current?.();
    // a new trace must be re-distillable on the next visit to the Distill stage
    distillStarted.current = false;
    dispatch({ type: "explore_start" });
    let url = `/api/explore?mode=${state.mode}&delay=${DELAY}`;
    if (state.mode === "live") {
      url +=
        `&server_ids=${encodeURIComponent(state.selected.join(","))}` +
        `&goal=${encodeURIComponent(state.goal)}` +
        (state.persona ? `&persona=${encodeURIComponent(state.persona)}` : "");
    }
    let done = false;
    closeSSE.current = openSSE(
      url,
      {
        call: (d) => dispatch({ type: "explore_call", call: d as ExploreCall }),
        fellback: () => dispatch({ type: "explore_fellback" }),
        done: () => {
          done = true;
          dispatch({ type: "explore_done" });
          closeSSE.current?.();
        },
      },
      () => {
        dispatch({ type: "explore_error" });
        if (!done) dispatch({ type: "error", message: "The exploration stream was interrupted." });
      },
    );
  }, [state.mode, state.selected, state.goal, state.persona]);

  const runDistill = useCallback(async () => {
    if (distillStarted.current) return;
    distillStarted.current = true;
    try {
      const res = await api.distill(state.mode);
      dispatch({ type: "distilled", spec: res.task_spec, equivSets: res.equivalence_sets || {} });
    } catch {
      distillStarted.current = false;
      dispatch({ type: "error", message: "The distiller didn't return a TaskSpec." });
    }
  }, [state.mode]);

  const loadCandidates = useCallback(async () => {
    if (candsLoaded.current) return;
    candsLoaded.current = true;
    try {
      dispatch({ type: "candidates_loaded", candidates: await api.candidates(state.mode) });
    } catch {
      candsLoaded.current = false;
      dispatch({ type: "error", message: "Couldn't load the candidate agents." });
    }
  }, [state.mode]);

  const runCandidate = useCallback(() => {
    if (!state.candidate) return;
    closeSSE.current?.();
    dispatch({ type: "score_start" });
    const ov = equivOverrides(state.equivOn, state.equivSets);
    const url =
      `/api/score?mode=${state.mode}&candidate=${encodeURIComponent(state.candidate)}&delay=${DELAY}` +
      (ov ? `&equiv_overrides=${encodeURIComponent(ov)}` : "");
    let done = false;
    closeSSE.current = openSSE(
      url,
      {
        call: (d) => dispatch({ type: "score_call", call: d as ExploreCall }),
        done: (d) => {
          done = true;
          dispatch({ type: "score_done", done: d as ScoreDone });
          closeSSE.current?.();
        },
      },
      () => {
        dispatch({ type: "score_error" });
        if (!done) dispatch({ type: "error", message: "The scoring stream was interrupted." });
      },
    );
  }, [state.candidate, state.mode, state.equivOn, state.equivSets]);

  const setMode = useCallback(
    (mode: Mode) => {
      if (mode === state.mode) return;
      closeSSE.current?.();
      goalLoaded.current = false;
      candsLoaded.current = false;
      distillStarted.current = false;
      dispatch({ type: "reset_for_mode", mode });
    },
    [state.mode],
  );

  // Re-score automatically when the equivalence set is toggled after a run.
  // Refs keep the effect dependency-clean (only equivOn) and loop-free
  // (score_done never mutates equivOn, so this doesn't re-trigger itself).
  const ranRef = useRef(state.ran);
  ranRef.current = state.ran;
  const runCandidateRef = useRef(runCandidate);
  runCandidateRef.current = runCandidate;
  useEffect(() => {
    if (ranRef.current) runCandidateRef.current();
  }, [state.equivOn]);

  // Close any open stream on unmount.
  useEffect(() => () => closeSSE.current?.(), []);

  const value = useMemo<Studio>(
    () => ({
      ...state,
      go,
      carryAdvisorDesign,
      setMode,
      loadServers,
      toggleServer,
      ensureGoal,
      runExplore,
      runDistill,
      toggleEquiv,
      loadCandidates,
      setCandidate,
      setScoreMode,
      runCandidate,
      clearError,
    }),
    [
      state,
      go,
      carryAdvisorDesign,
      setMode,
      loadServers,
      toggleServer,
      ensureGoal,
      runExplore,
      runDistill,
      toggleEquiv,
      loadCandidates,
      setCandidate,
      setScoreMode,
      runCandidate,
      clearError,
    ],
  );

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}
