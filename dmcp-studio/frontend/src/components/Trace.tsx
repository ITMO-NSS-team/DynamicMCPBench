import { fmtArgs } from "../lib/format";
import type { ExploreCall } from "../types";

export function TraceList({ calls, empty }: { calls: ExploreCall[]; empty: string }) {
  if (calls.length === 0) return <div className="empty">{empty}</div>;
  return (
    <div className="trace">
      {calls.map((c) => (
        <div className="trace-row" key={c.idx}>
          <span className="trace-idx">{c.idx}</span>
          <span className="trace-call">
            <span className="trace-tool">{c.tool_name}</span>
            <span className="trace-args">({fmtArgs(c.arguments)})</span>
          </span>
          <span className={"trace-status" + (c.ok ? "" : " err")}>{c.ok ? "200" : "err"}</span>
        </div>
      ))}
    </div>
  );
}
