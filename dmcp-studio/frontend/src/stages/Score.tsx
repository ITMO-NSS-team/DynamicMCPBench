import { useRef, useState, type SyntheticEvent } from "react";
import { Button } from "../ui";
import { useStudio } from "../store/context";
import { api } from "../api/client";
import { TraceList } from "../components/Trace";
import { CheckpointRow } from "../components/Checkpoint";
import { Verdict, RichLine } from "../components/Verdict";
import { contrastNote, scoreVerdict } from "../lib/verdict";
import type { Leaderboard, Mode } from "../types";

export function Score() {
  const s = useStudio();
  const done = s.lastDone;
  const verdict = done ? scoreVerdict(done, s.scoreMode) : null;

  return (
    <section className="stage" data-testid="score-stage" data-scored={done ? "1" : "0"}>
      <div className="eyebrow">Stage 4 — effect-scored evaluation</div>
      <h1>Grade the effects, not the answer</h1>
      <p className="lede">
        Replay a candidate against the checkpoints, then flip how it's scored. The verdict flips —
        and that flip is the whole point.
      </p>

      <div className="row-between" style={{ marginTop: 28, flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {s.candidates.map((c) => {
            const sel = s.candidate === c.name;
            return (
              <button
                key={c.name}
                type="button"
                className="pick"
                data-sel={sel}
                aria-pressed={sel}
                style={{ minWidth: 150 }}
                onClick={() => s.setCandidate(c.name)}
              >
                <div className="pick-name">{c.name}</div>
                <div className="pick-note">{c.note}</div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="row-between" style={{ marginTop: 16, flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span
            className="faint"
            style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}
          >
            Score by
          </span>
          <div className="seg" role="group" aria-label="scoring mode">
            <button
              type="button"
              data-on={s.scoreMode === "effect"}
              onClick={() => s.setScoreMode("effect")}
            >
              Effect
            </button>
            <button
              type="button"
              data-on={s.scoreMode === "answer"}
              onClick={() => s.setScoreMode("answer")}
            >
              Answer
            </button>
          </div>
          <Button type="secondary" scale={0.75} loading={s.scoring} onClick={s.runCandidate}>
            Run candidate
          </Button>
        </div>
        {s.ran && (
          <span className="faint" style={{ fontSize: 12 }}>
            pass³ · attempt 1 of 3 shown
          </span>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <Verdict
          tone={verdict ? (verdict.pass ? "pass" : "fail") : ""}
          chip={verdict ? (verdict.pass ? "SOLVED" : "FAILED") : "—"}
          mode={verdict ? verdict.label : "awaiting run"}
        >
          {verdict ? (
            <RichLine spans={verdict.why} />
          ) : (
            "Choose a candidate and run it to see how effect-scoring and answer-matching disagree."
          )}
        </Verdict>
      </div>

      <div className="grid cols2" style={{ marginTop: 16 }}>
        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <span className={"dot" + (s.scoring ? " live" : "")} />
              Candidate trajectory
            </span>
            <span className="panel-sub">{s.candCalls.length} calls</span>
          </div>
          <div className="panel-body">
            <TraceList calls={s.candCalls} empty="Run the candidate to replay its calls." />
            {done && (
              <div className="panel" style={{ marginTop: 14, background: "#070707" }}>
                <div className="panel-body" style={{ minHeight: 0 }}>
                  <div className="row-between" style={{ marginBottom: 8 }}>
                    <span
                      className="faint"
                      style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}
                    >
                      candidate's final answer
                    </span>
                    {s.scoreMode === "effect" && (
                      <span className="tag">not read · effect mode</span>
                    )}
                  </div>
                  <div style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--dim)" }}>
                    {done.final_answer}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">Checkpoint ledger</span>
            <span className="panel-sub">
              {done ? `${done.met_count}/${done.required} effects` : "—"}
            </span>
          </div>
          <div className="panel-body">
            {!done && <div className="empty">Run the candidate to grade its effects.</div>}
            {done &&
              s.spec &&
              done.checkpoints.map((v) => {
                const cp = s.spec!.checkpoints[v.n - 1];
                if (!cp) return null;
                return (
                  <CheckpointRow
                    key={v.n}
                    cp={cp}
                    n={v.n}
                    equiv={s.equivSets[cp.checkpoint_id]}
                    equivOn={s.equivOn}
                    onToggle={s.toggleEquiv}
                    verdict={v.met ? "met" : "unmet"}
                  />
                );
              })}
          </div>
        </div>
      </div>

      {done && (
        <p className="lede" style={{ marginTop: 18, maxWidth: 760 }}>
          <RichLine spans={contrastNote(done, s.mode === "live")} />
        </p>
      )}

      <LeaderboardPanel mode={s.mode} />

      <div className="footer-nav">
        <Button type="abort" scale={0.85} onClick={() => s.go("distill")}>
          ← Distill
        </Button>
        <span />
      </div>
    </section>
  );
}

function LeaderboardPanel({ mode }: { mode: Mode }) {
  const [lb, setLb] = useState<Leaderboard | null>(null);
  const loaded = useRef(false);

  const onToggle = (e: SyntheticEvent<HTMLDetailsElement>) => {
    if (!e.currentTarget.open || loaded.current) return;
    loaded.current = true;
    api
      .leaderboard(mode)
      .then(setLb)
      .catch(() => {
        loaded.current = false;
      });
  };

  const max = lb ? Math.max(...lb.rows.map((r) => r.pass3)) : 1;

  return (
    <details className="panel" style={{ marginTop: 18 }} onToggle={onToggle}>
      <summary className="panel-head">
        <span className="panel-title">pass³ leaderboard · parent study</span>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="panel-sub">deterministic replay</span>
          <span className="summary-chev">▶</span>
        </span>
      </summary>
      <div className="panel-body">
        {!lb ? (
          <div className="empty">Loading the leaderboard…</div>
        ) : (
          <table className="lb">
            <thead>
              <tr>
                <th>Model</th>
                <th>Group</th>
                <th style={{ width: "46%" }}>pass³</th>
                <th>%</th>
              </tr>
            </thead>
            <tbody>
              {lb.rows.map((r) => (
                <tr key={r.model}>
                  <td className="m">{r.model}</td>
                  <td>
                    <span className="grp">{r.group}</span>
                  </td>
                  <td>
                    <div
                      className="bar"
                      style={{ width: `${Math.round((r.pass3 / max) * 100)}%` }}
                    />
                  </td>
                  <td className="m">{r.pass3.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {lb?.placeholder && (
          <p className="faint" style={{ fontSize: 12, marginTop: 12 }}>
            Placeholder numbers — wired to a real export from the parent study before any public
            demo.
          </p>
        )}
      </div>
    </details>
  );
}
