import { useEffect } from "react";
import { useStudio } from "./store/context";
import type { View } from "./store/reducer";
import { ErrorBanner } from "./components/ErrorBanner";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Design } from "./stages/Design";
import { Collect } from "./stages/Collect";
import { Explore } from "./stages/Explore";
import { Distill } from "./stages/Distill";
import { Score } from "./stages/Score";

const NAV: { view: View; label: string }[] = [
  { view: "design", label: "Design" },
  { view: "collect", label: "Collect servers" },
  { view: "explore", label: "Explore live" },
  { view: "distill", label: "Distill" },
  { view: "score", label: "Score" },
];

const STAGES: Record<View, () => JSX.Element> = {
  design: Design,
  collect: Collect,
  explore: Explore,
  distill: Distill,
  score: Score,
};

export function App() {
  const s = useStudio();
  const { mode, view, loadServers, ensureGoal, runDistill, loadCandidates } = s;

  useEffect(() => {
    void loadServers();
  }, [mode, loadServers]);

  useEffect(() => {
    if (view === "explore") void ensureGoal();
    if (view === "distill") void runDistill();
    if (view === "score") void loadCandidates();
  }, [view, ensureGoal, runDistill, loadCandidates]);

  const enabled = (v: View): boolean => {
    if (v === "explore") return s.selected.length > 0;
    if (v === "distill") return s.explored;
    if (v === "score") return s.distilled;
    return true;
  };
  const done = (v: View): boolean =>
    (v === "explore" && s.explored) || (v === "distill" && s.distilled);

  const Stage = STAGES[view];

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◇
          </span>
          DMCP Studio
        </div>
        <nav className="nav" aria-label="pipeline stages">
          {NAV.map((n, i) => (
            <button
              key={n.view}
              type="button"
              className="nav-item"
              data-state={view === n.view ? "active" : undefined}
              data-done={done(n.view)}
              disabled={!enabled(n.view)}
              aria-current={view === n.view ? "step" : undefined}
              onClick={() => s.go(n.view)}
            >
              <span className="nav-num">{i}</span>
              {n.label}
            </button>
          ))}
        </nav>
        <div className="seg" role="group" aria-label="data mode">
          <button type="button" data-on={mode === "replay"} onClick={() => s.setMode("replay")}>
            Replay
          </button>
          <button type="button" data-on={mode === "live"} onClick={() => s.setMode("live")}>
            Live
          </button>
        </div>
      </header>

      <main className="shell">
        {s.error && <ErrorBanner message={s.error} onDismiss={s.clearError} />}
        <ErrorBoundary>
          <Stage />
        </ErrorBoundary>
      </main>
    </>
  );
}
