import { Button } from "../ui";
import { useStudio } from "../store/context";
import { TraceList } from "../components/Trace";
import { CheckpointRow } from "../components/Checkpoint";

export function Distill() {
  const s = useStudio();
  const cps = s.spec?.checkpoints ?? [];
  return (
    <section className="stage">
      <div className="eyebrow">Stage 3 — distillation</div>
      <h1>Compile a path-agnostic TaskSpec</h1>
      <p className="lede">
        The trace becomes effect checkpoints. A checkpoint demands an effect — that some tool from
        an equivalence set ran with the right arguments — never a specific path.
      </p>

      <div className="grid cols2" style={{ marginTop: 28 }}>
        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">Recorded trace</span>
            <span className="panel-sub">{s.refCalls.length} calls</span>
          </div>
          <div className="panel-body">
            <TraceList calls={s.refCalls} empty="No trace recorded." />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">Distilled TaskSpec</span>
            <span className="panel-sub">
              {cps.length ? `${cps.length} checkpoints` : "compiling…"}
            </span>
          </div>
          <div className="panel-body">
            {cps.length === 0 && <div className="empty">Compiling the TaskSpec…</div>}
            {cps.map((cp, i) => (
              <CheckpointRow
                key={cp.checkpoint_id}
                cp={cp}
                n={i + 1}
                equiv={s.equivSets[cp.checkpoint_id]}
                equivOn={s.equivOn}
                onToggle={s.toggleEquiv}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="footer-nav">
        <Button type="abort" scale={0.85} onClick={() => s.go("explore")}>
          ← Explore
        </Button>
        <Button type="secondary" scale={0.85} disabled={!s.distilled} onClick={() => s.go("score")}>
          Score a candidate →
        </Button>
      </div>
    </section>
  );
}
