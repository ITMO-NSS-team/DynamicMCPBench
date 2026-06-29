import type { Checkpoint } from "../types";

function kindLabel(kind: string): string {
  return kind === "value_produced" ? "value produced" : "tool effect";
}

export interface CkptProps {
  cp: Checkpoint;
  n: number;
  equiv?: string[];
  equivOn?: Record<string, boolean>;
  onToggle?: (tool: string) => void;
  verdict?: "met" | "unmet";
}

export function CheckpointRow({ cp, n, equiv, equivOn, onToggle, verdict }: CkptProps) {
  const set = equiv && equiv.length > 1 ? equiv : null;
  return (
    <div className={"ckpt" + (verdict ? " " + verdict : "")}>
      <div className="ckpt-top">
        <span className="mono" style={{ color: "var(--mute)" }}>
          {String(n).padStart(2, "0")}
        </span>
        <span>{kindLabel(cp.kind)}</span>
        {set && <span className="tag">path-agnostic</span>}
        {verdict && <span className="ckpt-verdict">{verdict}</span>}
      </div>
      <div className="ckpt-desc">
        <span className="ckpt-id">{cp.checkpoint_id}</span> — {cp.description}
      </div>
      {set && (
        <div className="equiv">
          {set.map((t, i) => (
            <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {i > 0 && <span className="equiv-or">or</span>}
              <span
                className={"equiv-tool" + (equivOn && !equivOn[t] ? " off" : "")}
                onClick={() => onToggle?.(t)}
              >
                {t}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
