import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { Button, Input, Textarea } from "../ui";
import { Slider } from "../components/Slider";
import { api } from "../api/client";
import { useStudio } from "../store/context";
import { advisorVerdict, advisorWhy } from "../lib/verdict";
import { Verdict } from "../components/Verdict";
import type { DResponse } from "../types";

const MODES = ["pairwise", "leaderboard", "regression", "diagnostic"] as const;

export function Design() {
  const s = useStudio();
  const [intent, setIntent] = useState(
    "Compare two local agents on long, multi-step finance workflows and tell me which is better.",
  );
  const [mode, setMode] = useState<string>("pairwise");
  const [models, setModels] = useState("qwen3.7-max, glm-5.1");
  const [budget, setBudget] = useState(120);
  const [attempts, setAttempts] = useState(3);
  const [target, setTarget] = useState(0);
  const [resp, setResp] = useState<DResponse | null>(null);
  const reqId = useRef(0);

  const modelList = useMemo(
    () =>
      models
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    [models],
  );

  useEffect(() => {
    const handle = setTimeout(async () => {
      const myId = ++reqId.current;
      const req: Record<string, unknown> = {
        schema_version: "benchmark_advisor.v1",
        intent: intent.trim() || "Compare two agents.",
        mode,
        task_budget: budget,
        attempts_per_task: attempts,
        candidate_models: modelList,
      };
      if (target > 0) req.target_detectable_effect_pp = target;
      try {
        const r = await api.advisorDesign(req);
        if (myId === reqId.current) setResp(r);
      } catch {
        /* keep the previous verdict on a transient failure */
      }
    }, 180);
    return () => clearTimeout(handle);
  }, [intent, mode, modelList, budget, attempts, target]);

  const v = resp ? advisorVerdict(resp.status) : null;
  const canProceed = resp?.status === "approved" || resp?.status === "warning";

  return (
    <section className="stage">
      <div className="eyebrow">Stage 0 — design</div>
      <h1>Design a benchmark that can test your claim</h1>
      <p className="lede">
        The advisor turns your question into a statistically grounded design — and refuses the ones
        that would fool you. A planner proposes, a validator decides, every number cites a guide
        rule.
      </p>

      <div className="split" style={{ marginTop: 28 }}>
        <div className="panel sticky-col">
          <div className="panel-head">
            <span className="panel-title">Your evaluation question</span>
            <span className="panel-sub">
              {mode} · {modelList.length} model{modelList.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="panel-body stack-gap">
            <Textarea
              width="100%"
              rows={2}
              value={intent}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setIntent(e.target.value)}
              placeholder="What do you want to find out?"
            />

            <div>
              <div className="section-label">mode</div>
              <div className="seg" role="group" aria-label="evaluation mode">
                {MODES.map((m) => (
                  <button type="button" key={m} data-on={mode === m} onClick={() => setMode(m)}>
                    {m}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="section-label">candidate models</div>
              <Input
                width="100%"
                value={models}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setModels(e.target.value)}
              />
            </div>

            <Field label="task budget" value={String(budget)}>
              <Slider value={budget} min={10} max={300} step={5} onChange={setBudget} />
            </Field>
            <Field label="attempts / task" value={String(attempts)}>
              <Slider value={attempts} min={1} max={5} step={1} onChange={setAttempts} />
            </Field>
            <Field label="target detectable effect" value={target > 0 ? `${target} pp` : "not set"}>
              <Slider value={target} min={0} max={30} step={1} onChange={setTarget} />
            </Field>
          </div>
        </div>

        <div className="col-stack">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Advisor verdict</span>
              <span className="panel-sub">
                {resp ? resp.status.replace("_", " ") : "planning…"}
              </span>
            </div>
            <div className="panel-body stack-gap">
              <Verdict
                tone={v ? v.tone : ""}
                chip={v ? v.chip : "—"}
                mode={v ? v.mode : "awaiting design"}
              >
                {resp ? advisorWhy(resp) : "Enter a question to see a proposed design."}
              </Verdict>

              {resp?.refusal && (
                <AdvisorCard
                  head={"refused · " + resp.refusal.code}
                  body={resp.refusal.reason}
                  stat={resp.refusal.statistical_reason}
                  repairs={resp.refusal.repair_options}
                />
              )}
              {resp?.clarification && (
                <AdvisorCard
                  head="needs clarification"
                  body={resp.clarification.why_needed}
                  repairs={resp.clarification.questions}
                />
              )}
              {resp?.warnings.map((w, i) => (
                <AdvisorCard
                  key={i}
                  head={w.code}
                  body={w.message}
                  stat={w.statistical_reason}
                  repairs={[w.repair_suggestion]}
                />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Why these numbers</span>
              <span className="panel-sub">guide-cited · hover a row</span>
            </div>
            <div className="panel-body">
              {!resp || resp.evidence_ledger.length === 0 ? (
                <div className="empty">Rationale appears once a design is proposed.</div>
              ) : (
                resp.evidence_ledger.map((e, i) => (
                  <div
                    key={i}
                    className="row-between"
                    title={e.hover_text}
                    style={{
                      padding: "9px 0",
                      borderBottom: "1px solid var(--hair)",
                      alignItems: "flex-start",
                    }}
                  >
                    <div>
                      <div className="mono" style={{ fontSize: 12.5 }}>
                        {e.parameter}
                      </div>
                      <div className="mono faint" style={{ fontSize: 10.5, marginTop: 3 }}>
                        {e.guide_references.map((g) => g.rule_id).join(" · ")}
                      </div>
                    </div>
                    <div className="mono" style={{ fontSize: 12.5, textAlign: "right" }}>
                      {e.value == null
                        ? "—"
                        : typeof e.value === "object"
                          ? JSON.stringify(e.value)
                          : String(e.value)}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <details className="panel" style={{ marginTop: 16 }}>
        <summary className="panel-head">
          <span className="panel-title">Export preview</span>
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="panel-sub">
              {resp?.export_config ? "dry-run config" : "unavailable"}
            </span>
            <span className="summary-chev">▶</span>
          </span>
        </summary>
        <div className="panel-body">
          <pre className="export">
            {resp?.export_config
              ? JSON.stringify(resp.export_config, null, 2)
              : "— no export (design refused or needs clarification)"}
          </pre>
        </div>
      </details>

      <div className="footer-nav">
        <span />
        <Button
          type="secondary"
          scale={0.85}
          disabled={!canProceed}
          onClick={() => s.go("collect")}
        >
          Carry this design into Collect →
        </Button>
      </div>
    </section>
  );
}

function Field({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <div>
      <div className="row-between" style={{ marginBottom: 4 }}>
        <span className="section-label" style={{ margin: 0 }}>
          {label}
        </span>
        <span className="mono" style={{ fontSize: 12.5 }}>
          {value}
        </span>
      </div>
      {children}
    </div>
  );
}

function AdvisorCard({
  head,
  body,
  stat,
  repairs,
}: {
  head: string;
  body: string;
  stat?: string | null;
  repairs: string[];
}) {
  return (
    <div className="ckpt" style={{ borderLeftColor: "var(--hair-2)" }}>
      <div
        className="faint"
        style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}
      >
        {head}
      </div>
      <div style={{ fontSize: 13, marginTop: 4, color: "var(--dim)", lineHeight: 1.5 }}>
        {body}
        {stat && <span className="faint"> ({stat})</span>}
      </div>
      {repairs.length > 0 && (
        <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
          → {repairs.join(" · ")}
        </div>
      )}
    </div>
  );
}
