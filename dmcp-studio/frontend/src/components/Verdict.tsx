import type { ReactNode } from "react";
import type { RichText } from "../lib/verdict";

/** Shared verdict readout: a status tile + a labelled explanation. */
export function Verdict({
  tone,
  chip,
  mode,
  children,
}: {
  tone: "pass" | "fail" | "";
  chip: string;
  mode: string;
  children: ReactNode;
}) {
  return (
    <div className={"verdict" + (tone ? " " + tone : "")}>
      <div className="verdict-chip" data-testid="verdict-chip">
        {chip}
      </div>
      <div className="verdict-why">
        <div className="verdict-mode">{mode}</div>
        <div className="verdict-text">{children}</div>
      </div>
    </div>
  );
}

/** Renders rich text spans (the bolded parts of verdict explanations). */
export function RichLine({ spans }: { spans: RichText }) {
  return (
    <>{spans.map((s, i) => (s.bold ? <b key={i}>{s.text}</b> : <span key={i}>{s.text}</span>))}</>
  );
}
