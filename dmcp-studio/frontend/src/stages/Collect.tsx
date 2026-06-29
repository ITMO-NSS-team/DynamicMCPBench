import { Button } from "../ui";
import { useStudio } from "../store/context";
import type { ServerCard } from "../types";

function serverTag(srv: ServerCard): string {
  if (srv.dynamism === "stateful_write")
    return srv.sandbox ? "stateful · sandboxed" : "stateful · unsandboxed";
  return srv.dynamism === "static" ? "static" : "live-read";
}

export function Collect() {
  const s = useStudio();
  return (
    <section className="stage">
      <div className="eyebrow">Stage 1 — substrate</div>
      <h1>Pick the live MCP servers</h1>
      <p className="lede">
        These tools are live, not a fixed dataset. The pipeline reads each server's tool surface and
        tags it by dynamism.
      </p>

      <div className="grid servers" style={{ marginTop: 28 }}>
        {s.servers.length === 0 && <div className="empty">Loading servers…</div>}
        {s.servers.map((srv) => {
          const sel = s.selected.includes(srv.server_id);
          return (
            <button
              key={srv.server_id}
              type="button"
              className="pick"
              data-sel={sel}
              aria-pressed={sel}
              onClick={() => s.toggleServer(srv.server_id)}
            >
              <div className="row-between">
                <span className="pick-name">{srv.server_id}</span>
                <span className="tag">{serverTag(srv)}</span>
              </div>
              <div className="pick-note">{srv.description}</div>
              <div
                className="mono faint"
                style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.6 }}
              >
                {(srv.tools || []).join(" · ")}
              </div>
            </button>
          );
        })}
      </div>

      <div className="footer-nav">
        <span />
        <Button
          type="secondary"
          scale={0.85}
          disabled={s.selected.length === 0}
          onClick={() => s.go("explore")}
        >
          Generate a goal and explore →
        </Button>
      </div>
    </section>
  );
}
