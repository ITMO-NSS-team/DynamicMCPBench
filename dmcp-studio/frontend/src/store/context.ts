import { createContext, useContext } from "react";
import type { AdvisorV2DesignResponse, Mode, ScoreMode } from "../types";
import type { StudioState, View } from "./reducer";

export interface StudioActions {
  go: (view: View) => void;
  carryAdvisorDesign: (response: AdvisorV2DesignResponse) => void;
  setMode: (mode: Mode) => void;
  loadServers: () => Promise<void>;
  toggleServer: (id: string) => void;
  ensureGoal: () => Promise<void>;
  runExplore: () => void;
  runDistill: () => Promise<void>;
  toggleEquiv: (tool: string) => void;
  loadCandidates: () => Promise<void>;
  setCandidate: (name: string) => void;
  setScoreMode: (mode: ScoreMode) => void;
  runCandidate: () => void;
  clearError: () => void;
}

export type Studio = StudioState & StudioActions;

export const StudioContext = createContext<Studio | null>(null);

export function useStudio(): Studio {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error("useStudio must be used within <StudioProvider>");
  return ctx;
}
