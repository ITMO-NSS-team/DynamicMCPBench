import { Button } from "../ui";
import { useStudio } from "../store/context";
import { TraceList } from "../components/Trace";

export function Explore() {
  const s = useStudio();
  return (
    <section className="stage">
      <div className="eyebrow">Stage 2 — forward generation</div>
      <h1>Explore the goal live</h1>
      <p className="lede">
        A generator turns the tool surface into a realistic request; an explorer pursues it and
        every successful call is recorded. We generate forward, then distill — no graph is imposed.
      </p>

      <div className="split" style={{ marginTop: 28 }}>
        <div className="panel sticky-col">
          <div className="panel-head">
            <span className="panel-title">Generated goal</span>
            <span className="panel-sub">{s.fellback ? "fixture goal" : "persona-seeded"}</span>
          </div>
          <div className="panel-body">
            {s.persona && <p className="goal-persona">{s.persona}</p>}
            <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6, color: "var(--text)" }}>
              {s.goal || "Generating a goal from the tool surface…"}
            </p>
            <div style={{ marginTop: 18 }}>
              <Button
                type="secondary"
                scale={0.8}
                loading={s.exploring}
                disabled={!s.goal}
                onClick={s.runExplore}
              >
                Run exploration
              </Button>
            </div>
            <p className="faint" style={{ fontSize: 12, marginTop: 16, lineHeight: 1.5 }}>
              Tool names are visible to the explorer; they're stripped from the candidate later, so
              candidates can't cheat off the reference path.
            </p>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <span className={"dot" + (s.exploring ? " live" : "")} />
              Reference trace
            </span>
            <span className="panel-sub">
              {s.refCalls.length} call{s.refCalls.length === 1 ? "" : "s"}
              {s.explored ? " · success" : ""}
            </span>
          </div>
          <div className="panel-body">
            <TraceList
              calls={s.refCalls}
              empty="Run exploration to record a successful trajectory."
            />
          </div>
        </div>
      </div>

      <div className="footer-nav">
        <Button type="abort" scale={0.85} onClick={() => s.go("collect")}>
          ← Servers
        </Button>
        <Button
          type="secondary"
          scale={0.85}
          disabled={!s.explored}
          onClick={() => s.go("distill")}
        >
          Distill this trace →
        </Button>
      </div>
    </section>
  );
}
